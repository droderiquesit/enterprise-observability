output "team_ids" {
  value = { for k, t in datadog_team.this : k => t.id }
}

output "schedule_ids" {
  value = { for k, s in datadog_on_call_schedule.this : k => s.id }
}

output "escalation_policy_ids" {
  value = { for k, p in datadog_on_call_escalation_policy.this : k => p.id }
}
