output "role_ids" {
  value = { for k, r in datadog_role.this : k => r.id }
}

output "service_account_ids" {
  value = { for k, s in datadog_service_account.this : k => s.id }
}
