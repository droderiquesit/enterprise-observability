# Monitor factory: renders every alerting monitor in the platform from a
# fully-resolved instance definition. One grouped multi-alert monitor per
# instance — resource identity lives in the monitor GROUP (template
# variables), never in per-resource monitors.

locals {
  # Mandatory tag set carried by every monitor (tagging-standard.md). The
  # dedup/correlation keys make Event Management aggregation deterministic.
  monitor_tags = {
    for k, m in var.instances : k => concat([
      "env:${m.env}",
      "service:${m.service}",
      "team:${m.team}",
      "owner:${m.owner}",
      "domain:${m.domain}",
      "platform:${m.platform}",
      "resource_type:${m.resource_type}",
      "criticality:${m.criticality}",
      "region:${m.region}",
      "monitoring_profile:${m.monitoring_profile}",
      "managed_by:${var.managed_by}",
      "archetype:${m.archetype}",
      "severity:${m.severity}",
      "priority:p${m.priority}",
      "slo_id:${m.slo_id}",
      "failure_domain:${m.failure_domain}",
      "routing_rule:${m.routing_rule}",
      "snow_record:${m.snow_record}",
      "support_model:${m.support_model}",
      "pages:${m.pages}",
      "runbook:${replace(lower(m.runbook_name), "/[^a-z0-9]+/", "-")}",
      "automation_ref:${m.workflow}",
      "correlation_key:${m.failure_domain}.${m.env}.${m.service}",
      "dedup_key:${m.service}.${m.env}.${m.archetype}${m.dedup_suffix}",
      "managed_source:${m.managed_source}",
      ],
      m.request_id != "" ? ["request_id:${m.request_id}"] : [],
      m.extra_tags
    )
  }

  # Standard message: summary → impact → SLO → runbook → workflow → correlation
  # metadata → recovery. Routing is tag-based (notification rules) — no
  # individuals are ever @-mentioned here.
  monitor_message = {
    for k, m in var.instances : k => <<-EOT
      {{#is_alert}}
      ### ${m.title} — {{env.name}} / ${m.service}
      ${coalesce(m.summary, m.title)} Group: **{{value}}** for scope {{host.name}}{{#is_match "service.name" "*"}} {{service.name}}{{/is_match}}.
      **Impact:** ${coalesce(m.impact, "Potential customer or platform impact — check the SLO error budget below.")}
      **SLO:** ${m.slo_id}${m.slo_url != "" ? format(" — %s", m.slo_url) : ""}
      **Runbook:** ${m.runbook_name}${m.runbook_url != "" ? format(" — %s", m.runbook_url) : ""}
      **Automated diagnostics:** workflow `${m.workflow}` has been triggered; its output is attached to this event.
      **Owner:** ${m.team} (${m.owner}) · Criticality ${m.criticality} · ${m.severity}
      {{/is_alert}}
      {{#is_warning}}
      Warning threshold crossed for ${m.title} on {{value}} — investigate before this pages.
      {{/is_warning}}
      {{#is_recovery}}
      ✅ Recovered: ${m.title} for group {{value}}. Error budget impact recorded against ${m.slo_id}. No action required.
      {{/is_recovery}}
      {{#is_no_data}}
      Telemetry missing for ${m.title} — treat as a telemetry-health incident (see runbook section "no data").
      {{/is_no_data}}
    EOT
  }

  is_service_check = { for k, m in var.instances : k => m.monitor_type == "service check" }
}

resource "datadog_monitor" "this" {
  for_each = var.instances

  name     = "[${each.value.domain}][${each.value.env}][${each.value.severity}] ${each.value.title}"
  type     = each.value.monitor_type
  query    = each.value.query
  message  = local.monitor_message[each.key]
  priority = each.value.priority
  tags     = local.monitor_tags[each.key]

  # Thresholds: keys present in the instance map are passed through verbatim.
  monitor_thresholds {
    critical          = lookup(each.value.thresholds, "critical", null)
    warning           = lookup(each.value.thresholds, "warning", null)
    ok                = lookup(each.value.thresholds, "ok", null)
    critical_recovery = lookup(each.value.thresholds, "critical_recovery", null)
    warning_recovery  = lookup(each.value.thresholds, "warning_recovery", null)
  }

  # Contract behavior with policy-layer overrides.
  evaluation_delay    = local.is_service_check[each.key] ? null : coalesce(each.value.evaluation_delay, var.defaults.evaluation_delay)
  new_group_delay     = coalesce(each.value.new_group_delay, var.defaults.new_group_delay)
  notify_no_data      = coalesce(each.value.notify_no_data, var.defaults.notify_no_data)
  no_data_timeframe   = coalesce(each.value.no_data_timeframe, var.defaults.no_data_timeframe)
  renotify_interval   = coalesce(each.value.renotify_interval, var.defaults.renotify_interval)
  renotify_statuses   = var.defaults.renotify_statuses
  require_full_window = coalesce(each.value.require_full_window, var.defaults.require_full_window)
  timeout_h           = coalesce(each.value.timeout_h, var.defaults.timeout_h)
  notify_audit        = var.defaults.notify_audit
  include_tags        = var.defaults.include_tags
  restricted_roles    = var.restricted_roles
  validate            = var.api_validate

  lifecycle {
    # Cardinality guardrails (ADR-004) — fail the plan, not the pager.
    precondition {
      condition     = length(each.value.group_by) <= var.cardinality.max_group_by_keys
      error_message = "Monitor ${each.key}: group_by has ${length(each.value.group_by)} keys; the platform maximum is ${var.cardinality.max_group_by_keys}."
    }
    precondition {
      condition     = length(setintersection(toset(each.value.group_by), toset(var.cardinality.forbidden_group_keys))) == 0
      error_message = "Monitor ${each.key}: group_by uses a forbidden high-cardinality key (${join(", ", var.cardinality.forbidden_group_keys)} are banned)."
    }
    # Informational severities must not exist as monitors — they stay events.
    precondition {
      condition     = each.value.severity != "informational" || each.value.pages == false
      error_message = "Monitor ${each.key}: informational signals must not page. Model it as an event or dashboard signal instead."
    }
  }
}
