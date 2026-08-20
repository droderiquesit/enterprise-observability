# =============================================================================
# DASHBOARDS — THREE (ADR-010, revised)
#
# This stack used to build 18: four hand-authored boards plus one generated
# drill-down per domain. The generator was the mistake, and it was a tempting
# one — a per-domain board looks like a service to the domain that owns it.
# What actually happened:
#
#   * The 14 generated boards were the same five widgets with `domain:x`
#     substituted. Nobody opened them. During an incident people went to the
#     monitor list, because it filters faster than a dashboard loads and it
#     shows the monitors that are actually firing rather than a fixed panel set.
#   * Datadog already ships the per-domain view. Filtering the monitor list by
#     `domain:database`, the Service Catalog, APM, the Infrastructure list, the
#     SLO list and the Watchdog/Kubernetes/Azure integration dashboards are all
#     maintained by Datadog, are correct the day a new resource type appears,
#     and cost this repository nothing. A hand-built copy is strictly worse: it
#     is a snapshot of what we knew about that domain on the day we generated it.
#   * Every board is a surface with an owner, a review cadence and a way to go
#     stale. Eighteen of them is eighteen ways to be wrong in public.
#
# The rule that replaces the generator: A DASHBOARD EXISTS ONLY WHERE THE
# ANSWER SPANS DOMAINS. Anything scoped to one domain, one service or one
# resource is a native Datadog view, and anything that is a periodic question
# rather than a live one is a report (platform/policy/reports.yaml,
# tools/reports.py) — which is where the five §34 report families went instead
# of becoming twenty more boards.
#
# What survives, and the audience each one is for:
#
#   enterprise-observability-overview  the platform grading itself — coverage,
#                                      ownership, alert quality, budget.
#                                      Audience: observability-platform.
#   operations-reliability             what is firing, what changed, how each
#                                      domain is behaving. Audience: responders
#                                      and the weekly reliability review.
#   slo-executive-health               the promises and whether we are keeping
#                                      them. Audience: leadership. Deliberately
#                                      free of engineering detail: a board that
#                                      answers both audiences answers neither.
# =============================================================================
locals {
  dashboards = {
    enterprise-observability-overview = file("${path.module}/dashboards/enterprise-observability-overview.json")
    operations-reliability            = file("${path.module}/dashboards/operations-reliability.json")
    slo-executive-health              = file("${path.module}/dashboards/slo-executive-health.json")
  }
}

# The resource lives directly in the stack: a module wrapping a single
# argument-for-argument resource is indirection without behavior.
resource "datadog_dashboard_json" "this" {
  for_each  = local.dashboards
  dashboard = each.value
}

# --- state safety -------------------------------------------------------------
#
# Two DIFFERENT mechanisms are in play here, and conflating them is how a
# consolidation turns into an outage of the boards people use.
#
# `moved` renames a state address, so the existing Datadog dashboard is UPDATED
# in place and keeps its id, its URL and every bookmark pointing at it. That is
# right for a board that is genuinely the same board under a new name.
#
# Dropping a key from the for_each map DESTROYS that instance. That is also
# right — retiring a board should delete it, not orphan it — but it is only
# safe because the content that mattered was folded into a surviving board
# first, and because ADR-016 keeps state in git so the destroy is reviewable in
# the plan before anyone approves it.
moved {
  from = module.dashboards.datadog_dashboard_json.this
  to   = datadog_dashboard_json.this
}

# Renamed, not replaced: same board, same URL, wider remit. The on-call widgets
# were merged into it, which is why it stopped being "operations-overview".
moved {
  from = datadog_dashboard_json.this["operations-overview"]
  to   = datadog_dashboard_json.this["operations-reliability"]
}

# Same board, retitled to say what it is. Keeping the key means the enterprise
# board people already have bookmarked does not move.
moved {
  from = datadog_dashboard_json.this["enterprise-overview"]
  to   = datadog_dashboard_json.this["enterprise-observability-overview"]
}

# DESTROYED ON THE NEXT APPLY, deliberately, and listed here so the plan is not
# the first place anybody reads about it:
#
#   oncall           its widgets (active pages, correlated events, recent
#                    changes, the responder crib sheet) are now the top of
#                    operations-reliability. A separate board that a responder
#                    has to remember to open is a board a responder does not
#                    open.
#   alert-quality    its widgets are now the body of
#                    enterprise-observability-overview. Alert quality is not a
#                    separate concern from platform health; splitting them let
#                    coverage look green on one board while the estate was
#                    unreadable on the other.
#   domain-<14>      retired in favour of the native Datadog domain views, for
#                    the reasons at the top of this file. The generator and its
#                    template are deleted with them: leaving the template would
#                    invite the next person to re-enable it.
