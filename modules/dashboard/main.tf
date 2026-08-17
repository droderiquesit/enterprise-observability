resource "datadog_dashboard_json" "this" {
  for_each  = var.dashboards
  dashboard = each.value
}
