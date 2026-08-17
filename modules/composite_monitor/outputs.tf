output "composite_ids" {
  description = "Map of composite key → Datadog monitor ID."
  value       = { for k, m in datadog_monitor.this : k => m.id }
}

output "contract_report" {
  description = "Composite contract evidence for the coverage report and scorecard."
  value = {
    for k, c in var.composites : k => {
      id       = datadog_monitor.this[k].id
      name     = datadog_monitor.this[k].name
      members  = c.member_titles
      priority = c.priority
      team     = c.team
      slo_id   = c.slo_id
      runbook  = c.runbook
      workflow = c.workflow
      pages    = c.pages
    }
  }
}
