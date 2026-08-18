# =============================================================================
# DASHBOARDS — a fixed, small set (ADR-010)
#
# Four hand-authored boards plus one generated drill-down per domain. Per-
# service views are Datadog-native (Service Catalog, APM, Infrastructure,
# SLO list) and are better than anything we would hand-build: a custom
# dashboard per service at 100k services is unmaintainable and redundant.
# =============================================================================
locals {
  domains_list = keys(local.domains)

  dashboards = merge(
    {
      enterprise-overview = file("${path.module}/dashboards/enterprise-overview.json")
      operations-overview = file("${path.module}/dashboards/operations-overview.json")
      oncall              = file("${path.module}/dashboards/oncall.json")
      alert-quality       = file("${path.module}/dashboards/alert-quality.json")
    },
    {
      for d in local.domains_list :
      "domain-${d}" => templatefile("${path.module}/dashboards/domain-template.json.tftpl", {
        domain       = d
        display_name = local.domains[d].display
        owner_team   = local.domains[d].owner_team
      })
    }
  )
}

# The resource lives directly in the stack: a module wrapping a single
# argument-for-argument resource is indirection without behavior. The moved
# block keeps the existing state addresses so the inlining is a no-op apply.
resource "datadog_dashboard_json" "this" {
  for_each  = local.dashboards
  dashboard = each.value
}

moved {
  from = module.dashboards.datadog_dashboard_json.this
  to   = datadog_dashboard_json.this
}
