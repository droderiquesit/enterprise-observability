# Service Definition (schema v2.2) per service — the authoritative ownership
# record inside Datadog, generated from inventory, never hand-edited.
resource "datadog_service_definition_yaml" "this" {
  for_each = var.services

  service_definition = yamlencode({
    schema-version = "v2.2"
    dd-service     = each.key
    team           = each.value.team
    description    = each.value.description
    tier           = each.value.tier
    lifecycle      = "production"
    contacts = [{
      name    = "${each.value.team} email"
      type    = "email"
      contact = each.value.owner_email
    }]
    tags = [
      "domain:${each.value.domain}",
      "criticality:${each.value.tier}",
      "monitoring_profile:${each.value.monitoring_profile}",
      "env:${each.value.env}",
      "managed_by:terraform",
    ]
    links = [for l in each.value.links : { name = l.name, type = l.type, url = l.url }]
  })
}
