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
#   tier0 SLOs    one per mission-critical service (tens, not thousands)
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

  # --- tier0 per-service SLOs ----------------------------------------------
  tier0_services = {
    for name, s in local.service_docs : name => s
    if s.tier == "tier0" && contains(s.envs, "prod")
  }

  tier0_slos = {
    for name, s in local.tier0_services : "slo-svc-${name}" => {
      name        = "${name} availability (tier0)"
      type        = "metric"
      description = "Tier0 per-service SLO. Mission-critical services carry their own error budget."
      domain      = local.service_archetype_domain[s.service_archetype]
      service     = name
      team        = s.team
      target      = local.tiers.tier0.slo.objectives.availability
      timeframe   = local.slo_doc.tier0_slo_template.timeframe
      warning     = null
      query = {
        numerator   = replace(local.slo_doc.tier0_slo_template.query.numerator, "__SERVICE__", name)
        denominator = replace(local.slo_doc.tier0_slo_template.query.denominator, "__SERVICE__", name)
      }
      monitor_ids = []
      tags        = ["scope:service", "tier:tier0", "service:${name}"]
    }
  }

  # SLOs and their burn monitors are prod-scoped objects (`burn.prod.*` — an
  # error budget is only measured against production). Under per-environment
  # state files (ADR-016) exactly one environment's apply must own them, or a
  # qa apply and a prod apply would each create their own copy. That owner is
  # the prod apply. (Filtered comprehension, not a ternary: `cond ? map : {}`
  # trips inconsistent-conditional-type unification on object maps.)
  manages_prod = contains(var.environments, "prod")
  all_slos     = { for k, v in merge(local.domain_slos, local.tier0_slos) : k => v if local.manages_prod }

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
    { for id, s in local.tier0_slos : id => {
      name      = s.name, service = s.service, team = s.team, domain = s.domain,
      timeframe = s.timeframe, windows = local.slo_doc.tier0_slo_template.burn_alerts
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
        timeout_h           = null

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
