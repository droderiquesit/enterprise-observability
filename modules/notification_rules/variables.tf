variable "teams" {
  description = "Team routing config: handle → destinations."
  type = map(object({
    teams_channel = string # Microsoft Teams integration handle (without @)
  }))
}

variable "severities" {
  description = "Severity model: sevN → routing behavior (from routing.yaml)."
  type = map(object({
    pages       = bool
    snow_handle = string # ServiceNow integration handle (without @), "" = none
  }))
}

variable "exec_channel" {
  description = "Executive-visibility Teams handle for sev1 (without @)."
  type        = string
  default     = ""
}

variable "managed_by" {
  type    = string
  default = "terraform"
}
