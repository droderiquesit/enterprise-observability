variable "teams" {
  description = <<-EOT
    Teams with on-call configuration.

    `members` / `secondary_members` are Datadog user IDs for the primary and
    secondary rotations, fed from the org's SCIM/IdP sync. BOTH default to an
    empty list and an empty list is a fully supported steady state: the whole
    on-call structure (schedules, layers, escalation policy, routing rules) is
    still created, with the schedule layer holding an UNASSIGNED position
    rather than an invented user. Rosters drop in later with no structural
    change — see the "unassigned position" comment in main.tf.
  EOT
  type = map(object({
    name                       = string
    description                = string
    members                    = optional(list(string), [])
    secondary_members          = optional(list(string), [])
    time_zone                  = optional(string, "America/New_York")
    rotation_days              = optional(number, 7)
    ack_timeout_minutes        = optional(number, 10)
    escalation_timeout_minutes = optional(number, 20)
    business_hours_only        = optional(bool, false)
  }))
}

variable "schedule_effective_date" {
  description = "Fixed anchor for rotation start (stable across plans; never use timestamp()). The value lives in stacks/foundation/variables.tf — declared required here so there is exactly one source."
  type        = string
}

# -----------------------------------------------------------------------------
# ESCALATION LADDER
#
# Four steps, cumulative wall-clock from the moment the page is raised:
#
#   t+0m   step 1  primary on-call schedule
#   t+10m  step 2  secondary on-call schedule
#   t+20m  step 3  the team itself (team lead / whole rotation)
#   t+30m  step 4  incident commander / platform leadership
#
# Each variable is the DWELL time of its own step, not the cumulative offset,
# because that is what the Datadog API models (`escalate_after_seconds` = how
# long to wait on THIS step before moving on). The Datadog provider constrains
# escalate_after_seconds to 60..36000, i.e. 1..600 minutes.
# -----------------------------------------------------------------------------
variable "step1_after_minutes" {
  description = "Minutes the PRIMARY on-call has to acknowledge before the page escalates to the secondary. Default 10 → secondary is paged at t+10m."
  type        = number
  default     = 10

  validation {
    condition     = var.step1_after_minutes >= 1 && var.step1_after_minutes <= 600
    error_message = "step1_after_minutes must be between 1 and 600 (Datadog allows escalate_after_seconds 60..36000)."
  }
}

variable "step2_after_minutes" {
  description = "Minutes the SECONDARY on-call has before the page escalates to the team lead. Default 10 → team lead is paged at t+20m cumulative."
  type        = number
  default     = 10

  validation {
    condition     = var.step2_after_minutes >= 1 && var.step2_after_minutes <= 600
    error_message = "step2_after_minutes must be between 1 and 600 (Datadog allows escalate_after_seconds 60..36000)."
  }
}

variable "step3_after_minutes" {
  description = "Minutes the TEAM has before the page escalates to the incident commander / platform leadership. Default 10 → leadership is paged at t+30m cumulative."
  type        = number
  default     = 10

  validation {
    condition     = var.step3_after_minutes >= 1 && var.step3_after_minutes <= 600
    error_message = "step3_after_minutes must be between 1 and 600 (Datadog allows escalate_after_seconds 60..36000)."
  }
}

variable "step4_after_minutes" {
  description = "Minutes leadership holds the page on the FINAL step before the policy ends (retries then apply; resolve_page_on_policy_end is false, so the page is never auto-resolved). Default 10."
  type        = number
  default     = 10

  validation {
    condition     = var.step4_after_minutes >= 1 && var.step4_after_minutes <= 600
    error_message = "step4_after_minutes must be between 1 and 600 (Datadog allows escalate_after_seconds 60..36000)."
  }
}

variable "leadership_team_id" {
  description = <<-EOT
    Datadog Team ID of the incident-commander / platform-leadership team that
    owns escalation step 4. May be "" (the default): with no leadership team
    provisioned yet, step 4 falls back to the owning team so the ladder still
    has four valid steps and no page can fall off the end of the policy.
  EOT
  type        = string
  default     = ""
}

variable "create_schedules" {
  description = <<-EOT
    Create the primary/secondary On-Call schedules. Leave true.

    This is an escape hatch for one specific failure mode: Datadog requires a
    schedule layer to carry at least one member slot, and this module fills an
    empty roster with a single UNASSIGNED position (`users = [null]`). If a
    given org/plan rejects unassigned positions outright, set this to false —
    teams, escalation policies and routing rules are still created in full, and
    every escalation step targets the TEAM instead of a schedule, so paging
    keeps working while rosters are sorted out.
  EOT
  type        = bool
  default     = true
}
