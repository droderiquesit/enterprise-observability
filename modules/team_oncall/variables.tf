variable "teams" {
  description = <<-EOT
    Teams with on-call configuration. `members` are Datadog user IDs for the
    rotation (fed from the org's SCIM/IdP sync; empty list = team created but
    schedule creation deferred until members exist, so a fresh org bootstraps
    cleanly).
  EOT
  type = map(object({
    name                       = string
    description                = string
    members                    = optional(list(string), [])
    time_zone                  = optional(string, "America/New_York")
    rotation_days              = optional(number, 7)
    handoff_time               = optional(string, "09:00:00")
    ack_timeout_minutes        = optional(number, 10)
    escalation_timeout_minutes = optional(number, 20)
    business_hours_only        = optional(bool, false)
  }))
}

variable "schedule_effective_date" {
  description = "Fixed anchor for rotation start (stable across plans; never use timestamp())."
  type        = string
  default     = "2026-09-01T09:00:00-05:00"
}

variable "managed_by" {
  type    = string
  default = "terraform"
}
