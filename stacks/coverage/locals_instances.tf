# ---------------------------------------------------------------------------
# Archetype instance generation: (archetype × environment) → fully-resolved
# monitor instance. NOT (archetype × resource): resources live in monitor
# groups, so the managed-object count stays bounded (~dozens of monitors for
# 1M+ resources).
# ---------------------------------------------------------------------------

locals {
  candidate_keys = [
    for pair in setproduct(keys(local.archetypes), var.environments) :
    { archetype = pair[0], env = pair[1] }
    # Environment restriction on the archetype, and no alerting in
    # observe_only environments (dev/sandbox are excluded by policy).
    if contains(try(local.archetypes[pair[0]].envs, var.environments), pair[1])
    && local.env_policy[pair[1]].default_profile != "observe_only"
  ]

  resolved = {
    for c in local.candidate_keys :
    "${c.env}.${local.archetypes[c.archetype].domain}.${c.archetype}" => {
      arch    = local.archetypes[c.archetype]
      env     = c.env
      tier    = local.archetype_tier[c.archetype]
      profile = local.profile_for["${c.archetype}.${c.env}"]

      # Severity: archetype class → tier severity map → environment floor →
      # approved exception (highest layer wins).
      severity = coalesce(
        try([for e in lookup(local.active_exceptions, "${c.archetype}.${c.env}", []) : e.value if e.control == "severity"][0], null),
        local.env_policy[c.env].paging_allowed
        ? local.tiers[local.archetype_tier[c.archetype]].severity_map[local.archetypes[c.archetype].severity_class]
        : try(local.env_policy[c.env].severity_floor, "sev3")
      )

      team = try(
        local.profiles_db.profiles[local.profile_for["${c.archetype}.${c.env}"]].overrides.route_to_team,
        local.domains[local.archetypes[c.archetype].domain].owner_team
      )
    }
  }

  # Instances whose exception-resolved severity is `informational` are NOT
  # monitors — the signal stays telemetry/dashboards (recorded in outputs).
  suppressed_instances = { for k, r in local.resolved : k => r if r.severity == "informational" }

  archetype_instances = {
    for k, r in local.resolved : k => {
      archetype          = r.arch.id
      title              = r.arch.title
      domain             = r.arch.domain
      env                = r.env
      monitor_type       = r.arch.monitor_type
      query              = replace(r.arch.query, "__ENV__", r.env)
      thresholds         = { for tk, tv in r.arch.thresholds : tk => tv }
      group_by           = try(r.arch.group_by, [])
      severity           = r.severity
      priority           = local.tiers[r.tier].priority_map[r.severity]
      team               = r.team
      owner              = r.team
      service            = local.slo_catalog[r.arch.slo_id].service
      slo_id             = r.arch.slo_id
      slo_url            = ""
      runbook_name       = r.arch.runbook
      runbook_url        = try(format("%s/%d", local.runbooks.notebook_base_url, local.runbooks.notebooks[r.arch.runbook].id), "")
      workflow           = r.arch.workflow
      failure_domain     = r.arch.failure_domain
      criticality        = r.tier
      monitoring_profile = r.profile
      platform           = local.domains[r.arch.domain].platform_tag
      resource_type      = length(try(r.arch.group_by, [])) > 0 ? r.arch.group_by[0] : "platform"
      region             = "global"
      routing_rule       = local.routing.severities[r.severity].routing_rule
      snow_record        = local.routing.severities[r.severity].snow_record
      support_model      = local.tiers[r.tier].support_model
      pages              = local.routing.severities[r.severity].pages && local.env_policy[r.env].paging_allowed
      summary            = "Detection: ${r.arch.detection} (${r.arch.class})."
      impact             = ""

      notify_no_data    = try(r.arch.notify_no_data, null)
      no_data_timeframe = try(r.arch.no_data_timeframe, null)
      evaluation_delay  = null
      new_group_delay   = null
      renotify_interval = try(
        local.profiles_db.profiles[r.profile].overrides.renotify_interval,
        try(local.profiles_db.profiles[try(local.profiles_db.profiles[r.profile].inherits, "")].overrides.renotify_interval, null)
      )
      require_full_window = null
      timeout_h           = null
      extra_tags          = []
      managed_source      = "platform"
      request_id          = ""
    }
    if r.severity != "informational"
  }
}
