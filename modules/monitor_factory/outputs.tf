output "monitor_ids" {
  description = "Map of instance key → Datadog monitor ID."
  value       = { for k, m in datadog_monitor.this : k => m.id }
}


