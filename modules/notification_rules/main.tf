# =============================================================================
# CENTRAL TAG-BASED ROUTING
#
# Monitors contain NO destinations. They carry tags; these rules resolve tags
# to people and systems:
#
#     notification_profile × priority × team  →  Teams + ServiceNow + On-Call
#
# Changing where a team's P1s go is one line in teams.yaml and touches ZERO
# monitors. That is the difference between a routing change being a five-minute
# PR and a 400-monitor migration.
# =============================================================================

locals {
  # One rule per (routing row × team). A profile that defines no route for a
  # priority produces no rule at all — silence is explicit, never accidental.
  rules = merge([
    for rkey, row in var.routes : {
      for tkey, team in { for h, tv in var.teams : h => tv if contains(row.teams, h) } : "${rkey}.${tkey}" => {
        profile  = row.profile
        priority = row.priority
        pages    = row.pages
        team     = tkey
        recipients = compact(concat(
          # Team channel — low-noise for P4, env-suffixed for non-production.
          [row.use_low_noise_channel
            ? "@teams-${team.low_noise_channel}"
          : "@teams-${team.channel}${row.channel_suffix}"],
          # ServiceNow incident or task.
          row.servicenow_handle != "" ? [row.servicenow_handle] : [],
          # Datadog On-Call page.
          row.page ? ["@oncall-${tkey}"] : [],
          # Broadcast channels (major incident bridge, exec, release train).
          row.extra_channels,
          # Security profiles notify the owning team for CONTEXT, never as the
          # primary responder — the responder is the security rotation.
          row.cc_owner_team ? ["@teams-${team.channel}"] : [],
        ))
      }
    }
  ]...)
}

resource "datadog_monitor_notification_rule" "this" {
  for_each = local.rules

  name       = "route-${each.value.profile}-${each.value.priority}-${each.value.pages ? "page" : "nopage"}-${each.value.team}"
  recipients = each.value.recipients

  filter {
    tags = [
      "managed_by:${var.managed_by}",
      "notification_profile:${each.value.profile}",
      "priority:${lower(each.value.priority)}",
      # `pages` is part of the filter because priority alone does not decide
      # whether a human is woken. See platform/policy/priorities.yaml.
      "pages:${each.value.pages}",
      "team:${each.value.team}",
    ]
  }
}
