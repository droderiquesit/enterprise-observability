# ---------------------------------------------------------------------------
# SLO lifecycle: create missing platform SLOs, adopt survivors by ID, rebuild
# the membership of the monitor-type SLOs whose monitors were deleted (the
# broken SLOs found in the current-state assessment), and generate multi-window
# burn-rate monitors — the platform's PRIMARY paging signal.
# ---------------------------------------------------------------------------

locals {
  burn_windows = local.global.burn_rate_defaults

  # SLOs Terraform manages directly: metric SLOs without a datadog_id (new) and
  # monitor-type SLOs (adopted via import; their membership is rebuilt from the
  # archetype monitors created in this stack).
  slos_to_manage = {
    for id, s in local.slo_catalog : id => {
      name        = s.name
      type        = s.type
      description = try(s.description, "")
      domain      = s.domain
      service     = s.service
      team        = s.team
      target      = s.target
      timeframe   = s.timeframe
      warning     = null
      query       = try(s.query, null)
      monitor_ids = s.type == "monitor" ? flatten([
        for arch in try(s.member_archetypes, []) : [
          for k, mid in module.coverage_monitors.monitor_ids :
          tonumber(mid) if startswith(k, "prod.") && endswith(k, ".${arch}")
        ]
      ]) : []
      tags = ["criticality:tier2", "platform:${local.domains[s.domain].platform_tag}"]
    }
    if s.type == "monitor" || (s.type == "metric" && !can(s.datadog_id))
  }

  # Survivor SLOs referenced by ID only (metric/time_slice already correct).
  adopted_slo_ids = {
    for id, s in local.slo_catalog : id => s.datadog_id
    if can(s.datadog_id) && s.type != "monitor"
  }

  # Import map for adopted monitor-type SLOs (migration M3/M4).
  slo_import_map = var.adopt_existing_slos ? {
    for id, s in local.slo_catalog : id => s.datadog_id
    if can(s.datadog_id) && s.type == "monitor"
  } : {}

  # Burn-rate monitor instances: one per SLO per configured window pair.
  burn_instances = merge([
    for slo_id, s in local.slo_catalog : {
      for w in try(s.burn_alerts, []) :
      "prod.${s.domain}.slo-burn.${slo_id}.${w}" => {
        archetype          = "slo-burn"
        title              = "${s.name} — error budget burn (${w})"
        domain             = s.domain
        env                = "prod"
        monitor_type       = "slo alert"
        query              = "burn_rate(\"${module.slos.slo_datadog_ids[slo_id]}\").over(\"${s.timeframe}\").long_window(\"${local.burn_windows[w].long_window}\").short_window(\"${local.burn_windows[w].short_window}\") > ${local.burn_windows[w].factor}"
        thresholds         = { critical = local.burn_windows[w].factor }
        group_by           = []
        severity           = local.burn_windows[w].severity == "page" ? "sev2" : "sev3"
        priority           = local.burn_windows[w].severity == "page" ? 2 : 3
        team               = s.team
        owner              = s.team
        service            = s.service
        slo_id             = slo_id
        slo_url            = ""
        runbook_name       = "Runbook: Application Dependency Degradation"
        runbook_url        = format("%s/%d", local.runbooks.notebook_base_url, 15208648)
        workflow           = "auto-major-incident"
        failure_domain     = s.service
        criticality        = "tier2"
        monitoring_profile = "critical"
        platform           = local.domains[s.domain].platform_tag
        resource_type      = "slo"
        region             = "global"
        routing_rule       = local.burn_windows[w].severity == "page" ? "incident-page" : "ticket-only"
        snow_record        = local.burn_windows[w].severity == "page" ? "incident-p2" : "task-p3"
        support_model      = "24x7"
        pages              = local.burn_windows[w].severity == "page"
        summary            = "Error budget for ${s.name} is burning ${local.burn_windows[w].factor}x faster than sustainable (${local.burn_windows[w].long_window}/${local.burn_windows[w].short_window} windows)."
        impact             = "Customer-facing objective at risk: at this rate the ${s.timeframe} budget is exhausted early."

        notify_no_data      = null
        no_data_timeframe   = null
        evaluation_delay    = null
        new_group_delay     = null
        renotify_interval   = null
        require_full_window = null
        timeout_h           = null
        dedup_suffix        = ".${slo_id}.${w}"
        extra_tags          = ["monitor_type:slo-burn"]
        managed_source      = "platform"
        request_id          = ""
      }
    }
  ]...)
}

module "slos" {
  source       = "../../modules/slo_with_burn"
  slos         = local.slos_to_manage
  adopted_slos = local.adopted_slo_ids
}

import {
  for_each = local.slo_import_map
  to       = module.slos.datadog_service_level_objective.this[each.key]
  id       = each.value
}

module "burn_monitors" {
  source       = "../../modules/monitor_factory"
  instances    = local.burn_instances
  defaults     = local.monitor_defaults
  cardinality  = local.cardinality_guardrails
  api_validate = var.datadog_validate
}
