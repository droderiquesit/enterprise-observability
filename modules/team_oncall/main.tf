# Teams + Datadog On-Call: schedule, escalation policy, and tag-based routing
# rules per team. Escalation: on-call responder → whole rotation → team
# management, driven by ack timeouts from routing policy.

resource "datadog_team" "this" {
  for_each    = var.teams
  handle      = each.key
  name        = each.value.name
  description = "${each.value.description} (managed_by:${var.managed_by})"
}

locals {
  # Schedules/policies only for teams that have rotation members.
  oncall_teams = { for k, t in var.teams : k => t if length(t.members) > 0 }
}

resource "datadog_on_call_schedule" "this" {
  for_each = local.oncall_teams

  name      = "${each.value.name} — primary"
  time_zone = each.value.time_zone
  teams     = [datadog_team.this[each.key].id]

  layer {
    name           = "weekly-rotation"
    effective_date = var.schedule_effective_date
    rotation_start = var.schedule_effective_date
    users          = each.value.members
    interval {
      days = each.value.rotation_days
    }
    dynamic "restriction" {
      for_each = each.value.business_hours_only ? [1] : []
      content {
        end_day    = "friday"
        end_time   = "18:00:00"
        start_day  = "monday"
        start_time = "08:00:00"
      }
    }
  }
}

resource "datadog_on_call_escalation_policy" "this" {
  for_each = local.oncall_teams

  name                       = "${each.value.name} — escalation"
  resolve_page_on_policy_end = false
  retries                    = 2
  teams                      = [datadog_team.this[each.key].id]

  step {
    assignment             = "default"
    escalate_after_seconds = each.value.ack_timeout_minutes * 60
    target {
      schedule = datadog_on_call_schedule.this[each.key].id
    }
  }

  step {
    assignment             = "round-robin"
    escalate_after_seconds = each.value.escalation_timeout_minutes * 60
    target {
      team = datadog_team.this[each.key].id
    }
  }
}

resource "datadog_on_call_team_routing_rules" "this" {
  for_each = local.oncall_teams

  id = datadog_team.this[each.key].id

  # sev1: page with high urgency around the clock.
  rule {
    query             = "tags.severity:sev1 tags.team:${each.key}"
    urgency           = "high"
    escalation_policy = datadog_on_call_escalation_policy.this[each.key].id
  }
  # sev2: page, normal urgency.
  rule {
    query             = "tags.severity:sev2 tags.team:${each.key}"
    urgency           = "low"
    escalation_policy = datadog_on_call_escalation_policy.this[each.key].id
  }
  # everything else: no page (ServiceNow/Teams routing handles it).
  rule {
    query   = "tags.team:${each.key}"
    urgency = "low"
  }
}
