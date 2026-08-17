variable "workflows" {
  description = <<-EOT
    Workflow Automation definitions. `spec_file` points at a versioned JSON
    spec under platform/workflows/. Workflows begin with read-only diagnostics;
    any remediation step must set `approval` (owner|change-board) which is
    enforced as an approval gate inside the spec and recorded as a tag.
  EOT
  type = map(object({
    name        = string
    description = string
    kind        = string # enrichment | remediation | ticket | incident
    team        = string
    approval    = string # none | owner | change-board
    read_only   = bool
    spec_json   = string
    published   = optional(bool, true)
  }))

  validation {
    condition     = alltrue([for k, w in var.workflows : contains(["enrichment", "remediation", "ticket", "incident"], w.kind)])
    error_message = "kind must be enrichment, remediation, ticket, or incident."
  }
  validation {
    # Guardrail: anything that can mutate production requires an approval gate.
    condition     = alltrue([for k, w in var.workflows : w.read_only || w.approval != "none"])
    error_message = "Non-read-only workflows must declare approval: owner or change-board (ADR-008)."
  }
}

variable "managed_by" {
  type    = string
  default = "terraform"
}
