variable "slos" {
  description = <<-EOT
    SLO catalog entries to CREATE (entries with an existing datadog_id are
    adopted, not recreated — pass them in `adopted_slos` instead). Metric and
    monitor types are supported; monitor member IDs come from the monitor
    factory's archetype output.
  EOT
  type = map(object({
    name        = string
    type        = string # metric | monitor
    description = optional(string, "")
    domain      = string
    service     = string
    team        = string
    target      = number
    timeframe   = string # 7d | 30d | 90d
    warning     = optional(number)
    query = optional(object({
      numerator   = string
      denominator = string
    }))
    monitor_ids = optional(list(number), [])
    tags        = optional(list(string), [])
  }))

  validation {
    condition     = alltrue([for k, s in var.slos : contains(["metric", "monitor"], s.type)])
    error_message = "slo type must be metric or monitor (time_slice SLOs are adopted from the org, not created here)."
  }
  validation {
    condition     = alltrue([for k, s in var.slos : s.type != "metric" || s.query != null])
    error_message = "metric SLOs require a query {numerator, denominator}."
  }
}

variable "adopted_slos" {
  description = "slo_id → existing Datadog SLO ID for SLOs that already exist in the org."
  type        = map(string)
  default     = {}
}

variable "managed_by" {
  type    = string
  default = "terraform"
}
