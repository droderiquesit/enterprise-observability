# =============================================================================
# SINGLE-YAML CUSTOM MONITORS
#
# platform/monitors/*.yaml → fully compliant Datadog monitors.
#
# A team writes the file in the "Example Monitor Definitions" shape and nothing
# else. Everything below is what the platform derives on their behalf: tags,
# naming, priority, routing, message contract, recovery behavior, correlation
# keys, evaluation windows, ownership, and the SLO association.
#
# CI (tools/validate_monitors.py) rejects a non-compliant manifest before
# Terraform ever sees it; the factory's preconditions are the second line of
# defence. Teams never write HCL.
# =============================================================================

locals {
  custom_docs = {
    for f in fileset("${local.policy_dir}/monitors", "*.yaml") :
    trimsuffix(f, ".yaml") => yamldecode(file("${local.policy_dir}/monitors/${f}")).monitor
  }

  # (file × env) — one monitor per declared environment, from ONE definition.
  # Restricted to the environments THIS apply manages, so each monitor lands
  # in exactly one environment's state file (ADR-016).
  custom_candidates = flatten([
    for id, m in local.custom_docs : [
      for env in m.env : { id = id, env = env, m = m }
      if local.env_policy[env].alerting && contains(var.environments, env)
    ]
  ])

  custom_resolved = {
    for c in local.custom_candidates : "custom.${c.env}.${c.id}" => {
      id  = c.id
      env = c.env
      m   = c.m

      # `predictive: {anomaly: true}` selects the catalog's declared predictive
      # variant of the archetype when one exists — the team expresses INTENT,
      # the platform picks the technique.
      base_id = (
        c.m.archetype == "custom" ? "custom" :
        try(c.m.predictive.anomaly, false)
        ? try(local.archetypes[c.m.archetype].predictive_variant, c.m.archetype)
        : c.m.archetype
      )

      # The owning service's tier decides the band; unregistered services fall
      # back to the standard band so a missing registry file cannot silently
      # grant a team tier0 paging.
      tier = try(
        local.service_docs[c.m.service].tier,
        try(c.m.tier, "tier2")
      )
    }
  }

  custom_band = {
    for k, r in local.custom_resolved : k => local.tiers[r.tier].alert_band
  }

  custom_base = {
    for k, r in local.custom_resolved : k =>
    r.base_id == "custom" ? null : local.archetypes[r.base_id]
  }

  # Custom monitors are SERVICE-scoped: env + service, plus the alert band so
  # that they inherit the same environment and tier semantics as the packs.
  custom_scope = {
    for k, r in local.custom_resolved : k =>
    "env:${r.env},service:${r.m.service}"
  }

  # `auto` means "use the archetype's tuned value". If the archetype does not
  # define that threshold (e.g. an anomaly archetype has no `warning`), the key
  # is DROPPED rather than invented — a made-up warning threshold is worse than
  # no warning threshold.
  custom_thresholds = {
    for k, r in local.custom_resolved : k => {
      for tk, tv in try(r.m.thresholds, {}) :
      tk => tostring(tv) == "auto" ? tonumber(try(local.custom_base[k].thresholds[tk], 0)) : tonumber(tv)
      if tostring(tv) != "auto" || can(local.custom_base[k].thresholds[tk])
    }
  }

  custom_priority = {
    for k, r in local.custom_resolved : k => local.rank_priority[
      max(
        local.priority_rank[
          try(r.m.priority,
            local.prio.matrix[
              try(r.m.impact_class, local.custom_base[k].impact_class)
            ][local.custom_band[k]]
          )
        ],
        local.priority_rank[local.env_policy[r.env].priority_ceiling]
      )
    ]
  }

  custom_instances = {
    for k, r in local.custom_resolved : k => {
      archetype = r.base_id
      title     = replace(title(replace(r.m.name, "-", " ")), "Api", "API")
      domain    = try(r.m.domain, local.custom_base[k].domain)
      env       = r.env
      band      = local.custom_band[k]
      signal    = try(local.custom_base[k].signal, "custom")

      monitor_type = try(r.m.monitor_type, local.custom_base[k].monitor_type)
      detection    = try(r.m.detection, local.custom_base[k].detection)
      query = replace(
        replace(
          try(r.m.query, local.custom_base[k].query),
        "__SCOPE__", local.custom_scope[k]),
      "__ESCOPE__", replace(local.custom_scope[k], ",", " "))
      thresholds       = local.custom_thresholds[k]
      group_by         = try(r.m.group_by, try(local.custom_base[k].group_by, []))
      notify_by        = []
      evaluation_delay = null
      new_group_delay  = null

      impact_class       = try(r.m.impact_class, local.custom_base[k].impact_class)
      priority           = local.custom_priority[k]
      tier               = r.tier
      monitoring_profile = local.tiers[r.tier].monitoring_profile
      # Self-service monitors follow the same rule as the packs: P1 only.
      # A team cannot obtain a pager by writing P2 in a YAML file.
      pages = (
        local.env_policy[r.env].paging_allowed
        && local.custom_priority[k] == "P1"
        && local.custom_band[k] == "critical"
      )
      support_model = local.tiers[r.tier].support_model
      slo_impacting = local.env_policy[r.env].slo_impact

      team          = r.m.team
      owner         = r.m.team
      service       = r.m.service
      resource_type = try(r.m.resource_type, try(local.custom_base[k].resource_type, "service"))
      region        = ""
      notification_profile = try(r.m.notification_profile,
        contains(local.nonprod_envs, r.env) ? "nonprod_standard" :
        local.custom_band[k] == "critical" ? "production_critical" : "production_standard"
      )
      failure_domain = try(local.custom_base[k].failure_domain, r.m.service)

      slo_id               = r.m.slo
      slo_url              = ""
      runbook              = r.m.runbook
      runbook_notebook_id  = try(local.runbook_notebook_id[r.m.runbook], "")
      runbook_notebook_url = try(local.runbook_notebook_url[r.m.runbook], "")
      runbook_title        = try(local.runbook_title[r.m.runbook], r.m.runbook)
      workflow             = r.m.workflow

      summary     = try(r.m.summary, "${r.m.name}: custom monitor requested by ${r.m.team}.")
      impact      = try(r.m.impact, "Service-specific impact declared by the owning team; see the runbook.")
      why         = try(r.m.justification, "Custom detection requested by ${r.m.team} for ${r.m.service}.")
      next_action = "Open the runbook. This monitor was requested by ${r.m.team} for a service-specific condition, so the owning team's runbook is authoritative."

      notify_no_data      = try(r.m.notify_no_data, null)
      no_data_timeframe   = null
      renotify_interval   = local.tiers[r.tier].renotify_interval_minutes > 0 ? local.tiers[r.tier].renotify_interval_minutes : null
      require_full_window = null
      timeout_h           = null

      compliance       = false
      compliance_scope = "sox"
      dedup_suffix     = ".${r.id}"
      extra_tags       = ["request_source:self_service"]
      managed_source   = "self_service"
      request_id       = r.id
    }
  }
}
