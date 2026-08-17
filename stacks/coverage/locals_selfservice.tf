# ---------------------------------------------------------------------------
# Self-service monitor requests: platform/requests/*.yaml → monitor instances.
# CI (tools/validate_manifests.py) rejects non-compliant manifests before this
# code ever sees them; the factory's preconditions are the second line of
# defense. Teams never write Terraform.
# ---------------------------------------------------------------------------

locals {
  requests_dir = "${path.module}/../../platform/requests"
  request_docs = {
    for f in fileset(local.requests_dir, "*.yaml") :
    trimsuffix(f, ".yaml") => yamldecode(file("${local.requests_dir}/${f}"))
  }

  request_instances = {
    for id, r in local.request_docs :
    "request.${r.env}.${id}" => {
      archetype          = "self-service"
      title              = r.title
      domain             = r.domain
      env                = r.env
      monitor_type       = r.monitor_type
      query              = r.query
      thresholds         = { for tk, tv in r.thresholds : tk => tv }
      group_by           = try(r.group_by, [])
      severity           = local.tiers[r.criticality].severity_map[r.severity_class]
      priority           = local.tiers[r.criticality].priority_map[local.tiers[r.criticality].severity_map[r.severity_class]]
      team               = r.team
      owner              = try(r.owner, r.team)
      service            = r.service
      slo_id             = r.slo_id
      slo_url            = ""
      runbook_name       = r.runbook
      runbook_url        = try(format("%s/%d", local.runbooks.notebook_base_url, local.runbooks.notebooks[r.runbook].id), "")
      workflow           = r.workflow
      failure_domain     = try(r.failure_domain, "${r.service}")
      criticality        = r.criticality
      monitoring_profile = try(r.monitoring_profile, "standard")
      platform           = local.domains[r.domain].platform_tag
      resource_type      = length(try(r.group_by, [])) > 0 ? r.group_by[0] : "service"
      region             = try(r.region, "global")
      routing_rule       = local.routing.severities[local.tiers[r.criticality].severity_map[r.severity_class]].routing_rule
      snow_record        = local.routing.severities[local.tiers[r.criticality].severity_map[r.severity_class]].snow_record
      support_model      = local.tiers[r.criticality].support_model
      pages              = local.routing.severities[local.tiers[r.criticality].severity_map[r.severity_class]].pages && local.env_policy[r.env].paging_allowed
      summary            = try(r.summary, r.title)
      impact             = try(r.impact, "")

      notify_no_data      = try(r.notify_no_data, null)
      no_data_timeframe   = null
      evaluation_delay    = null
      new_group_delay     = null
      renotify_interval   = null
      require_full_window = null
      timeout_h           = null
      extra_tags          = []
      managed_source      = "self_service"
      request_id          = id
    }
  }
}
