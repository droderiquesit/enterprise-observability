variable "windows" {
  description = "Recurring maintenance windows. Scope is tag-based; monitors are matched by tags, never by ID."
  type = map(object({
    scope         = string # e.g. "env:prod AND team:data-engineering"
    monitor_tags  = optional(list(string), ["managed_by:terraform"])
    rrule         = string # e.g. "FREQ=WEEKLY;INTERVAL=1;BYDAY=SU"
    start         = string # local wall time, e.g. "2026-09-07T02:00:00"
    duration      = string # e.g. "4h"
    timezone      = optional(string, "America/New_York")
    message       = string
    change_ticket = optional(string, "") # required for regulated scopes (validated in CI)
  }))
}
