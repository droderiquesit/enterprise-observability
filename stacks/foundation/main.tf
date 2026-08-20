# =============================================================================
# FOUNDATION STACK
#
# Everything an alert needs to REACH someone: teams, on-call schedules and
# escalation policies, the central tag-based routing matrix, workflow
# automation, maintenance windows, RBAC, dashboards, and the service catalog.
#
# Applied BEFORE the coverage stack — a monitor that fires into a routing void
# is worse than no monitor, because it creates the appearance of coverage.
# =============================================================================

locals {
  policy_dir = "${path.module}/../../platform"

  teams_db  = yamldecode(file("${local.policy_dir}/policy/teams.yaml"))
  teams     = local.teams_db.teams
  prio      = yamldecode(file("${local.policy_dir}/policy/priorities.yaml"))
  notif     = yamldecode(file("${local.policy_dir}/policy/notification_profiles.yaml"))
  workflows = yamldecode(file("${local.policy_dir}/policy/workflows.yaml")).workflows
  domains   = yamldecode(file("${local.policy_dir}/policy/domains.yaml")).domains
  tiers     = yamldecode(file("${local.policy_dir}/policy/tiers.yaml")).tiers

  # service_archetype → domain, straight from the service-archetype catalog
  # (previously re-typed by hand here and in stacks/coverage).
  service_archetype_domain = {
    for k, v in yamldecode(file("${local.policy_dir}/policy/service_archetypes.yaml")).service_archetypes :
    k => v.domain
  }

  tiers_doc = yamldecode(file("${local.policy_dir}/policy/tiers.yaml"))

  # The SUPERSEDED registration format. Still read so that a branch written
  # against platform/services/ keeps working (platform/services/README.md); it
  # ships empty, so this is normally {}. Anything found here is emitted as a
  # v2.2 service definition exactly as before — the entity model does not
  # rewrite objects nobody migrated.
  legacy_service_docs = {
    for f in fileset("${local.policy_dir}/services", "*.yaml") :
    trimsuffix(f, ".yaml") => yamldecode(file("${local.policy_dir}/services/${f}")).service
  }

  # The entity registry — every kind, not just services (§5).
  entity_docs = {
    for f in fileset("${local.policy_dir}/entities", "*.yaml") :
    trimsuffix(f, ".yaml") => yamldecode(file("${local.policy_dir}/entities/${f}")).entity
  }
}

# =============================================================================
# TEAMS + DATADOG ON-CALL
# =============================================================================
module "teams" {
  source = "../../modules/team_oncall"
  teams = {
    for handle, t in local.teams : handle => {
      name        = t.name
      description = "Owns ${length(t.domains_owned) > 0 ? join(", ", t.domains_owned) : "no domains directly"}. Escalates to ${t.escalation_to}."
      # Rosters come from the IdP/SCIM sync and are frequently empty at
      # bootstrap. That is fine: the module builds the full on-call structure
      # regardless and holds an UNASSIGNED schedule position until people
      # exist. Nobody is ever invented to fill a rotation.
      members           = lookup(var.oncall_members, handle, [])
      secondary_members = lookup(var.oncall_secondary_members, handle, [])
      time_zone         = t.business_hours_timezone
      # Ack/escalation timeouts come from the PRIORITY model, not per team —
      # a P1 has the same urgency contract everywhere in the enterprise. These
      # stay at P1 values because they describe the PAGING path, and the only
      # things that page are P1 and confirmed-impact P2 (priorities.yaml
      # paging_rule). P2's own 10/20 ack contract is enforced by the
      # routing-rule urgency split inside the module (high vs low urgency), not
      # by a second escalation policy per priority.
      ack_timeout_minutes        = local.prio.priorities.P1.ack_minutes
      escalation_timeout_minutes = local.prio.priorities.P1.escalate_minutes
      rotation_days              = var.rotation_days
      # Read the team's own policy when teams.yaml declares one; otherwise
      # 24x7. No team declares `business_hours_only` today, so every rotation
      # is round-the-clock — but a team that adds the key gets the restriction
      # without a code change here.
      business_hours_only = try(t.business_hours_only, false)
    }
  }
  schedule_effective_date = var.schedule_effective_date
  create_schedules        = var.create_oncall_schedules

  # Escalation step 4 is the incident commander / platform leadership team.
  # teams.yaml names `platform-leadership` and `security-leadership` as
  # escalation targets, but neither exists as a Datadog Team yet, so there is
  # no ID to point at. Empty string = the module falls back to the owning team
  # for step 4; wire the real ID here the moment a leadership team handle is
  # provisioned.
  leadership_team_id = ""
}

# =============================================================================
# CENTRAL TAG-BASED ROUTING
#
# One flattened row per (notification_profile × priority); the module
# multiplies by teams. Adding a team adds routing automatically. Changing a
# destination touches zero monitors.
# =============================================================================
locals {
  # Flatten notification_profiles.yaml → routing rows.
  #
  # A row is keyed (profile × priority × pages) because paging is a SEPARATE
  # decision from priority: a P2 raised by a symptom archetype notifies and
  # tickets, while a P2 raised by an SLO burn or a composite also pages. The
  # monitor carries `pages:true|false`, so the routing filter reads it directly
  # and the on-call handle is attached only where it belongs.
  routing_variants = flatten([
    for pname, prof in local.notif.notification_profiles : [
      for prio, route in prof.routes : [
        # A route that can page produces BOTH variants; one that cannot produces
        # only the non-paging variant.
        for pages in try(route.page, false) ? [true, false] : [false] : {
          profile = pname
          prio    = prio
          route   = route
          pages   = pages
          teams   = try(tolist(prof.applies_to_teams), keys(local.teams))
        }
      ]
    ] if try(prof.provisioned, true)
  ])

  routing_rows = {
    for v in local.routing_variants : "${v.profile}.${v.prio}.${v.pages}" => {
      profile  = v.profile
      priority = v.prio
      pages    = v.pages
      teams    = v.teams
      page     = v.pages
      # ONE non-production channel, deliberately — not a QA/stage split.
      #
      # A routing row is keyed (profile × priority × pages) and the notification
      # rule it produces filters on exactly those tags plus `team`. There is no
      # `env` tag in that filter, and there is no environment on the row: the
      # `nonprod_standard` profile is selected for `env in [qa, stage]`
      # (notification_profiles.yaml), so ONE rule already covers both. Deriving
      # "-qa" vs "-stage" here is not possible — the row genuinely does not know
      # which environment fired.
      #
      # environments.yaml does carry `teams_channel_suffix: -qa | -stage | ""`,
      # so a real per-environment split IS expressible, but it means adding an
      # environment dimension to routing_variants, adding `env:<e>` to the
      # notification-rule filter tags, and doubling the non-prod rule count.
      # That is a restructure of the routing matrix, not a suffix fix, and it is
      # deliberately not done here.
      #
      # It is also the right answer operationally: QA and stage are both
      # ticket-only, business-hours, non-paging, priority-ceiling P3
      # environments with the same audience. Splitting them buys two quieter
      # channels nobody watches instead of one that gets read. What mattered was
      # keeping non-prod OUT of the production channels, and the suffix (now
      # applied to both the normal and the low-noise arm — see
      # modules/notification_rules/main.tf) does exactly that.
      channel_suffix        = startswith(v.profile, "nonprod") ? "-nonprod" : ""
      use_low_noise_channel = contains(["low_noise_channel", "security_low_noise"], try(v.route.teams, ""))
      cc_owner_team         = try(v.route.cc_owner_team, false)
      servicenow_handle = (
        try(v.route.servicenow, "none") == "incident_p1" ? local.notif.destinations.servicenow.incident_p1 :
        try(v.route.servicenow, "none") == "incident_p2" ? local.notif.destinations.servicenow.incident_p2 :
        startswith(try(v.route.servicenow, "none"), "task_p3") ? local.notif.destinations.servicenow.task_p3 :
        ""
      )
      extra_channels = [
        for c in try(v.route.extra_channels, []) :
        c == "exec_channel" ? local.notif.destinations.exec_channel :
        c == "major_incident_channel" ? local.notif.destinations.major_incident_channel :
        local.notif.destinations.release_channel
      ]
    }
  }
}

module "notification_rules" {
  source = "../../modules/notification_rules"
  teams = {
    for handle, t in local.teams : handle => {
      channel           = t.teams_channel
      low_noise_channel = t.teams_low_noise_channel
    }
  }
  routes = local.routing_rows
}

# =============================================================================
# WORKFLOW AUTOMATION
#
# Every monitor names a workflow. The module enforces the safety contract:
# fully_automatic requires a bounded, reversible blast radius; anything that
# can lose data or replay business messages requires change-board approval.
# =============================================================================
# The org's plan caps the number of Workflow Automation workflows (observed:
# ~20). workflow_budget instantiates only the first N of this explicit
# priority order — diagnostics attached to alert messages first, then
# incident and change automation; remediation workflows (manual-approval
# gated anyway, per the safety contract) and secondary ticket workflows
# defer until the plan allows. 0 = no budget, instantiate everything.
locals {
  workflow_priority = [
    # monitors reference these in their AUTOMATED DIAGNOSTICS message line
    "diag-api-health", "diag-app-health", "diag-azure-resource",
    "diag-batch-job", "diag-data-pipeline", "diag-database",
    "diag-dependency", "diag-external-endpoint", "diag-host",
    "diag-k8s-workload", "diag-messaging", "diag-network",
    "diag-security-control", "diag-vmware",
    # incident + change automation
    "auto-major-incident", "auto-enrich-change", "auto-ticket-sustained",
    "auto-capacity-ticket",
    # deferred under a tight budget
    "auto-cert-renewal-ticket", "auto-compliance-ticket", "auto-drift-ticket",
    "auto-finops-review",
    "remediate-clear-dlq", "remediate-recycle-app-pool", "remediate-rerun-job",
    "remediate-restart-workload", "remediate-scale-workload",
  ]

  # Single comprehension, not `budget == 0 ? all : {...}` — a ternary between
  # a yamldecode object and a map trips inconsistent-conditional-type errors.
  workflow_selected_refs = slice(local.workflow_priority, 0,
  min(var.workflow_budget, length(local.workflow_priority)))

  workflows_selected = {
    for ref, w in local.workflows : ref => w
    if var.workflow_budget == 0 || contains(local.workflow_selected_refs, ref)
  }
}

# Every catalog workflow must appear in the priority order, or a budget would
# silently orphan it from selection.
check "workflow_priority_is_complete" {
  assert {
    condition     = toset(local.workflow_priority) == toset(keys(local.workflows))
    error_message = "workflow_priority must list exactly the keys of platform/policy/workflows.yaml."
  }
}

module "workflows" {
  source = "../../modules/workflow_automation"
  workflows = {
    for ref, w in local.workflows_selected : ref => {
      name                 = w.name
      description          = "${w.class} automation attached to monitors via automation_ref:${ref}. Actions: ${join(", ", w.actions)}."
      kind                 = w.class
      team                 = w.team
      approval             = w.approval
      read_only            = w.read_only
      reversible           = try(w.reversible, true)
      max_actions_per_hour = try(w.max_actions_per_hour, 0)
      spec_json = jsonencode({
        triggers = [{
          monitorTrigger = { rateLimit = { count = try(w.max_actions_per_hour, 100), interval = "3600s" } }
          startStepNames = ["fetch_monitor"]
        }]
        steps = [{
          name          = "fetch_monitor"
          actionId      = "com.datadoghq.dd.monitor.getMonitor"
          parameters    = [{ name = "monitorId", value = "{{ Trigger.monitorId }}" }]
          outboundEdges = []
        }]
      })
    }
  }
}

# =============================================================================
# MAINTENANCE WINDOWS
# Tag-scoped and recurring. Suppression is native (Datadog downtime) and the
# correlation engine additionally tags anything arriving inside a window.
# =============================================================================
module "downtimes" {
  source = "../../modules/downtime"
  windows = {
    data-platform-weekly = {
      scope        = "env:prod AND team:data-engineering"
      monitor_tags = ["managed_by:terraform", "domain:data"]
      rrule        = "FREQ=WEEKLY;INTERVAL=1;BYDAY=SU"
      start        = "2026-09-06T02:00:00"
      duration     = "4h"
      message      = "Weekly data-platform maintenance window — pipeline and warehouse alerts suppressed by policy."
    }
    nonprod-nightly-quiet = {
      scope        = "env:qa"
      monitor_tags = ["managed_by:terraform", "env:qa"]
      rrule        = "FREQ=DAILY;INTERVAL=1"
      start        = "2026-09-01T19:00:00"
      duration     = "13h"
      message      = "QA is business-hours only by environment policy; overnight signals are recorded, not notified."
    }
  }
}

# =============================================================================
# RBAC — EXACTLY FOUR ROLES (ADR-009)
#
# Permissions are resolved by NAME against the live permission catalog at plan
# time, so a typo fails the plan instead of silently granting nothing.
#
# THE FOUR-ROLE MODEL
#
#   platform-admin          runs Datadog itself: org settings, keys, RBAC,
#                           integrations, On-Call administration.
#   observability-engineer  builds and owns detection: monitors, SLOs,
#                           notebooks/runbooks, dashboards, workflows.
#   incident-responder      works incidents: investigate, acknowledge, mute,
#                           resolve, run approved workflows. Absorbs what used
#                           to be a separate security-engineer role.
#   viewer-auditor          reads everything, changes nothing.
#
# WHY THERE ARE NO PER-TEAM, PER-SERVICE OR PER-ENVIRONMENT ROLES
#
# A role answers "what KIND of action may this person take?". It is the wrong
# instrument for "on WHICH objects?" — that is scope, and scope in Datadog comes
# from three other mechanisms this platform already uses:
#
#   * Datadog Teams          (modules/team_oncall) — membership, ownership and
#                            the on-call rotation.
#   * ownership tags         `team:<handle>` on every monitor, SLO, dashboard
#                            and service, emitted by modules/monitor_factory.
#   * datadog_restriction_policy — the actual per-object write fence, applied
#                            to a resource and referencing a Team.
#
# Encoding scope in roles instead multiplies them: 8 teams × 4 environments ×
# 2 access levels is 64 roles that all say "monitors_write" and drift apart the
# moment one is edited by hand. It also breaks the moment somebody is on two
# teams, which is the normal case for SRE. Four verbs plus tag-driven scope
# stays correct as the estate grows; a role matrix does not.
#
# The removed roles and where their duties went:
#   engineering-user   → incident-responder (identical intent, honest name)
#   security-engineer  → incident-responder holds the signal/rule permissions;
#                        the SECURITY SCOPE was never enforced by that role
#                        anyway — it comes from team:security ownership and the
#                        security_operational routing profile.
# =============================================================================
module "rbac" {
  source = "../../modules/rbac"
  count  = var.manage_rbac ? 1 : 0

  roles = {
    # Full Datadog, RBAC, integration and On-Call administration.
    platform-admin = {
      name = "Platform Admin"
      permissions = [
        "org_management", "api_keys_write", "user_access_manage",
        "monitors_write", "monitors_downtime", "slos_write",
        "dashboards_write", "notebooks_write", "workflows_write",
        "monitor_config_policy_write", "incident_settings_write",
        "security_monitoring_rules_write",
      ]
    }

    # Manage monitors, SLOs, runbooks (notebooks), dashboards, workflows and
    # notification rules. No org, key or user administration.
    observability-engineer = {
      name = "Observability Engineer"
      permissions = [
        "monitors_write", "monitors_downtime", "slos_write", "slos_corrections",
        "dashboards_write", "notebooks_write", "workflows_write",
        "monitor_config_policy_write",
      ]
    }

    # Investigate, acknowledge, resolve, and execute already-approved
    # workflows. Cannot author new detection.
    incident-responder = {
      name = "Incident Responder"
      permissions = [
        "monitors_downtime", "incident_write", "incident_settings_write",
        "workflows_run", "notebooks_write",
        "security_monitoring_signals_write",
      ]
    }

    # Read-only. The permission list is INTENTIONALLY EMPTY: Datadog grants
    # baseline read access to every role in the org, so a role with no
    # permissions is exactly "can see everything, can change nothing". Adding
    # a "*_read" permission here would not widen anything — it would only
    # imply, falsely, that read had to be granted.
    viewer-auditor = {
      name        = "Viewer / Auditor"
      permissions = []
    }
  }

  service_accounts = {
    svc-observability-terraform = {
      email = "svc-observability-terraform@acme.example"
      name  = "Observability Terraform (CI deploys only)"
      roles = ["observability-engineer"]
    }
    svc-observability-coverage = {
      email = "svc-observability-coverage@acme.example"
      name  = "Coverage reporting (read-only)"
      roles = ["viewer-auditor"]
    }
  }
}

# =============================================================================
# SERVICE CATALOG — ownership inside Datadog, generated from the registry and
# from inventory discovery. Never hand-edited in the UI.
# =============================================================================
# -----------------------------------------------------------------------------
# SERVICE-LEVEL RUNBOOK RELATIONSHIPS
#
# The monitor→runbook binding is the monitor's native `assets` field (see
# modules/monitor_factory). This is the complementary SERVICE→runbook
# relationship: Datadog's service-definition schema has a first-class
# `type: runbook` link, so the catalog entry for a service points at the same
# published notebooks a responder would reach from any of its monitors.
#
# Both point at the notebook, never at a repository file. Scope is the
# archetype packs the service's archetype actually deploys, so a service links
# to the runbooks that can actually fire for it and nothing else.
# -----------------------------------------------------------------------------
locals {
  service_archetypes_doc = yamldecode(file("${local.policy_dir}/policy/service_archetypes.yaml"))
  runbook_registry       = yamldecode(file("${local.policy_dir}/policy/runbooks.yaml"))

  # service_archetype → the runbook ids reachable through its packs.
  runbooks_for_archetype = {
    for sa, v in local.service_archetypes_doc.service_archetypes : sa => distinct(flatten([
      for pack in v.packs : [
        for arch in try(local.service_archetypes_doc.packs[pack].archetypes, []) : arch
      ]
    ]))
  }

  # Keyed by ARCHETYPE rather than by service name, because both registries
  # (platform/services/ and platform/entities/) need the same lookup and the
  # entity registry contains kinds — a queue, a system — that have no archetype
  # at all.
  archetype_runbook_links = {
    for sa, rids in local.runbooks_for_archetype : sa => [
      for rid in rids : {
        name = "Runbook: ${local.runbook_registry.runbooks[rid].title}"
        type = "runbook"
        url  = "${local.runbook_registry.notebook_base_url}/${local.runbook_registry.runbooks[rid].id}"
      }
      # Only published runbooks: an entry without an id has no notebook to
      # point at, and a catalog link to nothing is worse than no link.
      if try(local.runbook_registry.runbooks[rid].id, null) != null
    ]
  }
}

module "service_catalog" {
  source = "../../modules/service_catalog"
  # v2.2 service definitions, for the DISCOVERED population and for anything
  # still registered the superseded way.
  #
  # A v2.2 service definition and a v3 entity with the same name are the SAME
  # Datadog catalog object, so a name managed by modules/catalog_entity is
  # excluded here — otherwise two Terraform resources would fight over one
  # entity on every apply. Discovery is deliberately the loser of that
  # exclusion: a declared entity carries reviewed intent and a typed kind, a
  # discovered one carries neither.
  services = {
    for name, s in merge(
      {
        for name, s in local.legacy_service_docs : name => {
          team               = s.team
          owner_email        = local.teams[s.team].email
          description        = s.description
          tier               = s.tier
          domain             = local.domains[try(local.service_archetype_domain[s.service_archetype], "application")].platform_tag
          monitoring_profile = local.tiers[s.tier].monitoring_profile
          env                = "prod"
          links              = concat(try(s.links, []), try(local.archetype_runbook_links[s.service_archetype], []))
        }
      },
      var.services,
    ) : name => s
    if !contains(keys(local.entity_docs), name)
  }
}

# =============================================================================
# SOFTWARE CATALOG — TYPED ENTITIES (§5, §10)
#
# Kind resolution, tag derivation and the entity graph happen HERE, from
# platform/policy/entity_kinds.yaml. modules/catalog_entity renders and
# enforces; it decides nothing. tools/entity_resolver.py performs the same
# resolution in Python for the tests, the census and anything that needs to
# answer "what would this entity look like?" without an apply — both read the
# one policy file, neither reads the other.
# =============================================================================
locals {
  entity_kinds_doc  = yamldecode(file("${local.policy_dir}/policy/entity_kinds.yaml"))
  entity_kind_spec  = local.entity_kinds_doc.entity_kinds
  kind_by_archetype = local.entity_kinds_doc.kind_by_service_archetype

  # `kind:` when declared, else the archetype's kind. The map is total over the
  # archetype vocabulary, so this never guesses; an archetype that maps to null
  # (infrastructure_resource — a VM is a host, not a catalog entity) is
  # rejected by tools/validate_policy.py before it reaches Terraform.
  entity_kind = {
    for name, e in local.entity_docs : name =>
    try(e.kind, local.kind_by_archetype[e.service_archetype])
  }

  # name → "kind:name". A name that is not registered resolves to `service:` —
  # the honest default for something outside our catalog (entra-id, warehouse).
  entity_ref = {
    for name, k in local.entity_kind : name =>
    "${coalesce(try(local.entity_kind_spec[k].datadog_kind, null), "service")}:${name}"
  }

  # Membership is declared once, on the system. `componentOf` on each member is
  # DERIVED from it here, so the reverse edge is never maintained by hand.
  system_members = {
    for name, e in local.entity_docs : name => [
      for c in try(e.components, []) : element(split(":", c), length(split(":", c)) - 1)
    ] if try(local.entity_kind_spec[local.entity_kind[name]].spec_components, false)
  }

  entity_resolved = {
    for name, e in local.entity_docs : name => {
      kind    = local.entity_kind[name]
      spec    = local.entity_kind_spec[local.entity_kind[name]]
      domain  = try(e.domain, local.service_archetype_domain[e.service_archetype], "platform")
      profile = try(e.monitoring_profile, local.tiers[e.criticality].monitoring_profile)
      slo     = try(e.slo.profile, local.tiers[e.criticality].slo.scope)
      oncall  = try(e.oncall.team, e.team)
    }
  }

  entity_tags = {
    for name, e in local.entity_docs : name => sort(concat(
      [
        "entity_kind:${local.entity_resolved[name].kind}",
        "env:${try(e.env, "prod")}",
        "team:${e.team}",
        "tier:${e.criticality}",
        "criticality:${e.criticality}",
        "domain:${local.entity_resolved[name].domain}",
        "monitoring_profile:${local.entity_resolved[name].profile}",
        "alert_band:${local.tiers_doc.profile_to_band[local.entity_resolved[name].profile]}",
        "slo_profile:${local.entity_resolved[name].slo}",
        "managed_by:terraform",
      ],
      # Emitted only where the telemetry is genuinely keyed by `service`.
      try(local.entity_resolved[name].spec.performance_data, false) ? ["service:${name}"] : [],
      try(e.service_archetype, null) == null ? [] : ["service_archetype:${e.service_archetype}"],
      try(e.platform, null) == null ? [] : ["platform:${e.platform}"],
      try(e.region, null) == null ? [] : ["region:${e.region}"],
      try(e.compliance_scope, null) == null ? [] : ["compliance_scope:${e.compliance_scope}"],
      local.entity_resolved[name].oncall == e.team ? [] : ["oncall_team:${local.entity_resolved[name].oncall}"],
    ))
  }
}

module "catalog_entity" {
  source               = "../../modules/catalog_entity"
  datadog_entity_kinds = local.entity_kinds_doc.datadog_entity_kinds

  entities = {
    for name, e in local.entity_docs : name => {
      emits        = local.entity_resolved[name].spec.emits
      datadog_kind = try(local.entity_resolved[name].spec.datadog_kind, null)

      display_name = try(e.display_name, null)
      description  = e.description
      lifecycle    = try(e.lifecycle, "production")
      tier         = e.criticality
      # `spec.type` is the technology, except where the kind forces it —
      # frontend_app must present as a `service` of type `web` because the v3
      # union has no UI kind (platform/policy/entity_kinds.yaml).
      spec_type = try(local.entity_resolved[name].spec.spec_type_override, try(e.platform, null))
      tags      = local.entity_tags[name]

      team        = e.team
      oncall_team = local.entity_resolved[name].oncall
      contacts = [{
        name    = "${e.team} email"
        type    = "email"
        contact = local.teams[e.team].email
      }]

      # Edges are emitted only for the kinds whose v3 spec can carry them; the
      # schema rejects the others, and this is the second line of defence.
      depends_on = try(local.entity_resolved[name].spec.spec_depends_on, false) ? sort([
        for d in try(e.dependencies, []) :
        length(split(":", d)) > 1 ? d : try(local.entity_ref[d], "service:${d}")
      ]) : []
      components = try(local.entity_resolved[name].spec.spec_components, false) ? sort([
        for c in try(e.components, []) :
        length(split(":", c)) > 1 ? c : try(local.entity_ref[c], "service:${c}")
      ]) : []
      component_of = try(local.entity_resolved[name].spec.spec_component_of, false) ? sort([
        for sysname, members in local.system_members : "system:${sysname}" if contains(members, name)
      ]) : []

      performance_data_tags = try(local.entity_resolved[name].spec.performance_data, false) ? ["service:${name}"] : []

      # Declared links plus the runbooks its packs can actually fire. A kind
      # with no archetype (a queue, a system) gets its declared links only —
      # there are no packs to derive from.
      links = concat(
        try(e.links, []),
        try(local.archetype_runbook_links[e.service_archetype], []),
      )
    }
  }
}

