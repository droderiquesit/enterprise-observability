# =============================================================================
# TEAMS + DATADOG ON-CALL
#
# Datadog Team, primary + secondary schedules, a four-step escalation policy
# and the team's tag-based routing rules.
#
# DESIGN RULE — THE STRUCTURE EXISTS BEFORE THE PEOPLE DO.
# Every team gets the full structure whether or not a roster has been synced
# yet. A team with no members produces a schedule with an UNASSIGNED position,
# never an invented user, and the escalation ladder still has all four steps.
# Rosters arrive later as a pure data change (var.teams[*].members) with no
# structural diff. The previous version gated schedules, policies and routing
# rules behind `length(members) > 0`, which meant a fresh org had teams that
# looked configured but could not be paged at all.
# =============================================================================

resource "datadog_team" "this" {
  for_each    = var.teams
  handle      = each.key
  name        = each.value.name
  description = "${each.value.description} (managed_by:terraform)"
}

locals {
  # Escape hatch, not a gate on rosters. See variables.tf: schedules are
  # created for EVERY team, and only an org-level API rejection of unassigned
  # positions should ever flip this to false.
  schedules_enabled = var.create_schedules

  # Datadog models "nobody is on call for this position" as a member slot whose
  # user is null — the provider documents `users` as "a valid user id or `null`
  # to represent No-one" and enforces at least one entry per layer. So an empty
  # roster becomes a single unassigned position rather than an empty list, and
  # the schedule/rotation shape is reviewable before anyone is named.
  primary_users = {
    for k, t in var.teams : k => length(t.members) > 0 ? t.members : [null]
  }
  secondary_users = {
    for k, t in var.teams : k => length(t.secondary_members) > 0 ? t.secondary_members : [null]
  }

  schedule_teams = local.schedules_enabled ? var.teams : {}

  # Step 4 target. With no leadership team provisioned, fall back to the owning
  # team: a four-step ladder whose last step points nowhere would silently drop
  # the page, which is exactly the failure this module exists to prevent.
  leadership_target = {
    for k, t in var.teams : k => (
      var.leadership_team_id != "" ? var.leadership_team_id : datadog_team.this[k].id
    )
  }
}

# -----------------------------------------------------------------------------
# SCHEDULES — primary and secondary, one layer each.
# -----------------------------------------------------------------------------
resource "datadog_on_call_schedule" "primary" {
  for_each = local.schedule_teams

  name      = "${each.value.name} — primary"
  time_zone = each.value.time_zone
  teams     = [datadog_team.this[each.key].id]

  layer {
    name           = "primary-rotation"
    effective_date = var.schedule_effective_date
    rotation_start = var.schedule_effective_date
    users          = local.primary_users[each.key]
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

resource "datadog_on_call_schedule" "secondary" {
  for_each = local.schedule_teams

  name      = "${each.value.name} — secondary"
  time_zone = each.value.time_zone
  teams     = [datadog_team.this[each.key].id]

  layer {
    name           = "secondary-rotation"
    effective_date = var.schedule_effective_date
    rotation_start = var.schedule_effective_date
    users          = local.secondary_users[each.key]
    interval {
      days = each.value.rotation_days
    }
    # The secondary deliberately carries NO business-hours restriction even for
    # business-hours teams: it is the backstop for a missed primary ack, and a
    # restriction there would reopen the same "page falls off the end" hole.
  }
}

# -----------------------------------------------------------------------------
# ESCALATION POLICY — four steps.
#
#   step 1  t+0m   primary schedule    (or the team, if schedules are disabled)
#   step 2  t+10m  secondary schedule  (or the team, if schedules are disabled)
#   step 3  t+20m  the owning team — team lead / whole rotation
#   step 4  t+30m  incident commander / platform leadership team
#
# Times are cumulative from the page; each `escalate_after_seconds` is the
# dwell time of its own step. resolve_page_on_policy_end = false and retries=2
# mean an unacknowledged page keeps cycling rather than quietly resolving.
#
# There is ONE policy per team, driving the paging path (P1, and P2 with
# confirmed impact). P2's own 10/20 ack contract from platform/policy/
# priorities.yaml is enforced by the routing-rule urgency split below, not by a
# second escalation policy — see the routing rules comment.
# -----------------------------------------------------------------------------
resource "datadog_on_call_escalation_policy" "this" {
  for_each = var.teams

  name                       = "${each.value.name} — escalation"
  resolve_page_on_policy_end = false
  retries                    = 2
  teams                      = [datadog_team.this[each.key].id]

  # Step 1 — primary on-call.
  step {
    assignment             = "default"
    escalate_after_seconds = var.step1_after_minutes * 60

    dynamic "target" {
      for_each = local.schedules_enabled ? [1] : []
      content {
        schedule = datadog_on_call_schedule.primary[each.key].id
      }
    }
    dynamic "target" {
      for_each = local.schedules_enabled ? [] : [1]
      content {
        team = datadog_team.this[each.key].id
      }
    }
  }

  # Step 2 — secondary on-call.
  step {
    assignment             = "default"
    escalate_after_seconds = var.step2_after_minutes * 60

    dynamic "target" {
      for_each = local.schedules_enabled ? [1] : []
      content {
        schedule = datadog_on_call_schedule.secondary[each.key].id
      }
    }
    dynamic "target" {
      for_each = local.schedules_enabled ? [] : [1]
      content {
        team = datadog_team.this[each.key].id
      }
    }
  }

  # Step 3 — team lead / whole rotation. round-robin so a repeatedly
  # unacknowledged page does not always land on the same person.
  step {
    assignment             = "round-robin"
    escalate_after_seconds = var.step3_after_minutes * 60
    target {
      team = datadog_team.this[each.key].id
    }
  }

  # Step 4 — incident commander / platform leadership.
  step {
    assignment             = "default"
    escalate_after_seconds = var.step4_after_minutes * 60
    target {
      team = local.leadership_target[each.key]
    }
  }
}

# -----------------------------------------------------------------------------
# TEAM ROUTING RULES
#
# BUG FIXED HERE: these rules used to query `tags.severity:sev1` and
# `tags.severity:sev2`. No `severity` tag is emitted anywhere in this platform.
# modules/monitor_factory tags monitors with `priority:p1..p4` (LOWERCASE, from
# `"priority:${lower(m.priority)}"`) and `pages:true|false`. The severity
# queries therefore matched NOTHING, every single page fell through to the
# urgency:"low" catch-all, and no escalation policy was ever attached to a real
# page — a silent, total loss of the paging path that still looked configured
# in the UI.
#
# The rules below read the tags that actually exist:
#
#   rule 1  priority:p1                  → high urgency, escalation policy
#   rule 2  priority:p2 AND pages:true   → high urgency, escalation policy
#                                          (pages:true is what platform/policy/
#                                          priorities.yaml calls "confirmed
#                                          impact": SLO burn or composite. A
#                                          symptom-raised P2 has pages:false and
#                                          never reaches this rule.)
#   rule 3  terminal catch-all           → low urgency, escalation policy
#                                          (required by the API; see below)
#
# P2 gets urgency "high" on purpose: a P2 that reaches this resource has already
# passed the paging gate, so it is a real page. The P1-vs-P2 difference in ack
# time (5/10 vs 10/20 minutes in priorities.yaml) is expressed by the urgency
# split — high urgency overrides a responder's quiet hours, low urgency does
# not — rather than by a second escalation policy per priority, which would
# double the policy estate for one timer.
# -----------------------------------------------------------------------------
resource "datadog_on_call_team_routing_rules" "this" {
  for_each = var.teams

  id = datadog_team.this[each.key].id

  # P1 — page immediately, around the clock.
  rule {
    query             = "tags.priority:p1 tags.team:${each.key}"
    urgency           = "high"
    escalation_policy = datadog_on_call_escalation_policy.this[each.key].id
  }

  # P2 with confirmed impact (SLO burn / composite) — page.
  rule {
    query             = "tags.priority:p2 tags.pages:true tags.team:${each.key}"
    urgency           = "high"
    escalation_policy = datadog_on_call_escalation_policy.this[each.key].id
  }

  # API-REQUIRED TERMINAL RULE — and the only other rule that can exist.
  #
  # Datadog rejects the whole request with a 400 unless the LAST rule is a true
  # catch-all: no query, no time restriction, and an escalation policy. It also
  # rejects `urgency` on any rule that has no escalation policy
  # ("urgency is only allowed if an escalation policy is provided" — a live
  # apply, not a plan, is what surfaced this).
  #
  # That pair of constraints removes the "notify, never page" rule that used to
  # sit here, and it should never have existed anyway: ONLY monitors that page
  # reach On-Call at all. modules/notification_rules attaches the
  # `@oncall-<team>` recipient exclusively where `pages:true`, so a P3, a P4 or
  # a symptom-raised P2 never arrives at this resource — Teams and ServiceNow
  # carry those. Anything that does arrive is by definition a page and must
  # reach a responder; low urgency is what keeps it from overriding quiet hours.
  rule {
    urgency           = "low"
    escalation_policy = datadog_on_call_escalation_policy.this[each.key].id
  }
}
