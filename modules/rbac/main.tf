data "datadog_permissions" "all" {}

resource "datadog_role" "this" {
  for_each = var.roles
  name     = each.value.name

  dynamic "permission" {
    for_each = toset(each.value.permissions)
    content {
      id = data.datadog_permissions.all.permissions[permission.value]
    }
  }
}

resource "datadog_service_account" "this" {
  for_each = var.service_accounts
  email    = each.value.email
  name     = each.value.name
  roles    = [for r in each.value.roles : datadog_role.this[r].id]
}
