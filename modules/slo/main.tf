locals {
  # Warning threshold: 30% of the remaining error budget, ahead of the target.
  #
  # Datadog rejects a monitor-based SLO whose warning carries more than TWO
  # decimal digits on a 30d timeframe ("Warning for 30d timeframe supports a
  # max of 2 decimal digits" — a live apply failed on 99.95 → 99.965). Round
  # UP to 2 decimals so the warning stays strictly ahead of the target, then
  # cap at 99.99.
  #
  # A target of 99.99 or tighter leaves no room for a distinguishable warning
  # after capping, so the warning is omitted (null) rather than emitted equal
  # to the target, which the API also rejects. No current target hits this,
  # but a future tightening must not break the production apply.
  slo_warning = {
    for k, s in var.slos : k => (
      s.warning != null
      ? s.warning
      : (
        min(ceil((s.target + (100 - s.target) * 0.3) * 100) / 100, 99.99) > s.target
        ? min(ceil((s.target + (100 - s.target) * 0.3) * 100) / 100, 99.99)
        : null
      )
    )
  }
}

resource "datadog_service_level_objective" "this" {
  for_each = var.slos

  name = each.value.name
  type = each.value.type
  # The " Owner: … Managed by Terraform (slo_id:…)" provenance suffix is owned
  # HERE and must not be repeated by callers — it was, and every deployed SLO
  # description carried it twice.
  description = "${each.value.description} Owner: ${each.value.team}. Managed by Terraform (slo_id:${each.key})."

  thresholds {
    timeframe = each.value.timeframe
    target    = each.value.target
    warning   = local.slo_warning[each.key]
  }

  dynamic "query" {
    for_each = each.value.type == "metric" ? [each.value.query] : []
    content {
      numerator   = query.value.numerator
      denominator = query.value.denominator
    }
  }

  monitor_ids = each.value.type == "monitor" ? each.value.monitor_ids : null

  tags = concat([
    "slo_id:${each.key}",
    "env:prod",
    "service:${each.value.service}",
    "team:${each.value.team}",
    "owner:${each.value.team}",
    "domain:${each.value.domain}",
    "managed_by:terraform",
    "monitor_type:slo",
  ], each.value.tags)
}

locals {
  # slo_id → Datadog SLO ID, for burn-rate monitor queries.
  slo_datadog_ids = { for k, s in datadog_service_level_objective.this : k => s.id }
}
