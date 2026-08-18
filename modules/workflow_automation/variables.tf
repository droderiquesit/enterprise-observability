variable "workflows" {
  description = <<-EOT
    Workflow Automation definitions, classified by BLAST RADIUS rather than by
    what they happen to do:

      diagnostic_only    read-only enrichment; runs on every alert
      fully_automatic    mutates production, but bounded, reversible and rate-capped
      approval_required  mutates production and waits for a human decision
      manual             documented in the runbook; no automation exists yet

    The validations below are the safety contract from ADR-008. They are the
    reason an automation cannot quietly become dangerous through an edit.
  EOT
  type = map(object({
    name                 = string
    description          = string
    kind                 = string # the automation class
    team                 = string
    approval             = string # none | owner | change-board
    read_only            = bool
    reversible           = optional(bool, true)
    max_actions_per_hour = optional(number, 0)
    spec_json            = string
    published            = optional(bool, true)
  }))

  validation {
    condition = alltrue([
      for k, w in var.workflows :
      contains(["diagnostic_only", "fully_automatic", "approval_required", "manual"], w.kind)
    ])
    error_message = "kind must be one of diagnostic_only, fully_automatic, approval_required, manual."
  }

  validation {
    condition     = alltrue([for k, w in var.workflows : w.kind != "diagnostic_only" || w.read_only])
    error_message = "A diagnostic_only workflow must be read_only. If it changes anything, it is not diagnostic."
  }

  validation {
    condition = alltrue([
      for k, w in var.workflows :
      w.read_only || contains(["fully_automatic", "approval_required"], w.kind)
    ])
    error_message = "A workflow that mutates production must be classified fully_automatic or approval_required."
  }

  validation {
    # The core ADR-008 guardrail: unattended production change requires a
    # bounded, reversible, rate-capped blast radius.
    condition = alltrue([
      for k, w in var.workflows :
      w.kind != "fully_automatic" || (try(w.reversible, false) && try(w.max_actions_per_hour, 0) > 0)
    ])
    error_message = "fully_automatic workflows must declare reversible: true and max_actions_per_hour > 0. Unbounded unattended change is not permitted."
  }

  validation {
    condition = alltrue([
      for k, w in var.workflows :
      w.kind != "approval_required" || contains(["owner", "change-board"], w.approval)
    ])
    error_message = "approval_required workflows must declare approval: owner or change-board."
  }

  validation {
    # Irreversible actions can never be owner-approved alone.
    condition = alltrue([
      for k, w in var.workflows :
      try(w.reversible, true) || w.approval == "change-board"
    ])
    error_message = "An irreversible workflow (reversible: false) requires change-board approval. Owner approval is not sufficient for an action that cannot be undone."
  }
}

