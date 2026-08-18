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

  teams_db   = yamldecode(file("${local.policy_dir}/policy/teams.yaml"))
  teams      = local.teams_db.teams
  prio       = yamldecode(file("${local.policy_dir}/policy/priorities.yaml"))
  notif      = yamldecode(file("${local.policy_dir}/policy/notification_profiles.yaml"))
  workflows  = yamldecode(file("${local.policy_dir}/policy/workflows.yaml")).workflows
  env_policy = yamldecode(file("${local.policy_dir}/policy/environments.yaml")).environments
  domains    = yamldecode(file("${local.policy_dir}/policy/domains.yaml")).domains

  service_docs = {
    for f in fileset("${local.policy_dir}/services", "*.yaml") :
    trimsuffix(f, ".yaml") => yamldecode(file("${local.policy_dir}/services/${f}")).service
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
      members     = lookup(var.oncall_members, handle, [])
      time_zone   = t.business_hours_timezone
      # Ack/escalation timeouts come from the PRIORITY model, not per team —
      # a P1 has the same urgency contract everywhere in the enterprise.
      ack_timeout_minutes        = local.prio.priorities.P1.ack_minutes
      escalation_timeout_minutes = local.prio.priorities.P1.escalate_minutes
      rotation_days              = var.rotation_days
      business_hours_only        = false
    }
  }
  schedule_effective_date = var.schedule_effective_date
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
      profile               = v.profile
      priority              = v.prio
      pages                 = v.pages
      teams                 = v.teams
      page                  = v.pages
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
# RBAC — four roles plus one scoped security role (see ADR-009)
# Permissions are resolved by NAME against the live permission catalog at plan
# time, so a typo fails the plan instead of silently granting nothing.
# =============================================================================
module "rbac" {
  source = "../../modules/rbac"
  count  = var.manage_rbac ? 1 : 0

  roles = {
    datadog-platform-admin = {
      name = "Datadog Platform Admin"
      permissions = [
        "org_management", "api_keys_write", "user_access_manage",
        "monitors_write", "monitors_downtime", "slos_write",
        "dashboards_write", "notebooks_write", "workflows_write",
        "monitor_config_policy_write",
      ]
    }
    observability-engineer = {
      name = "Observability Engineer"
      permissions = [
        "monitors_write", "monitors_downtime", "slos_write", "slos_corrections",
        "dashboards_write", "notebooks_write", "workflows_write",
        "incident_settings_write",
      ]
    }
    engineering-user = {
      name = "Engineering User"
      permissions = [
        "monitors_downtime", "incident_write", "workflows_run", "notebooks_write",
      ]
    }
    observability-read-only = {
      name        = "Observability Read Only"
      permissions = []
    }
    security-engineer = {
      name = "Security Engineer (scoped)"
      permissions = [
        "security_monitoring_rules_write", "security_monitoring_signals_write",
        "incident_write", "workflows_run",
      ]
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
      roles = ["observability-read-only"]
    }
  }
}

# =============================================================================
# SERVICE CATALOG — ownership inside Datadog, generated from the registry and
# from inventory discovery. Never hand-edited in the UI.
# =============================================================================
module "service_catalog" {
  source = "../../modules/service_catalog"
  services = merge(
    {
      for name, s in local.service_docs : name => {
        team               = s.team
        owner_email        = local.teams[s.team].email
        description        = s.description
        tier               = s.tier
        domain             = local.domains[try(local.archetype_domain_for[s.service_archetype], "application")].platform_tag
        monitoring_profile = local.tier_profile[s.tier]
        env                = "prod"
        links              = try(s.links, [])
      }
    },
    var.services,
  )
}

locals {
  tier_profile = {
    tier0 = "critical"
    tier1 = "critical"
    tier2 = "standard"
    tier3 = "observe_only"
  }
  archetype_domain_for = {
    api                     = "api"
    web                     = "application"
    worker                  = "application"
    event_consumer          = "messaging"
    batch_job               = "integration"
    scheduled_job           = "integration"
    integration_flow        = "integration"
    saas_dependency         = "saas"
    external_endpoint       = "saas"
    platform_service        = "platform"
    datastore               = "database"
    infrastructure_resource = "infrastructure"
  }
}
