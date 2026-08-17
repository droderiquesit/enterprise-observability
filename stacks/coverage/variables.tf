variable "datadog_api_url" {
  type    = string
  default = "https://api.datadoghq.com/"
}

variable "datadog_validate" {
  description = "Validate credentials on provider configure. false enables offline plan/validate in CI stages without secrets."
  type        = bool
  default     = true
}

variable "adopt_existing_slos" {
  description = "Enable import blocks that adopt the surviving org SLOs into state (migration step M3/M4). Disable only for offline CI plans."
  type        = bool
  default     = true
}

variable "environments" {
  description = "Environments to instantiate alerting coverage for."
  type        = list(string)
  default     = ["prod", "staging"]
}
