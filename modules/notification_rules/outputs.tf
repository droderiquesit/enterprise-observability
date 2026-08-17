output "rule_ids" {
  value = { for k, r in datadog_monitor_notification_rule.this : k => r.id }
}
