# =============================================================================
# MONITOR FACTORY
#
# Renders every alerting monitor in the platform from a fully-resolved instance
# definition produced by the policy hierarchy merge in the calling stack.
#
# One grouped multi-alert monitor per instance. Resource identity lives in the
# monitor GROUP (template variables), never in per-resource monitors — this is
# the invariant that keeps the managed object count proportional to the number
# of monitoring DECISIONS rather than the number of monitored RESOURCES.
# =============================================================================

locals {
  priority_number = { P1 = 1, P2 = 2, P3 = 3, P4 = 4 }

  # ---------------------------------------------------------------------------
  # THE MANDATORY TAG SET
  # 12 required tags + governance metadata. Everything downstream — routing,
  # correlation, dedup, coverage reporting, the scorecard — reads these and
  # nothing else. A tag is not decoration here; it is the API.
  # ---------------------------------------------------------------------------
  monitor_tags = {
    for k, m in var.instances : k => concat([
      # -- required (coverage check C3) --
      "env:${m.env}",
      "service:${m.service}",
      "team:${m.team}",
      "owner:${m.owner}",
      "tier:${m.tier}",
      # Datadog reserves the `priority` tag key and accepts only p1..p4.
      # The policy model speaks in P1..P4; the tag is lowercased here so the
      # two never drift apart. Verified against /api/v1/monitor/validate.
      "priority:${lower(m.priority)}",
      "domain:${m.domain}",
      "resource_type:${m.resource_type}",
      "monitoring_profile:${m.monitoring_profile}",
      "alert_band:${m.band}",
      "managed_by:terraform",
      "slo_id:${m.slo_id}",
      # -- governance --
      "monitor_id:${k}",
      "archetype:${m.archetype}",
      "impact_class:${m.impact_class}",
      "detection:${m.detection}",
      "signal:${m.signal}",
      "runbook:${m.runbook}",
      # The published notebook this monitor's runbook asset points at. Carried
      # as a tag as well as an asset so coverage reporting can prove the
      # attachment from a monitor list call, without a per-monitor
      # `with_assets` fetch across the whole estate.
      "runbook_notebook:${m.runbook_notebook_id}",
      "automation_ref:${m.workflow}",
      "notification_profile:${m.notification_profile}",
      "failure_domain:${m.failure_domain}",
      "support_model:${m.support_model}",
      "pages:${m.pages}",
      "managed_source:${m.managed_source}",
      # -- correlation (see platform/events/correlation-rules.yaml) --
      "correlation_key:${m.failure_domain}.${m.env}.${m.service}",
      "dedup_key:${m.service}.${m.env}.${m.archetype}${m.dedup_suffix}",
      ],
      m.region != "" ? ["region:${m.region}"] : [],
      m.compliance ? ["compliance_scope:${m.compliance_scope}"] : [],
      m.request_id != "" ? ["request_id:${m.request_id}"] : [],
      m.extra_tags
    )
  }

  # ---------------------------------------------------------------------------
  # THE MESSAGE CONTRACT
  #
  # The message carries the ALERT CONDITION, its IMPACT, its OWNERSHIP and the
  # NOTIFICATION CONTEXT — and nothing else. Procedure lives in the runbook,
  # which is a Datadog notebook attached to this monitor through the native
  # `assets` field below.
  #
  # No runbook text and no runbook URL is written here, deliberately. A URL in
  # an alert body is unversioned, unattributed, invisible to the API, and
  # (when it points at a repository) unreadable to a responder who is inside
  # Datadog at 3am. The asset attachment is the supported mechanism and it is
  # machine-readable, so coverage can PROVE every monitor has a runbook rather
  # than grepping alert text for an http:// string.
  #
  # No destination is ever written here either — routing is tag-based, resolved
  # by datadog_monitor_notification_rule. No individual is ever @-mentioned.
  # ---------------------------------------------------------------------------
  monitor_message = {
    for k, m in var.instances : k => <<-EOT
      {{#is_alert}}
      ## ${m.priority} · ${m.title}
      **WHAT:** ${m.summary}
      **WHERE:** {{value}} · env `${m.env}` · region `${m.region == "" ? "global" : m.region}`
      **SERVICE:** `${m.service}` (${m.domain} / ${m.resource_type}, ${m.tier})
      **BUSINESS IMPACT:** ${m.impact}
      **WHY IT TRIGGERED:** ${m.why}
      **OWNER:** ${m.team} · support ${m.support_model} · ${m.pages ? "this pages the on-call rotation" : "this does not page"}
      **RUNBOOK:** attached to this monitor as `${m.runbook_title != "" ? m.runbook_title : m.runbook}` — open it from the monitor's Runbook asset.
      **AUTOMATED DIAGNOSTICS:** workflow `${m.workflow}` has run; its output is attached to this event.
      **RELATED EVENTS:** correlated on `${m.failure_domain}.${m.env}.${m.service}` — deployments, infrastructure changes and platform events from the last 30 minutes are attached as context.
      **SLO / ERROR BUDGET:** `${m.slo_id}`${m.slo_impacting ? " · this condition consumes error budget" : " · no error-budget impact (non-production)"}
      {{/is_alert}}
      {{#is_warning}}
      ## ${m.title} — warning
      Approaching the alert condition on {{value}}. Investigate before it becomes ${m.priority}.
      {{/is_warning}}
      {{#is_no_data}}
      ## ${m.title} — NO DATA
      Telemetry stopped arriving for {{value}}. Treat this as a telemetry-health incident: an unmonitored resource is worse than an alerting one.
      {{/is_no_data}}
      {{#is_recovery}}
      ## Recovered · ${m.title}
      {{value}} returned to normal. Error-budget impact recorded against `${m.slo_id}`. No action required; the correlation group closes when every child recovers.
      {{/is_recovery}}
      {{#is_warning_recovery}}
      Warning cleared for {{value}}.
      {{/is_warning_recovery}}
    EOT
  }

  # Service checks and SLO alerts do not accept an evaluation delay.
  no_eval_delay = { for k, m in var.instances : k => contains(["service check", "slo alert"], m.monitor_type) }
}

resource "datadog_monitor" "this" {
  for_each = var.instances

  # Stable, parseable name. Identity for tooling comes from tags, never here.
  name     = "[${each.value.priority}][${each.value.env}][${each.value.domain}] ${each.value.title} (${each.value.band})"
  type     = each.value.monitor_type
  query    = each.value.query
  message  = local.monitor_message[each.key]
  priority = local.priority_number[each.value.priority]
  tags     = local.monitor_tags[each.key]

  # ---------------------------------------------------------------------------
  # NATIVE RUNBOOK ATTACHMENT
  #
  # `assets` is Datadog's supported monitor field for tying a monitor to the
  # resource a responder should open. `category = "runbook"` and
  # `resource_type = "notebook"` are the only values the API accepts, and
  # `resource_key` is a genuine object reference to the notebook id — not a
  # link glued into the alert body.
  #
  # Emitted only when the notebook has been published (id is non-empty): an
  # asset that points at nothing is worse than no asset, because it looks like
  # coverage. The `runbook_attached` coverage check reports any monitor that
  # reaches production without one.
  dynamic "assets" {
    for_each = each.value.runbook_notebook_id != "" ? [1] : []
    content {
      category      = "runbook"
      resource_type = "notebook"
      resource_key  = each.value.runbook_notebook_id
      name          = each.value.runbook_title != "" ? each.value.runbook_title : each.value.runbook
      url           = each.value.runbook_notebook_url
    }
  }

  monitor_thresholds {
    critical          = lookup(each.value.thresholds, "critical", null)
    warning           = lookup(each.value.thresholds, "warning", null)
    ok                = lookup(each.value.thresholds, "ok", null)
    critical_recovery = lookup(each.value.thresholds, "critical_recovery", null)
    warning_recovery  = lookup(each.value.thresholds, "warning_recovery", null)
  }

  # Contract behavior. Environment and profile overrides are already resolved
  # by the calling stack; the factory only applies defaults for nulls.
  evaluation_delay = local.no_eval_delay[each.key] ? null : coalesce(each.value.evaluation_delay, var.defaults.evaluation_delay)
  # new_group_delay exists to suppress evaluation on newly-seen GROUPS, so
  # Datadog rejects it on a monitor that has no groups at all.
  new_group_delay      = length(each.value.group_by) > 0 ? coalesce(each.value.new_group_delay, var.defaults.new_group_delay) : null
  notify_no_data       = coalesce(each.value.notify_no_data, var.defaults.notify_no_data)
  no_data_timeframe    = coalesce(each.value.notify_no_data, var.defaults.notify_no_data) ? coalesce(each.value.no_data_timeframe, var.defaults.no_data_timeframe) : null
  renotify_interval    = coalesce(each.value.renotify_interval, var.defaults.renotify_interval)
  renotify_statuses    = var.defaults.renotify_statuses
  renotify_occurrences = var.defaults.renotify_occurrences
  require_full_window  = coalesce(each.value.require_full_window, var.defaults.require_full_window)
  timeout_h            = coalesce(each.value.timeout_h, var.defaults.timeout_h)
  notify_audit         = var.defaults.notify_audit
  include_tags         = var.defaults.include_tags
  validate             = var.api_validate

  # Storm control: evaluate per group, notify per collapse key.
  notify_by = length(each.value.notify_by) > 0 ? each.value.notify_by : null

  lifecycle {
    # --- Cardinality guardrails: fail the plan, not the pager ---------------
    precondition {
      condition     = length(each.value.group_by) <= var.cardinality.max_group_by_keys
      error_message = "Monitor ${each.key}: group_by has ${length(each.value.group_by)} keys; the platform maximum is ${var.cardinality.max_group_by_keys}. Group by the smallest set needed to start investigating."
    }
    precondition {
      condition     = length(setintersection(toset(each.value.group_by), toset(var.cardinality.forbidden_group_keys))) == 0
      error_message = "Monitor ${each.key}: group_by uses a banned high-cardinality key. Banned: ${join(", ", var.cardinality.forbidden_group_keys)}."
    }
    # --- Monitor contract ---------------------------------------------------
    precondition {
      condition     = each.value.slo_id != "" && each.value.runbook != "" && each.value.workflow != "" && each.value.team != ""
      error_message = "Monitor ${each.key}: contract violation — slo_id, runbook, workflow and team are mandatory on every alerting monitor."
    }
    precondition {
      condition     = each.value.impact != "" && each.value.next_action != ""
      error_message = "Monitor ${each.key}: contract violation — every alert must state its business impact and the next action. An alert nobody can act on should not exist."
    }
    # --- Paging discipline ---------------------------------------------------
    precondition {
      condition     = !each.value.pages || each.value.env == "prod"
      error_message = "Monitor ${each.key}: only production monitors may page. ${each.value.env} paging is forbidden by environment policy."
    }
    precondition {
      condition     = !each.value.pages || contains(["P1", "P2"], each.value.priority)
      error_message = "Monitor ${each.key}: only P1 and P2 may page. P3/P4 are ticket and informational classes by definition."
    }
    # --- Query scope ---------------------------------------------------------
    precondition {
      condition     = !can(regex("\\{\\s*\\*\\s*\\}", each.value.query))
      error_message = "Monitor ${each.key}: unscoped wildcard query `{*}` matches the entire organization. Scope to env + selector."
    }
  }
}
