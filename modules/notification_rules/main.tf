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
        recipients = distinct(compact(concat(
          # Team channel — low-noise for P4, env-suffixed for non-production.
          #
          # BUG FIXED: row.channel_suffix used to be applied ONLY to the
          # non-low-noise arm of this ternary. A non-production P4 routes to the
          # low-noise channel, so it landed in the UNSUFFIXED PRODUCTION
          # low-noise channel — QA and stage informational alerts leaking into
          # the production signal stream, where they are indistinguishable from
          # real production hygiene findings. The suffix is a property of the
          # ENVIRONMENT, not of which of the two channels was picked, so it
          # applies to both arms.
          [row.use_low_noise_channel
            ? "@teams-${team.low_noise_channel}${row.channel_suffix}"
          : "@teams-${team.channel}${row.channel_suffix}"],
          # ServiceNow incident or task.
          row.servicenow_handle != "" ? [row.servicenow_handle] : [],
          # Datadog On-Call page.
          row.page ? ["@oncall-${tkey}"] : [],
          # Broadcast channels (major incident bridge, exec, release train).
          row.extra_channels,
          # Security profiles notify the owning team for CONTEXT, never as the
          # primary responder — the responder is the security rotation.
          #
          # BUG FIXED (partially — see below): `team` here is the team the rule
          # is being generated FOR, and security_operational applies only to
          # `security`, so this resolved to the security team's own channel and
          # listed it twice. `distinct()` now collapses that duplicate.
          #
          # LIMITATION, stated plainly: this does not implement a real
          # owner-cc. A true cc-the-owner needs the OWNING team of the firing
          # resource, and the routing row shape (profile × priority × pages)
          # carries no owner — the owner is only knowable per monitor, from the
          # monitor's own `team:` tag, which the security override has already
          # rewritten to `security`. Delivering it means adding an owner
          # dimension to the routing rows and a second filter tag, which is a
          # restructure of the routing matrix, not a fix here.
          row.cc_owner_team ? ["@teams-${team.channel}"] : [],
        )))
      }
    }
  ]...)
}

resource "datadog_monitor_notification_rule" "this" {
  for_each = local.rules

  name = "route-${each.value.profile}-${each.value.priority}-${each.value.pages ? "page" : "nopage"}-${each.value.team}"
  # Recipients use the monitor-message mention form ("@handle") throughout
  # the policy; the notification-rule API wants the bare handle and rejects
  # a leading '@' ("Recipient handle should not start with '@'" — found by
  # the first live foundation apply).
  recipients = [for r in each.value.recipients : trimprefix(r, "@")]

  filter {
    tags = [
      "managed_by:terraform",
      "notification_profile:${each.value.profile}",
      "priority:${lower(each.value.priority)}",
      # `pages` is part of the filter because priority alone does not decide
      # whether a human is woken. See platform/policy/priorities.yaml.
      "pages:${each.value.pages}",
      "team:${each.value.team}",
    ]
  }
}
