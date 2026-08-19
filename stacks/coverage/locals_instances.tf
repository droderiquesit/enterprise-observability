# =============================================================================
# ARCHETYPE INSTANCE GENERATION — THE CORE OF THE FRAMEWORK
#
#   instance = archetype × environment × alert_band
#
# NOT archetype × resource, and NOT archetype × service. Resources live in
# monitor GROUPS and are selected by tag, so:
#
#   * a new service that starts emitting telemetry is covered on first signal
#   * covering 10,000 more services creates ZERO new Datadog objects
#   * the managed estate grows only when someone adds a monitoring DECISION
#
# The naive alternative — 100 services × 4 environments × 20 signals — is 8,000
# monitors. This produces a few hundred, with identical coverage.
# =============================================================================

locals {

  # --- 1. Candidate (archetype × env × band) triples -------------------------
  # An instance exists only where all three agree:
  #   the archetype declares the env, the env instantiates the band, and the
  #   archetype declares the band.
  candidates = flatten([
    for aid, a in local.archetypes : [
      for env in var.environments : [
        for band in local.env_policy[env].bands_instantiated : {
          archetype = aid
          env       = env
          band      = band
        }
        if contains(a.bands, band)
      ]
      if contains(a.envs, env) && local.env_policy[env].alerting
    ]
  ])

  # --- 2. Resolution --------------------------------------------------------
  resolved = {
    for c in local.candidates :
    "${c.env}.${c.band}.${local.archetypes[c.archetype].domain}.${c.archetype}" => {
      a    = local.archetypes[c.archetype]
      env  = c.env
      band = c.band

      # Tier represented by this band (tiers.yaml → band_strictest_tier).
      tier = local.tier_maps.band_strictest_tier[c.band]

      # Monitoring profile: the strictest profile that maps to this band.
      profile = (
        c.band == "critical" ? (local.archetypes[c.archetype].domain == "security" ? "regulated" :
        try(local.archetypes[c.archetype].compliance, false) ? "regulated" : "critical") :
        c.band == "standard" ? "standard" : "baseline"
      )

      # ---- PRIORITY -------------------------------------------------------
      # matrix[impact_class][band], clamped to the environment ceiling, with an
      # approved exception able to LOWER it further (never raise it).
      priority = local.rank_priority[
        max(
          local.priority_rank[local.prio.matrix[local.archetypes[c.archetype].impact_class][c.band]],
          local.priority_rank[local.env_policy[c.env].priority_ceiling],
          local.priority_rank[
            lookup(local.priority_exceptions, "${c.archetype}.${c.env}",
            lookup(local.priority_exceptions, "${c.archetype}.*", "P1"))
          ]
        )
      ]
    }
  }

  # --- 3. Scope construction ------------------------------------------------
  # Every query is scoped to env + alert_band + the archetype's own selector.
  # This is what lets ONE monitor cover an entire class of resources: the tags
  # do the selection, so the monitor never names a service.
  scope_for = {
    for k, r in local.resolved : k => join(",", compact([
      "env:${r.env}",
      "alert_band:${r.band}",
      try(r.a.selector, "") != "" ? r.a.selector : "",
    ]))
  }
  # Event-search syntax uses spaces rather than commas.
  escope_for = {
    for k, r in local.resolved : k => join(" ", compact([
      "env:${r.env}",
      "alert_band:${r.band}",
      try(r.a.selector, "") != "" ? replace(r.a.selector, ":", ":") : "",
    ]))
  }

  # --- 4. Environment-aware evaluation window -------------------------------
  windowed_query = {
    for k, r in local.resolved : k => (
      contains(keys(local.window_scale), try(r.a.evaluation_window, "")) && r.env != "prod"
      ? replace(r.a.query, r.a.evaluation_window, local.window_scale[r.a.evaluation_window][r.env])
      : r.a.query
    )
  }

  # --- 5. Threshold resolution ---------------------------------------------
  #
  # Thresholds are NOT scaled per environment, deliberately.
  #
  # Datadog requires `monitor_thresholds` to match the numeric literal inside
  # the query. Scaling one without the other is rejected by the API; scaling
  # both means rewriting a number inside a query string at plan time, which
  # makes the deployed monitor differ from the reviewed catalog entry in a way
  # nobody can see in a diff. (It also produced 3.60000000000000000002 from a
  # float multiply — a good sign the approach was wrong.)
  #
  # Environment tolerance is expressed instead through mechanisms that cannot
  # silently disagree with the query:
  #     * which alert bands are instantiated at all (dev: none, QA: baseline)
  #     * the priority ceiling
  #     * WIDER EVALUATION WINDOWS (section 4 above) — stage and QA wait longer
  #       before believing a signal, which is the honest form of "less sensitive"
  #     * renotify intervals and new-group delays
  #
  # Thresholds come from the catalog, unmodified. There is no override path at
  # all — not per environment, not per exception. If a number is wrong it is
  # wrong in the catalog, where changing it produces a reviewable diff.
  final_thresholds = { for k, r in local.resolved : k => r.a.thresholds }

  # --- 6. Ownership + routing ----------------------------------------------
  owning_team = {
    for k, r in local.resolved : k => try(
      local.domains[r.a.domain].routing_override_team,
      local.domains[r.a.domain].owner_team
    )
  }

  notification_profile_for = {
    for k, r in local.resolved : k => (
      r.a.domain == "security" ? "security_operational" :
      contains(local.nonprod_envs, r.env) ? "nonprod_standard" :
      r.band == "critical" ? "production_critical" :
      r.band == "standard" ? "production_standard" :
      "production_baseline"
    )
  }

  # --- 7. Paging decision ---------------------------------------------------
  # Paging is the most expensive thing this platform can do to a human, so it
  # is the most constrained decision in the whole hierarchy.
  #
  # An ARCHETYPE monitor pages only at P1 — an unambiguous outage condition.
  # A P2 archetype (a deadlock, an OOMKill, a failed cron, a retry storm) is a
  # real problem with a real incident and a real ticket, but it is a SYMPTOM:
  # it has not established customer harm. Confirmed impact comes from two
  # places, and both of them page at P2:
  #     * SLO burn-rate monitors (stacks/coverage/slos.tf) — measured harm
  #     * composite monitors     (locals_composites.tf)    — two conditions agreeing
  #
  # See platform/policy/priorities.yaml → paging_rule.
  pages_for = {
    for k, r in local.resolved : k => (
      local.env_policy[r.env].paging_allowed
      && r.band == "critical"
      && local.resolved[k].priority == "P1"
    )
  }

  # --- 8. The instance map consumed by the factory --------------------------
  archetype_instances = {
    for k, r in local.resolved : k => {
      archetype = r.a.id
      title     = r.a.title
      domain    = r.a.domain
      env       = r.env
      band      = r.band
      signal    = r.a.signal

      monitor_type = r.a.monitor_type
      detection    = r.a.detection
      query = replace(
        replace(local.windowed_query[k], "__SCOPE__", local.scope_for[k]),
        "__ESCOPE__", local.escope_for[k]
      )
      thresholds       = local.final_thresholds[k]
      group_by         = try(r.a.group_by, [])
      notify_by        = try(r.a.notify_by, [])
      evaluation_delay = null
      new_group_delay  = null

      impact_class       = r.a.impact_class
      priority           = r.priority
      tier               = r.tier
      monitoring_profile = r.profile
      pages              = local.pages_for[k]
      support_model      = local.tiers[r.tier].support_model
      slo_impacting      = local.env_policy[r.env].slo_impact

      team                 = local.owning_team[k]
      owner                = local.owning_team[k]
      service              = local.slo_catalog[r.a.slo_id].service
      resource_type        = r.a.resource_type
      region               = ""
      notification_profile = local.notification_profile_for[k]
      failure_domain       = r.a.failure_domain

      slo_id               = r.a.slo_id
      slo_url              = ""
      runbook              = r.a.runbook
      runbook_notebook_id  = try(local.runbook_notebook_id[r.a.runbook], "")
      runbook_notebook_url = try(local.runbook_notebook_url[r.a.runbook], "")
      runbook_title        = try(local.runbook_title[r.a.runbook], r.a.runbook)
      workflow             = r.a.workflow

      summary = try(r.a.notes, "${r.a.title}: ${r.a.signal} signal detected by ${r.a.detection} analysis.")
      impact = (
        r.a.impact_class == "customer_impact" ? "Customers are affected now, or a mission-critical capability is unavailable." :
        r.a.impact_class == "degradation" ? "The service still functions but measurably worse; a subset of traffic or users is failing." :
        r.a.impact_class == "risk" ? "Nothing is broken yet. A boundary will be crossed if nobody acts within the lead time this monitor provides." :
        "Observability or configuration hygiene is degraded. No direct customer impact, but our ability to see or govern the estate is reduced."
      )
      why = (
        r.a.detection == "anomaly" ? "The signal deviated from its own learned baseline by more than the configured number of deviations — not because it crossed a fixed number." :
        r.a.detection == "seasonal_anomaly" ? "The signal deviated from its learned SEASONAL baseline (same hour, same day of week), so normal daily and weekly cycles are already accounted for." :
        r.a.detection == "forecast" ? "Extrapolating the recent trend, this resource is projected to cross its limit inside the forecast horizon. It has not crossed it yet — that is the point." :
        r.a.detection == "outlier" ? "This member diverged from its peer group. Every peer receives the same work, so divergence is the defect." :
        r.a.detection == "rate_of_change" ? "The signal changed faster than the configured percentage relative to its own recent history. Speed of degradation, not absolute level." :
        r.a.detection == "service_check" ? "A check reported a non-OK status for consecutive evaluations." :
        r.a.detection == "event" ? "A discrete platform event matched this monitor's search." :
        try(r.a.rationale_fixed_threshold, "A fixed threshold was crossed. This threshold has recorded operational meaning.")
      )
      next_action = "Open the runbook, confirm scope from the group tags, and follow the validation steps. The attached workflow output already contains the standard diagnostics."

      notify_no_data      = try(r.a.notify_no_data, null)
      no_data_timeframe   = try(r.a.no_data_timeframe, null)
      renotify_interval   = local.tiers[r.tier].renotify_interval_minutes > 0 ? local.tiers[r.tier].renotify_interval_minutes : null
      require_full_window = null

      # AUTO-RESOLVE — mandatory, never Datadog's "never". Precedence is
      # documented in locals_policy.tf → auto_resolve.
      timeout_h = coalesce(
        try(r.a.auto_resolve_hours, null),
        try(local.auto_resolve.by_signal[r.a.signal], null),
        try(local.auto_resolve.by_detection[r.a.detection], null),
        local.auto_resolve.by_priority[r.priority],
      )

      compliance       = try(r.a.compliance, false)
      compliance_scope = "sox"
      dedup_suffix     = ".${r.band}"
      extra_tags       = try(r.a.release_gate, false) ? ["release_gate:true"] : []
      managed_source   = "platform"
      request_id       = ""
    }
  }
}
