variable "datadog_api_url" {
  type    = string
  default = "https://api.datadoghq.com/"
}

variable "datadog_validate" {
  description = "Set false for offline CI stages (fmt/validate/plan without credentials) so the provider skips its API credential check."
  type        = bool
  default     = true
}

variable "oncall_members" {
  description = <<-EOT
    team handle → Datadog user IDs for the on-call rotation. Fed from the
    IdP/SCIM sync job, never hand-edited and never committed. An empty map is a
    valid bootstrap state: teams and routing rules are created, and schedules
    appear the moment rosters exist.
  EOT
  type        = map(list(string))
  default     = {}
}

variable "rotation_days" {
  description = "Length of the primary on-call rotation in days."
  type        = number
  default     = 7
}

variable "schedule_effective_date" {
  description = "Fixed anchor for rotation start. Never derived from timestamp() — a plan must not change because a day passed."
  type        = string
  default     = "2026-09-01T09:00:00-05:00"
}

variable "workflow_budget" {
  description = <<-EOT
    Maximum Workflow Automation workflows to instantiate, selected in the
    explicit priority order in main.tf. 0 = no budget (all). Exists because
    the org's Datadog plan caps total workflows; raise or zero this when the
    plan allows the full catalog.
  EOT
  type        = number
  default     = 0

  validation {
    condition     = var.workflow_budget >= 0
    error_message = "workflow_budget must be >= 0 (0 = unlimited)."
  }
}

variable "manage_rbac" {
  description = "Manage roles and service accounts. Requires user_access_manage; disable for offline plans because permission names are resolved against the live API."
  type        = bool
  default     = true
}

variable "services" {
  description = <<-EOT
    Additional service catalog entries discovered by the inventory pipeline
    (generated/services.auto.tfvars.json). These MERGE with the registered
    services in platform/services/ — discovery covers everything, registration
    adds ownership intent.
  EOT
  type = map(object({
    team               = string
    owner_email        = string
    description        = optional(string, "")
    tier               = string
    domain             = string
    monitoring_profile = string
    env                = optional(string, "prod")
    links              = optional(list(object({ name = string, type = string, url = string })), [])
  }))
  default = {}
}
