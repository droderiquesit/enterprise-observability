output "slo_datadog_ids" {
  description = "slo_id → Datadog SLO ID (created and adopted)."
  value       = local.slo_datadog_ids
}

output "created_slo_ids" {
  value = { for k, s in datadog_service_level_objective.this : k => s.id }
}
