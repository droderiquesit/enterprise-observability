output "dashboard_ids" {
  value = { for k, d in datadog_dashboard_json.this : k => d.id }
}
