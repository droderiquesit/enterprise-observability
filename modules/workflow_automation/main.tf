resource "datadog_workflow_automation" "this" {
  for_each = var.workflows

  name        = each.value.name
  description = each.value.description
  published   = each.value.published
  spec_json   = each.value.spec_json

  tags = [
    "automation_ref:${each.key}",
    "kind:${each.value.kind}",
    "team:${each.value.team}",
    "approval:${each.value.approval}",
    "read_only:${each.value.read_only}",
    "managed_by:${var.managed_by}",
    "attaches_to:automation:${each.key}",
  ]
}
