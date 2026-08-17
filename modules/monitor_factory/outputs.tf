output "monitor_ids" {
  description = "Map of instance key → Datadog monitor ID."
  value       = { for k, m in datadog_monitor.this : k => m.id }
}

output "monitor_ids_by_archetype" {
  description = "Map of archetype → list of monitor IDs (used to rebuild monitor-type SLO membership)."
  value = {
    for arch in distinct([for k, m in var.instances : m.archetype]) :
    arch => [for k, m in var.instances : datadog_monitor.this[k].id if m.archetype == arch]
  }
}

output "contract_report" {
  description = "Per-monitor contract summary consumed by the coverage report."
  value = {
    for k, m in var.instances : k => {
      id       = datadog_monitor.this[k].id
      name     = datadog_monitor.this[k].name
      slo_id   = m.slo_id
      runbook  = m.runbook_name
      workflow = m.workflow
      team     = m.team
      severity = m.severity
    }
  }
}
