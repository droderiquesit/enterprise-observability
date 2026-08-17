variable "roles" {
  description = <<-EOT
    Least-privilege role model (ADR-009). Permission names are resolved against
    the live org via the datadog_permissions data source at plan time, so an
    unknown permission fails the plan instead of silently granting nothing.
  EOT
  type = map(object({
    name        = string
    permissions = list(string) # datadog permission names, e.g. "monitors_write"
  }))
}

variable "service_accounts" {
  description = "Automation identities — strictly separate from human roles."
  type = map(object({
    email = string
    name  = string
    roles = list(string) # keys into var.roles
  }))
  default = {}
}
