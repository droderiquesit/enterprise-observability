# =============================================================================
# COVERAGE STACK
#
# Dependency order is deliberate and acyclic:
#
#   coverage_monitors  (archetype packs + self-service)
#         ↓ monitor IDs
#   slos               (monitor-type SLO membership is rebuilt from them)
#         ↓ SLO IDs
#   burn_monitors      (multi-window burn-rate alerts — the primary page)
#
#   composites         (reference member monitor IDs from coverage_monitors)
# =============================================================================

locals {
  monitor_defaults = {
    evaluation_delay     = local.global.monitor_defaults.evaluation_delay
    new_group_delay      = local.global.monitor_defaults.new_group_delay
    renotify_interval    = local.global.monitor_defaults.renotify_interval
    renotify_statuses    = local.global.monitor_defaults.renotify_statuses
    renotify_occurrences = local.global.monitor_defaults.renotify_occurrences
    notify_no_data       = local.global.monitor_defaults.notify_no_data
    no_data_timeframe    = local.global.monitor_defaults.no_data_timeframe
    require_full_window  = local.global.monitor_defaults.require_full_window
    notify_audit         = local.global.monitor_defaults.notify_audit
    include_tags         = local.global.monitor_defaults.include_tags
    # Auto-resolve: the org-wide floor plus the bounds the factory enforces.
    # Per-monitor windows are resolved in locals_policy.tf → auto_resolve.
    timeout_h              = local.global.monitor_defaults.timeout_h
    auto_resolve_min_hours = local.auto_resolve.min_hours
    auto_resolve_max_hours = local.auto_resolve.max_hours
  }

  cardinality_guardrails = {
    max_group_by_keys    = local.global.cardinality.max_group_by_keys
    forbidden_group_keys = local.global.cardinality.forbidden_group_keys
  }

  # Everything the first factory pass renders.
  primary_instances = merge(
    local.demoted_archetype_instances,
    local.custom_instances,
  )

  total_managed_monitors = (
    length(local.primary_instances)
    + length(local.burn_instances)
    + length(local.composite_instances)
  )
}

# --- 1. Archetype packs + self-service monitors ------------------------------
module "coverage_monitors" {
  source       = "../../modules/monitor_factory"
  instances    = local.primary_instances
  defaults     = local.monitor_defaults
  cardinality  = local.cardinality_guardrails
  api_validate = var.datadog_validate
}

# --- 2. Burn-rate monitors (depend on SLO IDs from module.slos) --------------
module "burn_monitors" {
  source       = "../../modules/monitor_factory"
  instances    = local.burn_instances
  defaults     = local.monitor_defaults
  cardinality  = local.cardinality_guardrails
  api_validate = var.datadog_validate
}

# --- 3. Composites (depend on member monitor IDs) ----------------------------
module "composites" {
  source      = "../../modules/composite_monitor"
  composites  = local.composite_instances
  max_members = local.composites_budget.max_members_per_composite
  defaults = {
    renotify_statuses      = local.monitor_defaults.renotify_statuses
    renotify_occurrences   = local.monitor_defaults.renotify_occurrences
    require_full_window    = local.monitor_defaults.require_full_window
    notify_audit           = local.monitor_defaults.notify_audit
    include_tags           = local.monitor_defaults.include_tags
    timeout_h              = local.monitor_defaults.timeout_h
    auto_resolve_min_hours = local.monitor_defaults.auto_resolve_min_hours
    auto_resolve_max_hours = local.monitor_defaults.auto_resolve_max_hours
  }
  api_validate = var.datadog_validate
}

locals {
  composites_budget = yamldecode(file("${local.policy_dir}/policy/composites.yaml")).budget
}

# =============================================================================
# PLATFORM-WIDE GUARDRAIL
#
# The bounded-object invariant, asserted as code. If a change to the catalog
# would push the managed estate past the budget, the PLAN fails — before anyone
# discovers it as a Datadog bill or an unreviewable estate.
# =============================================================================
check "monitor_budget" {
  assert {
    condition = local.total_managed_monitors <= local.global.cardinality.max_total_managed_monitors
    error_message = format(
      "Monitor budget exceeded: %d managed monitors (%d archetype+custom, %d burn, %d composite) against a budget of %d. Either the catalog has grown a per-resource pattern, or the budget needs an explicit, reviewed increase in platform/policy/global.yaml.",
      local.total_managed_monitors,
      length(local.primary_instances),
      length(local.burn_instances),
      length(local.composite_instances),
      local.global.cardinality.max_total_managed_monitors,
    )
  }
}

check "paging_budget" {
  assert {
    condition = length([
      for k, i in merge(local.primary_instances, local.burn_instances) : k if i.pages
    ]) <= local.global.cardinality.max_paging_monitors
    error_message = format(
      "Paging budget exceeded: %d monitor patterns can page against a budget of %d. Every addition here costs somebody sleep — raise the budget deliberately in platform/policy/global.yaml, or reclassify the signal.",
      length([for k, i in merge(local.primary_instances, local.burn_instances) : k if i.pages]),
      local.global.cardinality.max_paging_monitors,
    )
  }
}

check "p1_budget" {
  assert {
    condition = length([
      for k, i in merge(local.primary_instances, local.burn_instances) : k if i.priority == "P1"
    ]) <= local.global.cardinality.max_p1_monitors
    error_message = format(
      "P1 budget exceeded: %d patterns classed P1 against a budget of %d. P1 means 'major business outage'. If everything is P1, nothing is.",
      length([for k, i in merge(local.primary_instances, local.burn_instances) : k if i.priority == "P1"]),
      local.global.cardinality.max_p1_monitors,
    )
  }
}

check "composite_members_resolved" {
  assert {
    condition     = length(local.composite_unresolvable) == 0
    error_message = "Composite members missing for: ${join("; ", local.composite_unresolvable)}. A composite whose members do not exist silently removes a confirmed-impact page."
  }
}
