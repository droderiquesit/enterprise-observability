output "entity_ids" {
  description = "entity name → Datadog catalog entity ID."
  value       = { for name, r in datadog_software_catalog.this : name => r.id }
}

output "entity_yaml" {
  description = <<-EOT
    entity name → the rendered v3 document. Exposed so the offline plan and the
    tests can read exactly what would be sent to Datadog without an apply —
    the entity-kind census §5 asks for is this map grouped by `kind`.
  EOT
  value       = local.entity_yaml
}

output "not_emitted" {
  description = <<-EOT
    Entities that deliberately produce no Datadog object (a `repository`, or
    anything whose archetype is infrastructure_resource). Listed rather than
    dropped silently: "nothing was created" must be a visible decision, not an
    apparent omission.
  EOT
  value       = sort([for name, e in var.entities : name if !e.emits])
}
