resource "datadog_workflow_automation" "this" {
  for_each = var.workflows

  name        = each.value.name
  description = each.value.description
  published   = each.value.published
  spec_json   = each.value.spec_json

  tags = [
    "automation_ref:${each.key}",
    "automation_class:${each.value.kind}",
    "team:${each.value.team}",
    "approval:${each.value.approval}",
    "read_only:${each.value.read_only}",
    "reversible:${try(each.value.reversible, true)}",
    "rate_cap_per_hour:${try(each.value.max_actions_per_hour, 0)}",
    "managed_by:terraform",
  ]
}
