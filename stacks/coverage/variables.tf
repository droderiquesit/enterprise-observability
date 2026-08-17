variable "datadog_api_url" {
  type    = string
  default = "https://api.datadoghq.com/"
}

variable "datadog_validate" {
  description = "Validate credentials and every monitor definition against the Datadog API at plan time. false enables offline CI stages without secrets."
  type        = bool
  default     = true
}

variable "environments" {
  description = <<-EOT
    Environments to instantiate. The SAME definitions are used for all of them;
    platform/policy/environments.yaml decides how loud each one is. `dev` is
    accepted here but produces no monitors — its policy sets alerting: false.

    Promotion is done by narrowing this list, not by copying definitions:
      stage rollout  →  ["stage"]
      full           →  ["qa", "stage", "prod"]

    Under per-environment state files (ADR-016) the deploy workflow applies
    exactly ONE environment per state file. Environment-agnostic objects —
    SLOs and their burn-rate monitors — are owned by the apply whose list
    contains "prod", so they exist exactly once.
  EOT
  type        = list(string)
  default     = ["qa", "stage", "prod"]

  validation {
    condition     = alltrue([for e in var.environments : contains(["dev", "qa", "stage", "prod"], e)])
    error_message = "environments must be a subset of dev, qa, stage, prod."
  }
}
