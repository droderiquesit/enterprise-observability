# =============================================================================
# POLICY LOADING + SHARED RESOLUTION HELPERS
#
# Terraform is a pure INTERPRETER of platform/policy/. No monitoring decision
# is made in HCL — every decision is data, reviewed as YAML in a pull request.
# =============================================================================

locals {
  policy_dir = "${path.module}/../../platform"

  # --- the configuration hierarchy, loaded verbatim -------------------------
  # Only the files THIS stack decides from are loaded. Foundation concerns
  # (teams, notification profiles, workflow catalog) are loaded by the
  # foundation stack; loading them here too would just be a plan-time cost
  # and a second place for a reader to look.
  global      = yamldecode(file("${local.policy_dir}/policy/global.yaml"))
  domains     = yamldecode(file("${local.policy_dir}/policy/domains.yaml")).domains
  env_policy  = yamldecode(file("${local.policy_dir}/policy/environments.yaml")).environments
  tier_maps   = yamldecode(file("${local.policy_dir}/policy/tiers.yaml"))
  tiers       = local.tier_maps.tiers
  prio        = yamldecode(file("${local.policy_dir}/policy/priorities.yaml"))
  slo_doc     = yamldecode(file("${local.policy_dir}/policy/slos.yaml"))
  slo_catalog = local.slo_doc.slos
  exceptions  = yamldecode(file("${local.policy_dir}/policy/exceptions.yaml")).exceptions
  runbooks    = yamldecode(file("${local.policy_dir}/policy/runbooks.yaml"))

  # ---------------------------------------------------------------------------
  # NATIVE RUNBOOK ATTACHMENT LOOKUP
  #
  # runbook id → the published Datadog notebook it lives in. The monitor
  # factory turns these into the monitor's `assets` block (category=runbook,
  # resource_type=notebook), which is how a runbook is attached to a monitor.
  # NOTHING here produces a URL for the alert body.
  #
  # `notebook_id` is empty for a runbook that has not been published yet; the
  # factory omits the asset in that case rather than attaching a dead pointer,
  # and tools/publish_runbooks.py --check fails the governance run until it is
  # published and its id is committed to the registry.
  # ---------------------------------------------------------------------------
  runbook_notebook_id = {
    for rid, r in local.runbooks.runbooks : rid => try(tostring(r.id), "")
  }
  runbook_notebook_url = {
    for rid, r in local.runbooks.runbooks :
    rid => try("${local.runbooks.notebook_base_url}/${tostring(r.id)}", "")
  }
  runbook_title = {
    for rid, r in local.runbooks.runbooks : rid => try(r.title, rid)
  }
  composites = yamldecode(file("${local.policy_dir}/policy/composites.yaml")).composites

  # service_archetype → domain, straight from the service-archetype catalog.
  # (Previously re-typed by hand here AND in the foundation stack — a policy
  # decision living in HCL, which this file's header forbids.)
  service_archetype_domain = {
    for k, v in yamldecode(file("${local.policy_dir}/policy/service_archetypes.yaml")).service_archetypes :
    k => v.domain
  }

  # --- archetype catalog: every file in policy/archetypes/ ------------------
  archetype_docs = {
    for f in fileset("${local.policy_dir}/policy/archetypes", "*.yaml") :
    f => yamldecode(file("${local.policy_dir}/policy/archetypes/${f}"))
  }
  archetypes = merge([
    for f, doc in local.archetype_docs : {
      for id, a in doc.archetypes : id => merge(a, { id = id, domain = doc.domain })
    }
  ]...)

  # --- service registry (tier0 SLOs + catalog ownership) --------------------
  service_docs = {
    for f in fileset("${local.policy_dir}/services", "*.yaml") :
    trimsuffix(f, ".yaml") => yamldecode(file("${local.policy_dir}/services/${f}")).service
  }

  # ---------------------------------------------------------------------------
  # ENVIRONMENT-AWARE EVALUATION WINDOWS
  #
  # The SAME archetype definition is reused across environments; only the
  # window widens. Non-production is noisier and less important, so it waits
  # longer before believing a signal.
  #
  # Forecast horizons (`next_*`) are deliberately NOT scaled: a forecast window
  # expresses how much lead time a human needs, which does not change because
  # the environment is staging.
  # ---------------------------------------------------------------------------
  window_scale = {
    "last_5m"  = { prod = "last_5m", stage = "last_10m", qa = "last_10m" }
    "last_10m" = { prod = "last_10m", stage = "last_15m", qa = "last_30m" }
    "last_15m" = { prod = "last_15m", stage = "last_30m", qa = "last_30m" }
    "last_30m" = { prod = "last_30m", stage = "last_1h", qa = "last_1h" }
    "last_1h"  = { prod = "last_1h", stage = "last_2h", qa = "last_2h" }
    "last_2h"  = { prod = "last_2h", stage = "last_4h", qa = "last_4h" }
  }

  # ---------------------------------------------------------------------------
  # EXCEPTION INDEX
  #
  # Terraform applies every exception in the file and does NOT evaluate expiry.
  # That is deliberate: `timestamp()` inside a plan makes the plan
  # non-deterministic, and a plan that changes because a day passed cannot be
  # reviewed or replayed.
  #
  # Expiry is enforced in three places that CAN be time-aware safely:
  #   1. tools/validate_policy.py  — CI fails the build on an expired entry
  #   2. coverage check C12        — the scheduled governance run goes red
  #   3. archetype exception-expired — runtime alert to the platform team
  # An expired exception therefore cannot survive a merge, let alone an apply.
  # ---------------------------------------------------------------------------
  priority_exceptions = {
    for e in local.exceptions :
    "${lookup(e.scope, "archetype", "*")}.${lookup(e.scope, "env", "*")}" => e.value
    if e.control == "priority"
  }

  # ---------------------------------------------------------------------------
  # PRIORITY RESOLUTION  (see platform/policy/priorities.yaml)
  #
  #   priority = clamp( matrix[impact_class][band], environment ceiling )
  #
  # "Clamp" means an environment can only ever make a signal QUIETER. There is
  # no mechanism anywhere in this platform for a non-production environment to
  # raise a priority — that is what stops staging from paging.
  # ---------------------------------------------------------------------------
  priority_rank = { P1 = 1, P2 = 2, P3 = 3, P4 = 4 }
  rank_priority = { 1 = "P1", 2 = "P2", 3 = "P3", 4 = "P4" }

  # ---------------------------------------------------------------------------
  # NOTIFICATION PROFILE RESOLUTION (first match wins, per notification_profiles.yaml)
  # ---------------------------------------------------------------------------
  # Implemented as a function-shaped local consumed by locals_instances.tf.
  nonprod_envs = ["qa", "stage"]
}
