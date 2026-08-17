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

module "dashboards" {
  source     = "../../modules/dashboard"
  dashboards = local.dashboards
}
