# Centrally-managed tag-based routing (ADR-005): one notification rule per
# (team × severity). Monitors carry only tags; changing a destination is a
# one-line change here, touching zero monitors.

locals {
  pairs = merge([
    for t, tc in var.teams : {
      for s, sc in var.severities : "${t}.${s}" => {
        team     = t
        severity = s
        recipients = compact(concat(
          [tc.teams_channel],
          sc.snow_handle != "" ? [sc.snow_handle] : [],
          s == "sev1" && var.exec_channel != "" ? [var.exec_channel] : [],
        ))
      }
    }
  ]...)
}

resource "datadog_monitor_notification_rule" "this" {
  for_each = local.pairs

  name       = "route-${each.value.team}-${each.value.severity}"
  recipients = each.value.recipients

  filter {
    tags = [
      "managed_by:${var.managed_by}",
      "team:${each.value.team}",
      "severity:${each.value.severity}",
    ]
  }
}
