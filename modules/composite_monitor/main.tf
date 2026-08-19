# =============================================================================
# COMPOSITE MONITOR MODULE
#
# A composite turns a noisy symptom into a confirmed impact. Its members are
# ordinary factory monitors; the composite references them by ID and pages so
# that they do not have to.
#
# Datadog evaluates a composite PER GROUP only when every member shares the
# same grouping. The precondition below enforces that — a composite of
# mismatched members silently degrades into "any group of A and any group of
# B", which correlates unrelated resources and is worse than no composite.
# =============================================================================

locals {
  priority_number = { P1 = 1, P2 = 2, P3 = 3, P4 = 4 }

  composite_query = {
    for k, c in var.composites :
    k => join(" ${c.operator == "OR" ? "||" : "&&"} ", [for id in c.member_ids : tostring(id)])
  }
}

resource "datadog_monitor" "this" {
  for_each = var.composites

  name    = "[${each.value.priority}][${each.value.env}][${each.value.domain}] ${each.value.title} (composite)"
  type    = "composite"
  query   = local.composite_query[each.key]
  message = <<-EOT
    {{#is_alert}}
    ## ${each.value.priority} · ${each.value.title} — CONFIRMED
    **WHAT:** ${each.value.description}
    **WHY THIS IS DIFFERENT:** every member condition below is true at the same time, which is what separates a real incident from an isolated symptom:
    ${join("\n", [for m in each.value.member_titles : "  - ${m}"])}
    **WHERE:** {{value}} · env `${each.value.env}`
    **SERVICE / SCOPE:** `${each.value.service}` (${each.value.domain})
    **BUSINESS IMPACT:** ${each.value.impact}
    **OWNER:** ${each.value.team}${length(each.value.cc_teams) > 0 ? " (observers: ${join(", ", each.value.cc_teams)})" : ""} · ${each.value.pages ? "pages the on-call rotation" : "does not page"}
    **DO THIS NEXT:** ${each.value.next_action}
    **RUNBOOK:** attached to this monitor as `${each.value.runbook_title != "" ? each.value.runbook_title : each.value.runbook}` — open it from the monitor's Runbook asset.
    **AUTOMATED DIAGNOSTICS:** workflow `${each.value.workflow}`.
    **SLO / ERROR BUDGET:** `${each.value.slo_id}`
    {{/is_alert}}
    {{#is_recovery}}
    ## Recovered · ${each.value.title}
    At least one member condition cleared, so the confirmed-impact state no longer holds. Individual member monitors may still be alerting — check before closing the incident.
    {{/is_recovery}}
  EOT

  priority = local.priority_number[each.value.priority]

  tags = concat([
    "env:${each.value.env}",
    "service:${each.value.service}",
    "team:${each.value.team}",
    "owner:${each.value.team}",
    "tier:${each.value.tier}",
    "priority:${lower(each.value.priority)}",
    "domain:${each.value.domain}",
    "resource_type:composite",
    "monitoring_profile:${each.value.monitoring_profile}",
    "alert_band:${each.value.band}",
    "managed_by:terraform",
    "slo_id:${each.value.slo_id}",
    "monitor_id:${each.key}",
    "archetype:composite",
    "impact_class:${each.value.impact_class}",
    "detection:composite",
    "signal:confirmed_impact",
    "runbook:${each.value.runbook}",
    "runbook_notebook:${each.value.runbook_notebook_id}",
    "automation_ref:${each.value.workflow}",
    "notification_profile:${each.value.notification_profile}",
    "failure_domain:${each.value.failure_domain}",
    "support_model:${each.value.support_model}",
    "pages:${each.value.pages}",
    "managed_source:composite",
    "correlation_key:${each.value.failure_domain}.${each.value.env}.${each.value.service}",
    "dedup_key:${each.value.service}.${each.value.env}.composite.${each.key}",
    ], each.value.extra_tags
  )

  # Native runbook attachment — identical contract to modules/monitor_factory.
  # A composite is the platform's confirmed-impact signal, so it is exactly the
  # monitor a responder opens the runbook from.
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

  # Composites inherit the platform monitor-option defaults rather than the
  # provider's, so a composite behaves like every other managed monitor.
  notify_no_data       = false
  no_data_timeframe    = null
  renotify_interval    = each.value.renotify_interval
  renotify_statuses    = var.defaults.renotify_statuses
  renotify_occurrences = var.defaults.renotify_occurrences
  require_full_window  = var.defaults.require_full_window
  # AUTO-RESOLVE. A composite stays triggered for exactly as long as its
  # members do, so it needs a window of its own; the calling stack resolves one
  # from priority policy and this is the floor if it ever passes none.
  timeout_h    = coalesce(each.value.timeout_h, var.defaults.timeout_h)
  notify_audit = var.defaults.notify_audit
  include_tags = var.defaults.include_tags
  validate     = var.api_validate

  lifecycle {
    # --- Auto-resolve contract ----------------------------------------------
    precondition {
      condition = (
        coalesce(each.value.timeout_h, var.defaults.timeout_h) >= var.defaults.auto_resolve_min_hours
        && coalesce(each.value.timeout_h, var.defaults.timeout_h) <= var.defaults.auto_resolve_max_hours
      )
      error_message = "Composite ${each.key}: auto-resolve window is ${coalesce(each.value.timeout_h, var.defaults.timeout_h)}h, outside the policy range ${var.defaults.auto_resolve_min_hours}-${var.defaults.auto_resolve_max_hours}h. 0 means the composite stays triggered forever, and a composite stuck in alert suppresses the next confirmed-impact page."
    }
    precondition {
      condition     = length(each.value.member_ids) >= 2 && length(each.value.member_ids) <= var.max_members
      error_message = "Composite ${each.key}: needs between 2 and ${var.max_members} members. A composite nobody can reason about is not a safety feature."
    }
    precondition {
      condition     = length(distinct(each.value.member_group_by)) <= 1
      error_message = "Composite ${each.key}: all members must share an IDENTICAL group_by. Mismatched groupings make Datadog correlate unrelated groups. Members grouped by: ${join(" | ", distinct(each.value.member_group_by))}."
    }
    # Cross-team composites are the valuable ones (cause in one domain,
    # symptom in another). They are permitted — but the ownership question must
    # be answered explicitly in policy, never inferred.
    precondition {
      condition     = length(setsubtract(toset(each.value.member_teams), toset(concat([each.value.team], each.value.cc_teams)))) == 0
      error_message = "Composite ${each.key}: members span teams ${join(", ", distinct(each.value.member_teams))}, but the composite declares owner_team=${each.value.team} and cc_teams=[${join(", ", each.value.cc_teams)}]. Name every member team as owner or cc so the alert has one owner and known observers."
    }
    precondition {
      condition     = !each.value.pages || each.value.env == "prod"
      error_message = "Composite ${each.key}: only production composites may page."
    }
  }
}
