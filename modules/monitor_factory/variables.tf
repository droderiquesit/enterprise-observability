variable "instances" {
  description = <<-EOT
    Map of fully-resolved monitor instances (key = stable monitor id, e.g.
    "prod.application.app-latency-degradation"). Each instance is the result of
    the policy hierarchy merge performed in the calling stack. The factory
    enforces the monitor contract and cardinality guardrails on every instance.
  EOT
  type = map(object({
    archetype          = string
    title              = string
    domain             = string
    env                = string
    monitor_type       = string # query alert | service check | event-v2 alert | log alert | slo alert
    query              = string
    thresholds         = map(number)
    group_by           = list(string)
    severity           = string # sev1 | sev2 | sev3 | informational
    priority           = number # 1..5
    team               = string
    owner              = string
    service            = string
    slo_id             = string
    slo_url            = optional(string, "")
    runbook_name       = string
    runbook_url        = optional(string, "")
    workflow           = string
    failure_domain     = string
    criticality        = string
    monitoring_profile = string
    platform           = string
    resource_type      = string
    region             = optional(string, "global")
    routing_rule       = string
    snow_record        = string
    support_model      = string
    pages              = bool
    summary            = optional(string, "")
    impact             = optional(string, "")

    notify_no_data      = optional(bool)
    no_data_timeframe   = optional(number)
    evaluation_delay    = optional(number)
    new_group_delay     = optional(number)
    renotify_interval   = optional(number)
    require_full_window = optional(bool)
    timeout_h           = optional(number)

    dedup_suffix   = optional(string, "")
    extra_tags     = optional(list(string), [])
    managed_source = optional(string, "platform") # platform | self_service
    request_id     = optional(string, "")
  }))

  validation {
    condition = alltrue([
      for k, m in var.instances :
      contains(["sev1", "sev2", "sev3", "informational"], m.severity)
    ])
    error_message = "severity must be one of sev1, sev2, sev3, informational."
  }
  validation {
    condition = alltrue([
      for k, m in var.instances :
      contains(["query alert", "metric alert", "service check", "event-v2 alert", "log alert", "slo alert"], m.monitor_type)
    ])
    error_message = "monitor_type must be a supported Datadog monitor type."
  }
  validation {
    condition = alltrue([
      for k, m in var.instances : m.slo_id != "" && m.runbook_name != "" && m.workflow != "" && m.team != ""
    ])
    error_message = "Monitor contract violation: slo_id, runbook_name, workflow, and team are mandatory on every instance."
  }
}

variable "defaults" {
  description = "Org-wide monitor option defaults (from platform/policy/global.yaml monitor_defaults)."
  type = object({
    evaluation_delay  = number
    new_group_delay   = number
    renotify_interval = number
    renotify_statuses = list(string)
    notify_no_data    = bool
    no_data_timeframe = number

    require_full_window = bool
    notify_audit        = bool
    include_tags        = bool
    timeout_h           = number
  })
}

variable "cardinality" {
  description = "Cardinality guardrails (from global.yaml). Instances exceeding them fail at plan time."
  type = object({
    max_group_by_keys    = number
    forbidden_group_keys = list(string)
  })
}

variable "managed_by" {
  type    = string
  default = "terraform"
}

variable "api_validate" {
  description = "Validate each monitor against the Datadog /monitor/validate API at plan time. Disable only for offline CI plans without credentials."
  type        = bool
  default     = true
}

variable "restricted_roles" {
  description = "Role IDs allowed to edit these monitors in-app (normally none: Terraform-only)."
  type        = list(string)
  default     = null
}
