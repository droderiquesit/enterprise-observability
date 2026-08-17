variable "datadog_api_url" {
  type    = string
  default = "https://api.datadoghq.com/"
}

variable "datadog_validate" {
  type    = bool
  default = true
}

variable "oncall_members" {
  description = "team handle → Datadog user IDs for the on-call rotation (from IdP sync; kept out of VCS)."
  type        = map(list(string))
  default     = {}
}

variable "manage_rbac" {
  description = "Manage roles/service accounts (requires user_access_manage; disable for offline plans since permission resolution needs the API)."
  type        = bool
  default     = true
}

variable "adopt_existing_workflows" {
  description = "Import the 18 surviving org workflows into state (migration step M5). Disable for offline CI plans."
  type        = bool
  default     = false
}

variable "services" {
  description = "Service catalog entries (generated/services.auto.tfvars.json from the inventory pipeline)."
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
