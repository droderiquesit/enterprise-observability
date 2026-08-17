output "monitor_count" {
  description = "Total managed monitors. The number that must stay bounded no matter how large the estate becomes."
  value = {
    archetype_packs = length(local.demoted_archetype_instances)
    self_service    = length(local.custom_instances)
    burn_rate       = length(local.burn_instances)
    composite       = length(local.composite_instances)
    total           = local.total_managed_monitors
    budget          = local.global.cardinality.max_total_managed_monitors
  }
}

output "monitor_ids" {
  value = merge(
    module.coverage_monitors.monitor_ids,
    module.burn_monitors.monitor_ids,
    module.composites.composite_ids,
  )
}

output "slo_ids" {
  value = module.slos.slo_datadog_ids
}

output "instances_by_env" {
  description = "Instance count per environment — evidence that dev creates nothing and non-production stays small."
  value = {
    for env in var.environments : env => length([
      for k, i in local.primary_instances : k if i.env == env
    ])
  }
}

output "instances_by_priority" {
  description = "How much of the estate can page. P1+P2 should be a small minority."
  value = {
    for p in ["P1", "P2", "P3", "P4"] : p => length([
      for k, i in merge(local.primary_instances, local.burn_instances) : k if i.priority == p
    ])
  }
}

output "paging_monitors" {
  description = "Every monitor permitted to wake a human, with its owner. Reviewed quarterly."
  value = {
    for k, i in merge(local.primary_instances, local.burn_instances) :
    k => "${i.priority} → ${i.team}" if i.pages
  }
}

output "demoted_by_composite" {
  description = "Member monitors demoted to informational because a composite carries their page."
  value       = tolist(local.demoted_instance_keys)
}

output "contract_report" {
  description = "Machine-readable monitor-contract evidence consumed by tools/coverage_report.py and tools/monitor_scorecard.py."
  value = merge(
    module.coverage_monitors.contract_report,
    module.burn_monitors.contract_report,
    module.composites.contract_report,
  )
}
