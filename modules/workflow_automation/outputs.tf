output "workflow_ids" {
  value = { for k, w in datadog_workflow_automation.this : k => w.id }
}
