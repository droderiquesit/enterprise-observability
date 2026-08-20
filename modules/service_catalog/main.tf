# Service Definition (schema v2.2) per service — the authoritative ownership
# record inside Datadog, generated from inventory, never hand-edited.
#
# THIS MODULE ONLY EMITS SERVICES, because v2.2 has no other shape. That is the
# §5 defect: a database or a queue arriving through discovery lands here as a
# "service". Declared entities go to modules/catalog_entity instead, which
# emits v3 entities of the correct kind; the calling stack passes each name to
# exactly one of the two modules, since a v2.2 definition and a v3 entity with
# the same name are the SAME Datadog catalog object and would otherwise be
# rewritten by both on every apply.
#
# What is left here is the DISCOVERED population (generated/services.auto.
# tfvars.json), which has no declared kind to trust. Typing it is §7's
# reconciliation work, not this module's.
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
