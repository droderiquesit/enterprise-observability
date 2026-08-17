# =============================================================================
# COMPOSITE RESOLUTION
#
# A composite converts a noisy symptom into a confirmed impact. Where a
# composite declares `demote_members: true`, its members are rewritten to P4
# and stripped of paging BEFORE they reach the factory — that demotion is the
# entire point. A composite that adds a page on top of the pages its members
# already send has made the noise worse, not better.
# =============================================================================

locals {

  # Only instantiate a composite where EVERY member instance actually exists
  # for that (env × band). Missing members are reported, never silently
  # dropped, so a catalog change cannot quietly disable a confirmed-impact page.
  composite_candidates = flatten([
    for cid, c in local.composites : [
      for env in c.envs : [
        for band in c.bands : {
          id   = cid
          c    = c
          env  = env
          band = band
          member_keys = [
            for m in c.members :
            "${env}.${band}.${local.archetypes[m].domain}.${m}"
          ]
        }
        if contains(var.environments, env) && local.env_policy[env].alerting
      ]
    ]
  ])

  composite_resolvable = {
    for cc in local.composite_candidates :
    "composite.${cc.env}.${cc.band}.${cc.id}" => cc
    if alltrue([for mk in cc.member_keys : contains(keys(local.archetype_instances), mk)])
  }

  composite_unresolvable = [
    for cc in local.composite_candidates :
    "${cc.id} (${cc.env}/${cc.band}) — missing members: ${join(", ", [
      for mk in cc.member_keys : mk if !contains(keys(local.archetype_instances), mk)
    ])}"
    if !alltrue([for mk in cc.member_keys : contains(keys(local.archetype_instances), mk)])
  ]

  # Instance keys to demote to P4 / no page because a composite carries their page.
  demoted_instance_keys = toset(flatten([
    for k, cc in local.composite_resolvable :
    cc.member_keys if try(cc.c.demote_members, false)
  ]))

  # The instance map actually handed to the factory: archetype instances with
  # composite demotions applied, plus the self-service monitors.
  demoted_archetype_instances = {
    for k, inst in local.archetype_instances : k => (
      contains(local.demoted_instance_keys, k)
      ? merge(inst, {
        priority = "P4"
        pages    = false
        notification_profile = contains(local.nonprod_envs, inst.env) ? "nonprod_standard" : (
          inst.domain == "security" ? "security_operational" : "production_baseline"
        )
        summary    = "${inst.summary} (Demoted to informational: a composite monitor carries the page for this condition — see the composite in the same failure domain.)"
        extra_tags = concat(inst.extra_tags, ["demoted_by:composite"])
      })
      : inst
    )
  }

  # Composite definitions in the shape the composite module expects.
  composite_instances = {
    for k, cc in local.composite_resolvable : k => {
      title       = cc.c.title
      description = trimspace(cc.c.description)
      operator    = try(cc.c.operator, "AND")

      member_ids      = [for mk in cc.member_keys : module.coverage_monitors.monitor_ids[mk]]
      member_titles   = [for mk in cc.member_keys : local.archetype_instances[mk].title]
      member_group_by = [for mk in cc.member_keys : join("|", local.archetype_instances[mk].group_by)]
      member_teams    = [for mk in cc.member_keys : local.archetype_instances[mk].team]

      domain = cc.c.domain
      env    = cc.env
      band   = cc.band
      tier   = local.tier_maps.band_strictest_tier[cc.band]
      priority = local.rank_priority[max(
        local.priority_rank[local.prio.matrix[cc.c.impact_class][cc.band]],
        local.priority_rank[local.env_policy[cc.env].priority_ceiling]
      )]
      impact_class       = cc.c.impact_class
      monitoring_profile = cc.band == "critical" ? "critical" : "standard"
      support_model      = local.tiers[local.tier_maps.band_strictest_tier[cc.band]].support_model
      pages = (
        local.env_policy[cc.env].paging_allowed
        && cc.band == "critical"
        && contains(["P1", "P2"], local.rank_priority[max(
          local.priority_rank[local.prio.matrix[cc.c.impact_class][cc.band]],
          local.priority_rank[local.env_policy[cc.env].priority_ceiling]
        )])
      )

      service              = local.slo_catalog[cc.c.slo_id].service
      team                 = cc.c.owner_team
      cc_teams             = try(cc.c.cc_teams, [])
      notification_profile = contains(local.nonprod_envs, cc.env) ? "nonprod_standard" : "production_critical"
      failure_domain       = cc.c.failure_domain

      slo_id      = cc.c.slo_id
      runbook     = cc.c.runbook
      runbook_url = "${local.runbooks.docs_base_url}/${try(local.runbooks.runbooks[cc.c.runbook].source, "${cc.c.runbook}.md")}"
      workflow    = cc.c.workflow
      impact      = "Confirmed impact: every member condition is true simultaneously, which is the evidence threshold this platform requires before paging on a symptom."
      next_action = "Treat as a confirmed incident. The member alerts are the evidence trail; the runbook's remediation section applies directly."

      renotify_interval = 30
      extra_tags        = try(cc.c.release_gate, false) ? ["release_gate:true"] : []
    }
  }
}
