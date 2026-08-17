output "rule_ids" {
  description = "Map of routing rule key → Datadog notification rule ID."
  value       = { for k, r in datadog_monitor_notification_rule.this : k => r.id }
}

output "routing_matrix" {
  description = "Human-readable routing matrix, published as evidence by the coverage report."
  value       = { for k, r in local.rules : k => r.recipients }
}
