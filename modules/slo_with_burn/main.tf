resource "datadog_service_level_objective" "this" {
  for_each = var.slos

  name        = each.value.name
  type        = each.value.type
  description = "${each.value.description} Owner: ${each.value.team}. Managed by Terraform (slo_id:${each.key})."

  thresholds {
    timeframe = each.value.timeframe
    target    = each.value.target
    warning   = each.value.warning != null ? each.value.warning : min(each.value.target + (100 - each.value.target) * 0.3, 99.99)
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
    "managed_by:${var.managed_by}",
    "monitor_type:slo",
  ], each.value.tags)
}

locals {
  # slo_id → Datadog SLO ID for burn-rate monitors: created ∪ adopted.
  slo_datadog_ids = merge(
    var.adopted_slos,
    { for k, s in datadog_service_level_objective.this : k => s.id }
  )
}
