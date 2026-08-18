variable "teams" {
  description = "team handle → channel names (platform/policy/teams.yaml)."
  type = map(object({
    channel           = string
    low_noise_channel = string
  }))
}

variable "routes" {
  description = <<-EOT
    Flattened routing rows keyed "<notification_profile>.<priority>", built in
    stacks/foundation from platform/policy/notification_profiles.yaml. Each row
    describes WHAT happens; this module multiplies it by the team list to
    produce the concrete destinations.
  EOT
  type = map(object({
    profile               = string
    priority              = string
    teams                 = list(string)
    pages                 = bool
    page                  = bool
    servicenow_handle     = string
    channel_suffix        = string
    use_low_noise_channel = bool
    cc_owner_team         = bool
    extra_channels        = list(string)
  }))

  validation {
    condition     = alltrue([for k, r in var.routes : contains(["P1", "P2", "P3", "P4"], r.priority)])
    error_message = "Every routing row must target P1, P2, P3 or P4."
  }
}

