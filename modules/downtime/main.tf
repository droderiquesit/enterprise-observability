resource "datadog_downtime_schedule" "this" {
  for_each = var.windows

  scope = each.value.scope
  message = trimspace(<<-EOT
    ${each.value.message}
    ${each.value.change_ticket != "" ? "Change ticket: ${each.value.change_ticket}" : ""}
    (managed_by:terraform downtime_id:${each.key})
  EOT
  )

  monitor_identifier {
    monitor_tags = each.value.monitor_tags
  }

  recurring_schedule {
    recurrence {
      rrule    = each.value.rrule
      start    = each.value.start
      duration = each.value.duration
    }
    timezone = each.value.timezone
  }

  # The API requires the display timezone to equal the recurrence timezone
  # ("timezone must match display_timezone" — found by the first live apply;
  # display_timezone otherwise defaults to UTC).
  display_timezone = each.value.timezone

  notify_end_states = ["alert", "warn"]
  notify_end_types  = ["canceled", "expired"]
}
