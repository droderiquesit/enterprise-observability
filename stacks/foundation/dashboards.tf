# Minimal dashboard set (ADR-010): 4 dashboards total. Domain drill-downs are
# generated from one template per domain; Datadog-native Service Catalog / APM
# / Infrastructure views cover per-service detail — no per-service dashboards.
locals {
  domains_list = keys(yamldecode(file("${local.policy_dir}/domains.yaml")).domains)

  dashboards = merge(
    {
      enterprise-overview = file("${path.module}/dashboards/enterprise-overview.json")
      operations-overview = file("${path.module}/dashboards/operations-overview.json")
      oncall              = file("${path.module}/dashboards/oncall.json")
    },
    {
      for d in local.domains_list :
      "domain-${d}" => templatefile("${path.module}/dashboards/domain-template.json.tftpl", { domain = d })
    }
  )
}

module "dashboards" {
  source     = "../../modules/dashboard"
  dashboards = local.dashboards
}
