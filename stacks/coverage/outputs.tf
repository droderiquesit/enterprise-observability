output "monitor_count" {
  value = length(local.archetype_instances) + length(local.request_instances) + length(local.burn_instances)
}

output "monitor_ids" {
  value = merge(module.coverage_monitors.monitor_ids, module.burn_monitors.monitor_ids)
}

output "slo_ids" {
  value = module.slos.slo_datadog_ids
}

output "suppressed_signals" {
  description = "Signals demoted to informational by approved exceptions — intentionally not alerting; surfaced in the coverage report."
  value       = { for k, r in local.suppressed_instances : k => "exception-driven informational (see exceptions.yaml)" }
}

output "contract_report" {
  description = "Machine-readable monitor-contract evidence for tools/coverage_report.py."
  value = merge(
    module.coverage_monitors.contract_report,
    module.burn_monitors.contract_report,
  )
}
