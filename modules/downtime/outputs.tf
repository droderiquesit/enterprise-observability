output "downtime_ids" {
  value = { for k, d in datadog_downtime_schedule.this : k => d.id }
}
