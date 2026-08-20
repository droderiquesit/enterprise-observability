# =============================================================================
# SLO LIFECYCLE + MULTI-WINDOW BURN-RATE ALERTING
#
# Burn-rate monitors are the PRIMARY customer-impact paging signal in this
# framework. Everything else — infrastructure, saturation, capacity — supports
# diagnosis. A page should mean "customers are losing something", and the only
# honest measure of that is error-budget consumption.
#
# TWO SLO SCOPES keep the object count bounded:
#   domain SLOs   ~20 for the entire enterprise, covering tier1/tier2
#   service SLOs  the objectives a mission-critical service resolves through
#                 the §12 chain (tens of services, not thousands)
#
# A service does not write its SLOs. It states its intent — a tier, an entity
# type, optionally a profile name, optionally one overridden number — and the
# chain below resolves the objectives from platform/policy/slo_profiles.yaml.
# That is what lets two technically identical services carry different targets
# without carrying different monitoring.
# =============================================================================

locals {
  burn_windows = local.global.burn_rate_windows

  # --- domain SLOs ----------------------------------------------------------
  domain_slos = {
    for id, s in local.slo_catalog : id => {
      name = s.name
      type = s.type
      # Ownership/provenance suffix is appended by modules/slo.
      description = "Domain SLO for ${s.domain}."
      domain      = s.domain
      service     = s.service
      team        = s.team
      target      = s.target
      timeframe   = s.timeframe
      warning     = null
      query       = try(s.query, null)
      # Monitor-type SLOs take their membership from the PROD CRITICAL
      # instances of their declared member archetypes. Membership is therefore
      # rebuilt automatically whenever the catalog changes — an SLO can never
      # end up pointing at monitors that no longer exist.
      #
      # When the SLO carries burn-rate alerts, membership is further
      # restricted to METRIC monitors ("query alert"): Datadog rejects a
      # burn_rate() alert on a monitor-based SLO containing any non-metric
      # member ("Alerting on monitor based SLOs currently supports metric
      # monitors" — found by live plan validation; service-check members
      # tripped it). Non-metric members still alert in their own right —
      # they just cannot participate in a burn-alerted SLI. An SLO with no
      # burn alerts keeps its full membership, service checks included
      # (slo-infra-compute-availability is exactly that: all members are
      # service checks, so it sets burn_alerts: [] in the catalog).
      monitor_ids = s.type == "monitor" ? [
        for k, inst in local.archetype_instances :
        tonumber(module.coverage_monitors.monitor_ids[k])
        if inst.env == "prod" && inst.band == "critical" && contains(try(s.member_archetypes, []), inst.archetype) && (length(try(s.burn_alerts, [])) == 0 || inst.monitor_type == "query alert")
      ] : []
      tags = ["scope:domain", "domain:${s.domain}", "platform:${local.domains[s.domain].platform_tag}"]
    }
  }

  # --- per-service SLOs: the resolved objectives (§11, §12, §14) ------------
  # WHICH services get their own objectives (§14 — not every entity needs one).
  # Either the tier asks for per-service scope (today tier0, which is what keeps
  # the object count bounded by mission-critical services rather than by estate
  # size), or the service opted in by declaring an `slo:` block — the escape
  # hatch for a tier1 service with one contractual endpoint, which should not
  # have to be relabelled tier0 to make a promise.
  svc_slo_services = {
    for name, s in local.service_docs : name => s
    if contains(s.envs, "prod") && (
      local.tiers[s.tier].slo.scope == local.slo_profiles.criticality.materialize_when_scope
      || try(s.slo, null) != null
    )
  }

  # (service × objective) — the entity type is the ONLY layer that can introduce
  # an objective, because it is the layer that owns the SLI. A profile that
  # enables an objective its entity type never declared would produce an SLO
  # with no query, which tools/slo_resolver.py rejects in CI.
  svc_objective_keys = merge([
    for name, s in local.svc_slo_services : {
      for obj_name, _ in try(local.slo_profiles.by_entity_type[s.service_archetype].objectives, {}) :
      "${name}.${obj_name}" => { service = name, objective = obj_name, svc = s }
    }
  ]...)

  # ---------------------------------------------------------------------------
  # THE RESOLUTION CHAIN (§12)
  #
  #   enterprise defaults → entity type → platform → criticality → environment
  #   → slo_profile → service override
  #
  # Later layers win, FIELD BY FIELD — that is what lets a service change one
  # number without restating the SLI, the timeframe or the burn windows. Each
  # field below is a `try()` chain written in REVERSE layer order, because
  # `try` returns the first expression that succeeds and a missing key is an
  # error: first success = last layer that set it.
  #
  # Two layers are absent from the chains and deliberately so:
  #   platform     may not set `target` or `burn_alerts` — criticality resolves
  #                after it and would overwrite both, so a platform-wide target
  #                is a value that silently never applies (lint enforces it).
  #   environment  is applied as `manages_prod` below. environments.yaml says
  #                only prod carries `slo_impact`, so only a prod apply
  #                materializes objectives at all.
  #
  # The same chain, over the same YAML, is implemented in tools/slo_resolver.py
  # for the tooling. Neither reads the other.
  # ---------------------------------------------------------------------------
  svc_resolved = {
    for k, v in local.svc_objective_keys : k => {
      service   = v.service
      objective = v.objective
      svc       = v.svc
      domain    = local.service_archetype_domain[v.svc.service_archetype]

      enabled = try(v.svc.slo.objectives[v.objective].enabled,
        local.slo_profiles.profiles[v.svc.slo.profile].objectives[v.objective].enabled,
        local.slo_profiles.by_entity_type[v.svc.service_archetype].objectives[v.objective].enabled,
      local.slo_profiles.defaults.enabled)

      type = try(v.svc.slo.objectives[v.objective].type,
        local.slo_profiles.profiles[v.svc.slo.profile].objectives[v.objective].type,
        local.slo_profiles.by_platform[local.service_archetype_domain[v.svc.service_archetype]].objectives[v.objective].type,
        local.slo_profiles.by_entity_type[v.svc.service_archetype].objectives[v.objective].type,
      local.slo_profiles.defaults.type)

      target = try(v.svc.slo.objectives[v.objective].target,
        local.slo_profiles.profiles[v.svc.slo.profile].objectives[v.objective].target,
        local.tiers[v.svc.tier].slo.objectives[v.objective],
        local.slo_profiles.by_entity_type[v.svc.service_archetype].objectives[v.objective].target,
      local.slo_profiles.defaults.target)

      timeframe = try(v.svc.slo.objectives[v.objective].timeframe,
        local.slo_profiles.profiles[v.svc.slo.profile].objectives[v.objective].timeframe,
        local.slo_profiles.by_platform[local.service_archetype_domain[v.svc.service_archetype]].objectives[v.objective].timeframe,
        local.slo_profiles.by_entity_type[v.svc.service_archetype].objectives[v.objective].timeframe,
      local.slo_profiles.defaults.timeframe)

      burn_alerts = try(v.svc.slo.objectives[v.objective].burn_alerts,
        local.slo_profiles.profiles[v.svc.slo.profile].objectives[v.objective].burn_alerts,
        local.tiers[v.svc.tier].slo.burn_windows,
        local.slo_profiles.by_entity_type[v.svc.service_archetype].objectives[v.objective].burn_alerts,
      local.slo_profiles.defaults.burn_alerts)

      member_archetypes = try(local.slo_profiles.profiles[v.svc.slo.profile].objectives[v.objective].member_archetypes,
      local.slo_profiles.by_entity_type[v.svc.service_archetype].objectives[v.objective].member_archetypes, [])

      numerator = try(local.slo_profiles.profiles[v.svc.slo.profile].objectives[v.objective].sli.numerator,
        local.slo_profiles.by_platform[local.service_archetype_domain[v.svc.service_archetype]].objectives[v.objective].sli.numerator,
      local.slo_profiles.by_entity_type[v.svc.service_archetype].objectives[v.objective].sli.numerator, "")

      denominator = try(local.slo_profiles.profiles[v.svc.slo.profile].objectives[v.objective].sli.denominator,
        local.slo_profiles.by_platform[local.service_archetype_domain[v.svc.service_archetype]].objectives[v.objective].sli.denominator,
      local.slo_profiles.by_entity_type[v.svc.service_archetype].objectives[v.objective].sli.denominator, "")

      # The threshold merges per SUB-FIELD for the same reason: a service that
      # promises 200ms writes `threshold: {value: 200}` and keeps the statistic
      # and the unit its entity type defined. Replacing the whole map would drop
      # them and produce an SLI reading a tag nobody emits.
      threshold_value = try(v.svc.slo.objectives[v.objective].threshold.value,
        local.slo_profiles.profiles[v.svc.slo.profile].objectives[v.objective].threshold.value,
        local.slo_profiles.by_platform[local.service_archetype_domain[v.svc.service_archetype]].objectives[v.objective].threshold.value,
      local.slo_profiles.by_entity_type[v.svc.service_archetype].objectives[v.objective].threshold.value, "")

      threshold_unit = try(v.svc.slo.objectives[v.objective].threshold.unit,
        local.slo_profiles.profiles[v.svc.slo.profile].objectives[v.objective].threshold.unit,
        local.slo_profiles.by_platform[local.service_archetype_domain[v.svc.service_archetype]].objectives[v.objective].threshold.unit,
      local.slo_profiles.by_entity_type[v.svc.service_archetype].objectives[v.objective].threshold.unit, "")
    }
  }

  # The objectives that are actually created. `enabled` is what separates "this
  # entity type COULD carry a latency objective" from "this service promised
  # one" — see slo_profiles.yaml. A service that names no profile therefore
  # resolves exactly what it resolved before profiles existed.
  svc_slos = {
    for k, r in local.svc_resolved : (
      r.objective == "availability" ? "slo-svc-${r.service}" : "slo-svc-${r.service}-${r.objective}"
      ) => {
      name = "${r.service} ${r.objective} (${r.svc.tier})"
      type = r.type
      description = join(" ", [
        "Per-service ${r.objective} objective for ${r.service}.",
        "Resolved from ${try(r.svc.slo.profile, "the ${r.svc.tier} default for a ${r.svc.service_archetype}")}.",
      ])
      domain    = r.domain
      service   = r.service
      team      = r.svc.team
      target    = r.target
      timeframe = r.timeframe
      warning   = null

      # __LATENCY_BUCKET__ carries the objective's threshold into the SLI: a
      # Datadog metric SLI is a ratio of two counts, so "faster than 300ms" has
      # to already exist as a tag on the count (see slo_profiles.yaml). The tag
      # spelling here and in tools/slo_resolver.py must stay identical.
      query = r.type != "metric" ? null : {
        numerator = replace(replace(replace(r.numerator,
          "__SERVICE__", r.service),
          "__ENV__", "prod"),
        "__LATENCY_BUCKET__", "under_${r.threshold_value}${r.threshold_unit}")
        denominator = replace(replace(replace(r.denominator,
          "__SERVICE__", r.service),
          "__ENV__", "prod"),
        "__LATENCY_BUCKET__", "under_${r.threshold_value}${r.threshold_unit}")
      }

      # A monitor-type per-service objective takes its membership the same way
      # a domain SLO does. Note what that means: the platform's monitors are
      # grouped across every service carrying an archetype's tag, so such an
      # objective measures the ARCHETYPE's availability as this service sees
      # it, not this service alone. That is honest for a datastore ("is the
      # database up"), and it is why the metric form is the default everywhere
      # a per-request SLI exists.
      monitor_ids = r.type != "monitor" ? [] : [
        for ik, inst in local.archetype_instances :
        tonumber(module.coverage_monitors.monitor_ids[ik])
        if inst.env == "prod" && inst.band == "critical" && contains(r.member_archetypes, inst.archetype)
      ]

      tags = [
        "scope:service", "tier:${r.svc.tier}", "service:${r.service}",
        "objective:${r.objective}", "entity_type:${r.svc.service_archetype}",
        "slo_profile:${try(r.svc.slo.profile, "none")}",
      ]
    }
    if r.enabled
  }

  # INVARIANT, applied after the whole chain because no tier may override it:
  # Datadog rejects burn_rate() on a monitor-based SLO with any non-metric
  # member ("Alerting on monitor based SLOs currently supports metric monitors"
  # — found by live plan validation). A tier that asks for three burn windows
  # on a service-check-backed objective gets none, rather than a failed apply.
  svc_burn_windows = {
    for k, r in local.svc_resolved :
    (r.objective == "availability" ? "slo-svc-${r.service}" : "slo-svc-${r.service}-${r.objective}") => (
      r.type == "monitor" && length([
        for m in r.member_archetypes : m
        if try(local.archetypes[m].monitor_type, "") != "query alert"
      ]) > 0 ? [] : r.burn_alerts
    )
    if r.enabled
  }

  # SLOs and their burn monitors are prod-scoped objects (`burn.prod.*` — an
  # error budget is only measured against production). Under per-environment
  # state files (ADR-016) exactly one environment's apply must own them, or a
  # qa apply and a prod apply would each create their own copy. That owner is
  # the prod apply. (Filtered comprehension, not a ternary: `cond ? map : {}`
  # trips inconsistent-conditional-type unification on object maps.)
  manages_prod = contains(var.environments, "prod")
  all_slos     = { for k, v in merge(local.domain_slos, local.svc_slos) : k => v if local.manages_prod }

  # --- burn-rate monitor instances -----------------------------------------
  # One monitor per (SLO × window). Windows come from global.yaml and are
  # selected per SLO, which is how tier0 gets fast burn and tier2 does not.
  #
  # The manages_prod restriction is applied HERE, on the iteration source —
  # not on the built result. The monitor bodies below interpolate
  # module.slos.slo_datadog_ids[slo_id], and in a non-prod apply that map is
  # empty: indexing it errors even for entries a later filter would discard,
  # because HCL builds the whole source collection before any filter runs.
  # An empty source means the bodies are never evaluated at all.
  burn_source = { for k, v in merge(
    { for id, s in local.slo_catalog : id => {
      name      = s.name, service = s.service, team = s.team, domain = s.domain,
      timeframe = s.timeframe, windows = try(s.burn_alerts, [])
    } },
    # Per-service objectives carry their OWN windows: the burn windows are a
    # resolved field like any other, so a service that promised only a slow
    # burn does not inherit its tier's fast-burn pages.
    { for id, s in local.svc_slos : id => {
      name      = s.name, service = s.service, team = s.team, domain = s.domain,
      timeframe = s.timeframe, windows = local.svc_burn_windows[id]
    } },
  ) : k => v if local.manages_prod }

  burn_instances = merge([
    for slo_id, s in local.burn_source : {
      for w in s.windows : "burn.prod.${slo_id}.${w}" => {
        archetype = "slo-burn-${w}"
        title     = "${s.name} — error budget burn (${w})"
        domain    = s.domain
        env       = "prod"
        band      = "critical"
        signal    = "error_budget"

        monitor_type = "slo alert"
        detection    = "slo_burn"
        query        = "burn_rate(\"${module.slos.slo_datadog_ids[slo_id]}\").over(\"${s.timeframe}\").long_window(\"${local.burn_windows[w].long_window}\").short_window(\"${local.burn_windows[w].short_window}\") > ${local.burn_windows[w].factor}"
        thresholds   = { critical = local.burn_windows[w].factor }
        group_by     = []
        notify_by    = []

        evaluation_delay = null
        new_group_delay  = null

        impact_class       = local.burn_windows[w].impact_class
        priority           = local.prio.matrix[local.burn_windows[w].impact_class]["critical"]
        tier               = "tier0"
        monitoring_profile = "critical"
        pages              = contains(["P1", "P2"], local.prio.matrix[local.burn_windows[w].impact_class]["critical"])
        support_model      = "24x7"
        slo_impacting      = true

        team                 = s.team
        owner                = s.team
        service              = s.service
        resource_type        = "slo"
        region               = ""
        notification_profile = "production_critical"
        failure_domain       = s.service

        slo_id               = slo_id
        slo_url              = ""
        runbook              = "slo-error-budget-burn"
        runbook_notebook_id  = try(local.runbook_notebook_id["slo-error-budget-burn"], "")
        runbook_notebook_url = try(local.runbook_notebook_url["slo-error-budget-burn"], "")
        runbook_title        = try(local.runbook_title["slo-error-budget-burn"], "SLO Error Budget Burn")
        workflow             = "auto-major-incident"

        summary     = "Error budget for ${s.name} is being consumed ${local.burn_windows[w].factor}× faster than sustainable, confirmed over ${local.burn_windows[w].long_window} and still true over the last ${local.burn_windows[w].short_window}."
        impact      = "Customer-facing objective at risk. At the current rate the ${s.timeframe} budget is exhausted well before the window ends."
        why         = "Multi-window burn rate: the long window (${local.burn_windows[w].long_window}) proves the burn is sustained rather than a spike, and the short window (${local.burn_windows[w].short_window}) means it is still happening now. Both must be true, which is what makes burn-rate alerting both fast and quiet."
        next_action = "Identify the largest contributor to the budget burn (service, endpoint, dependency), then follow the error-budget runbook. If the burn is a known incident, attach this alert to the existing incident rather than opening a new one."

        notify_no_data      = null
        no_data_timeframe   = null
        renotify_interval   = 30
        require_full_window = null

        # AUTO-RESOLVE by priority. A burn-rate query reports for as long as the
        # SLO has any traffic, so this window only ever closes a burn alert on
        # an objective that has gone completely silent — which is a different
        # alert's job (telemetry_health), not this one's to hold open forever.
        timeout_h = local.auto_resolve.by_priority[
          local.prio.matrix[local.burn_windows[w].impact_class]["critical"]
        ]

        compliance       = false
        compliance_scope = "sox"
        dedup_suffix     = ".${slo_id}.${w}"
        extra_tags       = ["burn_window:${w}", "slo_scope:${startswith(slo_id, "slo-svc-") ? "service" : "domain"}"]
        managed_source   = "platform"
        request_id       = ""
      }
    }
  ]...)
}

module "slos" {
  source = "../../modules/slo"
  slos   = local.all_slos
}
