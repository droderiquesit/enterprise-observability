locals {
  policy_dir = "${path.module}/../../platform/policy"
  teams_db   = yamldecode(file("${local.policy_dir}/teams.yaml")).teams
  routing    = yamldecode(file("${local.policy_dir}/routing.yaml"))
  workflows  = yamldecode(file("${local.policy_dir}/workflows.yaml")).workflows
}

# --- Teams + On-Call ---------------------------------------------------------
module "teams" {
  source = "../../modules/team_oncall"
  teams = {
    for handle, t in local.teams_db : handle => {
      name                       = t.name
      description                = "Owns domains: ${join(", ", t.domains_owned)}. Escalates to ${t.escalation_to}."
      members                    = lookup(var.oncall_members, handle, [])
      ack_timeout_minutes        = local.routing.severities.sev2.ack_timeout_minutes
      escalation_timeout_minutes = local.routing.severities.sev2.escalation_timeout_minutes
    }
  }
}

# --- Central tag-based routing ----------------------------------------------
module "notification_rules" {
  source = "../../modules/notification_rules"
  teams = {
    for handle, t in local.teams_db : handle => { teams_channel = t.teams_channel }
  }
  severities = {
    for sev, s in local.routing.severities : sev => {
      pages       = s.pages
      snow_handle = s.snow_record == "none" ? "" : trimprefix(local.routing.destinations.servicenow[s.snow_record], "@")
    } if sev != "informational" # informational never routes
  }
  exec_channel = trimprefix(local.routing.destinations.teams_exec_channel, "@")
}

# --- Workflow Automation (adopted registry; see ADR-008) ---------------------
module "workflows" {
  source = "../../modules/workflow_automation"
  workflows = {
    for ref, w in local.workflows : ref => {
      name        = w.name
      description = "Standard ${w.kind} automation for archetype monitors (automation_ref:${ref})."
      kind        = w.kind
      team        = w.team
      approval    = w.approval
      read_only   = w.read_only
      spec_json = jsonencode({
        triggers = [{ monitorTrigger = { rateLimit = { count = 100, interval = "3600s" } }, startStepNames = ["fetch_monitor"] }]
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

import {
  for_each = var.adopt_existing_workflows ? { for ref, w in local.workflows : ref => w.id } : {}
  to       = module.workflows.datadog_workflow_automation.this[each.key]
  id       = each.value
}

# --- Scheduled maintenance ---------------------------------------------------
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
  }
}

# --- RBAC (ADR-009) ----------------------------------------------------------
module "rbac" {
  source = "../../modules/rbac"
  count  = var.manage_rbac ? 1 : 0

  roles = {
    platform-administrator = {
      name = "Observability Platform Administrator"
      permissions = [
        "org_management", "api_keys_write", "user_access_manage",
        "monitors_write", "monitors_downtime", "slos_write",
        "dashboards_write", "notebooks_write", "workflows_write",
      ]
    }
    observability-maintainer = {
      name = "Observability Maintainer"
      permissions = [
        "monitors_write", "monitors_downtime", "slos_write", "slos_corrections",
        "dashboards_write", "notebooks_write", "workflows_write", "incident_settings_write",
      ]
    }
    responder = {
      name = "Incident Responder"
      permissions = [
        "monitors_downtime", "incident_write", "workflows_run", "notebooks_write",
      ]
    }
    read-only = {
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
      roles = ["observability-maintainer"]
    }
    svc-observability-coverage = {
      email = "svc-observability-coverage@acme.example"
      name  = "Coverage reporting (read-only)"
      roles = ["read-only"]
    }
  }
}

# --- Service catalog (generated from inventory) ------------------------------
module "service_catalog" {
  source   = "../../modules/service_catalog"
  services = var.services
}
