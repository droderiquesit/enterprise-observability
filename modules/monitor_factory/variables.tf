variable "instances" {
  description = <<-EOT
    Map of fully-resolved monitor instances. The key is the stable monitor id
    (e.g. "prod.critical.api.api-availability") and becomes the `monitor_id`
    tag. Every value is the OUTPUT of the policy hierarchy merge performed in
    the calling stack — the factory itself makes no policy decisions, it only
    enforces the contract and renders Datadog resources.
  EOT
  type = map(object({
    # identity
    archetype = string
    title     = string
    domain    = string
    env       = string
    band      = string
    signal    = string

    # detection
    monitor_type     = string # query alert | metric alert | service check | event-v2 alert | log alert | composite
    detection        = string
    query            = string
    thresholds       = map(number)
    group_by         = list(string)
    notify_by        = optional(list(string), [])
    evaluation_delay = optional(number)
    new_group_delay  = optional(number)

    # classification & response
    impact_class       = string # customer_impact | degradation | risk | hygiene
    priority           = string # P1..P4
    tier               = string
    monitoring_profile = string
    pages              = bool
    support_model      = string
    slo_impacting      = optional(bool, true)

    # ownership & routing
    team                 = string
    owner                = string
    service              = string
    resource_type        = string
    region               = optional(string, "")
    notification_profile = string
    failure_domain       = string

    # contract
    slo_id      = string
    slo_url     = optional(string, "")
    runbook     = string
    runbook_url = optional(string, "")
    workflow    = string
    summary     = string
    impact      = string
    why         = string
    next_action = string

    # behavior overrides
    notify_no_data      = optional(bool)
    no_data_timeframe   = optional(number)
    renotify_interval   = optional(number)
    require_full_window = optional(bool)
    timeout_h           = optional(number)

    # metadata
    compliance       = optional(bool, false)
    compliance_scope = optional(string, "sox")
    dedup_suffix     = optional(string, "")
    extra_tags       = optional(list(string), [])
    managed_source   = optional(string, "platform") # platform | self_service | composite
    request_id       = optional(string, "")
  }))

  validation {
    condition = alltrue([
      for k, m in var.instances : contains(["P1", "P2", "P3", "P4"], m.priority)
    ])
    error_message = "priority must be one of P1, P2, P3, P4."
  }
  validation {
    condition = alltrue([
      for k, m in var.instances :
      contains(["customer_impact", "degradation", "risk", "hygiene"], m.impact_class)
    ])
    error_message = "impact_class must be one of customer_impact, degradation, risk, hygiene."
  }
  validation {
    condition = alltrue([
      for k, m in var.instances :
      contains(["query alert", "metric alert", "service check", "event-v2 alert", "log alert", "slo alert", "composite"], m.monitor_type)
    ])
    error_message = "monitor_type must be a supported Datadog monitor type."
  }
  validation {
    condition = alltrue([
      for k, m in var.instances : contains(["dev", "qa", "stage", "prod"], m.env)
    ])
    error_message = "env must be one of dev, qa, stage, prod."
  }
  validation {
    condition = alltrue([
      for k, m in var.instances : contains(["baseline", "standard", "critical"], m.band)
    ])
    error_message = "alert_band must be one of baseline, standard, critical. Band 'none' never produces a monitor."
  }
  validation {
    condition = alltrue([
      for k, m in var.instances : m.env != "dev"
    ])
    error_message = "Environment policy: dev never instantiates alerting monitors. Fix the calling stack, not this validation."
  }
  validation {
    condition = alltrue([
      for k, m in var.instances :
      m.slo_id != "" && m.runbook != "" && m.workflow != "" && m.team != ""
    ])
    error_message = "Monitor contract: slo_id, runbook, workflow and team are mandatory on every instance."
  }
}

variable "defaults" {
  description = "Org-wide monitor option defaults (platform/policy/global.yaml → monitor_defaults)."
  type = object({
    evaluation_delay     = number
    new_group_delay      = number
    renotify_interval    = number
    renotify_statuses    = list(string)
    renotify_occurrences = number
    notify_no_data       = bool
    no_data_timeframe    = number
    require_full_window  = bool
    notify_audit         = bool
    include_tags         = bool
    timeout_h            = number
  })
}

variable "cardinality" {
  description = "Cardinality guardrails (global.yaml → cardinality). Violations fail at plan time."
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
  description = "Validate every monitor against the Datadog monitor-validation API at plan time. Disable only for offline CI plans without credentials."
  type        = bool
  default     = true
}

variable "restricted_roles" {
  description = "Role IDs permitted to edit these monitors in-app. Normally null: Terraform is the only writer."
  type        = list(string)
  default     = null
}
