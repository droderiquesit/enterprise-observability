output "monitor_ids" {
  description = "Map of instance key → Datadog monitor ID."
  value       = { for k, m in datadog_monitor.this : k => m.id }
}

output "monitor_ids_by_archetype" {
  description = "archetype → list of Datadog monitor IDs. Used to rebuild monitor-type SLO membership and to resolve composite members."
  value = {
    for arch in distinct([for k, m in var.instances : m.archetype]) :
    arch => [for k, m in var.instances : datadog_monitor.this[k].id if m.archetype == arch]
  }
}

output "contract_report" {
  description = "Per-monitor contract evidence consumed by the coverage report and the quality scorecard."
  value = {
    for k, m in var.instances : k => {
      id                   = datadog_monitor.this[k].id
      name                 = datadog_monitor.this[k].name
      archetype            = m.archetype
      env                  = m.env
      band                 = m.band
      priority             = m.priority
      impact_class         = m.impact_class
      detection            = m.detection
      slo_id               = m.slo_id
      runbook              = m.runbook
      workflow             = m.workflow
      team                 = m.team
      notification_profile = m.notification_profile
      pages                = m.pages
      group_by             = m.group_by
      managed_source       = m.managed_source
    }
  }
}
