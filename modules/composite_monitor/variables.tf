variable "composites" {
  description = "Fully-resolved composite definitions. member_ids are Datadog monitor IDs produced by the monitor factory."
  type = map(object({
    title       = string
    description = string
    operator    = string # AND | OR

    member_ids      = list(string)
    member_titles   = list(string)
    member_group_by = list(string) # one joined string per member; must be identical
    member_teams    = list(string)

    domain             = string
    env                = string
    band               = string
    tier               = string
    priority           = string
    impact_class       = string
    monitoring_profile = string
    support_model      = string
    pages              = bool

    service              = string
    team                 = string
    cc_teams             = optional(list(string), [])
    notification_profile = string
    failure_domain       = string

    slo_id  = string
    runbook = string
    # Native runbook attachment — see modules/monitor_factory/variables.tf.
    runbook_notebook_id  = optional(string, "")
    runbook_notebook_url = optional(string, "")
    runbook_title        = optional(string, "")
    workflow             = string
    impact               = string
    next_action          = string

    renotify_interval = optional(number, 60)
    extra_tags        = optional(list(string), [])
  }))

  validation {
    condition     = alltrue([for k, c in var.composites : contains(["AND", "OR"], c.operator)])
    error_message = "operator must be AND or OR."
  }
  validation {
    condition     = alltrue([for k, c in var.composites : contains(["P1", "P2", "P3", "P4"], c.priority)])
    error_message = "priority must be one of P1..P4."
  }
}

variable "max_members" {
  description = "Maximum members per composite (platform/policy/composites.yaml → budget)."
  type        = number
  default     = 3
}


variable "api_validate" {
  type    = bool
  default = true
}

variable "defaults" {
  description = <<-EOT
    Org-wide monitor option defaults (platform/policy/global.yaml →
    monitor_defaults). Composites previously hardcoded a subset and let the
    rest fall to provider defaults, so a composite silently behaved differently
    from every other managed monitor. It now takes the same defaults object the
    monitor factory does.
  EOT
  type = object({
    renotify_statuses    = list(string)
    renotify_occurrences = number
    require_full_window  = bool
    notify_audit         = bool
    include_tags         = bool
    timeout_h            = number
  })
}
