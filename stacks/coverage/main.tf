locals {
  monitor_defaults = {
    evaluation_delay    = local.global.monitor_defaults.evaluation_delay
    new_group_delay     = local.global.monitor_defaults.new_group_delay
    renotify_interval   = local.global.monitor_defaults.renotify_interval
    renotify_statuses   = local.global.monitor_defaults.renotify_statuses
    notify_no_data      = local.global.monitor_defaults.notify_no_data
    no_data_timeframe   = local.global.monitor_defaults.no_data_timeframe
    require_full_window = local.global.monitor_defaults.require_full_window
    notify_audit        = local.global.monitor_defaults.notify_audit
    include_tags        = local.global.monitor_defaults.include_tags
    timeout_h           = local.global.monitor_defaults.timeout_h
  }

  cardinality_guardrails = {
    max_group_by_keys    = local.global.cardinality.max_group_by_keys
    forbidden_group_keys = local.global.cardinality.forbidden_group_keys
  }
}

# Baseline coverage packs (all domains) + validated self-service requests.
module "coverage_monitors" {
  source       = "../../modules/monitor_factory"
  instances    = merge(local.archetype_instances, local.request_instances)
  defaults     = local.monitor_defaults
  cardinality  = local.cardinality_guardrails
  api_validate = var.datadog_validate
}
