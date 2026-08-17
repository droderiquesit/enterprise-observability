# ---------------------------------------------------------------------------
# Policy loading + the configuration hierarchy merge:
#   global → domain → archetype → profile → environment → criticality → team
#   → approved exception
# Everything below is pure data transformation; the result is the `instances`
# map consumed by the monitor factory.
# ---------------------------------------------------------------------------

locals {
  policy_dir = "${path.module}/../../platform/policy"

  global      = yamldecode(file("${local.policy_dir}/global.yaml"))
  domains     = yamldecode(file("${local.policy_dir}/domains.yaml")).domains
  profiles_db = yamldecode(file("${local.policy_dir}/profiles.yaml"))
  env_policy  = yamldecode(file("${local.policy_dir}/environments.yaml")).environments
  tiers       = yamldecode(file("${local.policy_dir}/criticality.yaml")).tiers
  teams       = yamldecode(file("${local.policy_dir}/teams.yaml")).teams
  routing     = yamldecode(file("${local.policy_dir}/routing.yaml"))
  slo_catalog = yamldecode(file("${local.policy_dir}/slos.yaml")).slos
  exceptions  = yamldecode(file("${local.policy_dir}/exceptions.yaml")).exceptions
  runbooks    = yamldecode(file("${local.policy_dir}/runbooks.yaml"))

  archetype_docs = {
    for f in fileset("${local.policy_dir}/archetypes", "*.yaml") :
    f => yamldecode(file("${local.policy_dir}/archetypes/${f}"))
  }
  # archetype id → definition + domain
  archetypes = merge([
    for f, doc in local.archetype_docs : {
      for id, a in doc.archetypes : id => merge(a, { id = id, domain = doc.domain })
    }
  ]...)

  # -- Exception index -------------------------------------------------------
  # Active (non-expired) exceptions keyed by "<archetype>.<env>" for the
  # severity/profile controls handled at instance level. Expiry enforcement
  # for ALL exceptions also happens in CI (tools/validate_policy.py).
  active_exceptions = {
    for e in local.exceptions :
    "${lookup(e.scope, "archetype", "*")}.${lookup(e.scope, "env", "*")}" => e...
  }

  # -- Hierarchy resolution helpers -----------------------------------------
  # Tier band for an archetype instance: an archetype restricted to specific
  # tiers uses its strictest tier; otherwise the platform standard band tier2.
  archetype_tier = {
    for id, a in local.archetypes : id => try(sort(a.tiers)[0], "tier2")
  }

  # Monitoring profile per (archetype, env): environment default, upgraded to
  # `regulated` for compliance_absolute archetypes and `security_sensitive`
  # for the security domain.
  profile_for = {
    for pair in setproduct(keys(local.archetypes), var.environments) :
    "${pair[0]}.${pair[1]}" => (
      local.archetypes[pair[0]].domain == "security" ? "security_sensitive" :
      contains(["compliance_absolute", "audit_continuity"], local.archetypes[pair[0]].class) ? "regulated" :
      local.archetypes[pair[0]].class == "burn_rate" ? "critical" :
      local.env_policy[pair[1]].default_profile
    )
  }
}
