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

variable "oncall_secondary_members" {
  description = <<-EOT
    team handle → Datadog user IDs for the SECONDARY on-call rotation (the
    backstop paged at escalation step 2, ten minutes after an unacknowledged
    primary page). Same contract as oncall_members: fed from the IdP/SCIM sync,
    never hand-edited, never committed. An empty map is a valid steady state —
    the secondary schedule is still created and holds an unassigned position,
    so the escalation ladder is complete and reviewable before rosters exist.
  EOT
  type        = map(list(string))
  default     = {}
}

variable "create_oncall_schedules" {
  description = <<-EOT
    Create the primary/secondary On-Call schedules. Leave true.

    Escape hatch for one specific risk: Datadog requires every schedule layer
    to carry at least one member slot, and an empty roster is expressed as a
    single UNASSIGNED position (`users = [null]`). If the org rejects
    unassigned positions, set this false — teams, escalation policies and
    routing rules are still created in full and every escalation step targets
    the team instead of a schedule, so paging keeps working.
  EOT
  type        = bool
  default     = true
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
