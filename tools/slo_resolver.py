#!/usr/bin/env python3
"""THE SLO RESOLUTION CHAIN (§12) — one implementation, used by every tool.

A service does not state its SLOs; it states its INTENT (a tier, an entity
type, optionally a profile name, optionally an override) and the platform
resolves the objectives from policy. This module is that resolution, and it is
the only place in the Python tooling that knows the order of the layers:

    1 enterprise defaults  slo_profiles.yaml → defaults
    2 entity type          slo_profiles.yaml → by_entity_type[service_archetype]
    3 platform             slo_profiles.yaml → by_platform[domain]
    4 criticality          tiers.yaml        → tiers[tier].slo
    5 environment          environments.yaml → slo_impact  (+ by_environment)
    6 slo_profile          slo_profiles.yaml → profiles[service.slo.profile]
    7 service override     the service's own slo.objectives.<name>   ← WINS

Later layers win field by field, so a service can override a single number
without restating the SLI, the timeframe or the burn windows. Every resolved
field records WHICH layer set it (`provenance`), because "why is this service's
target 99.99?" is a question an on-call engineer asks at 3am and a governance
review asks quarterly, and neither should have to read four YAML files to
answer it.

`stacks/coverage/slos.tf` implements the same chain in HCL against the same
files. The two never read each other — they are both interpreters of
platform/policy/, which is the rule the whole repository is built on.
"""
from __future__ import annotations

import sys

import obs_common as oc

# The layers, in resolution order. Named here so provenance strings, the HCL
# implementation and the documentation cannot drift apart silently.
LAYERS = (
    "enterprise_defaults",
    "entity_type",
    "platform",
    "criticality",
    "environment",
    "slo_profile",
    "service_override",
)

# Sub-objects that merge FIELD-WISE rather than being replaced wholesale. A
# service that wants a tighter latency boundary writes `threshold: {value: 200}`
# and keeps the statistic and unit the entity type defined; replacing the whole
# map would silently drop them and produce an SLI that reads a tag nobody emits.
DEEP_MERGE_KEYS = ("threshold", "sli")

# Datadog's supported SLO timeframes. Anything else is rejected at apply time.
VALID_TIMEFRAMES = ("7d", "30d", "90d")


def load_slo_profiles() -> dict:
    """slo_profiles.yaml, loaded on its own for callers that only need it."""
    return oc.load_policy()["slo_profiles_doc"]


# -----------------------------------------------------------------------------
# Identity
# -----------------------------------------------------------------------------
def slo_id_for(service: str, objective: str) -> str:
    """The stable id of a per-service objective.

    `availability` keeps the bare `slo-svc-<service>` id it has always had.
    That is not cosmetic: the id is the Terraform address AND the tag the burn
    monitors select on, so changing it destroys and recreates the SLO in
    Datadog — and an SLO recreated is an error-budget history erased. Every
    objective added by this phase takes a suffixed id, which is exactly the
    information the old single-objective id could not carry.
    """
    return f"slo-svc-{service}" if objective == "availability" else f"slo-svc-{service}-{objective}"


# -----------------------------------------------------------------------------
# Merge
# -----------------------------------------------------------------------------
def _merge_layer(acc: dict, prov: dict, layer_fields: dict, layer: str) -> None:
    """Apply one layer's fields onto the accumulator, recording provenance."""
    for key, value in (layer_fields or {}).items():
        if key in DEEP_MERGE_KEYS and isinstance(value, dict) and isinstance(acc.get(key), dict):
            merged = dict(acc[key])
            for sub_key, sub_value in value.items():
                merged[sub_key] = sub_value
                prov[f"{key}.{sub_key}"] = layer
            acc[key] = merged
        else:
            acc[key] = value
        prov[key] = layer


def _objectives_of(block) -> dict:
    """`objectives:` out of a layer block, tolerating an absent or empty block."""
    if not isinstance(block, dict):
        return {}
    return block.get("objectives") or {}


def _criticality_layer(policy: dict, tier: str) -> dict:
    """tiers.yaml expressed in objective shape.

    The tier owns two things and only two: the TARGET the business attached to
    each objective name, and how many burn windows that tier is willing to be
    woken for. Everything else about an objective is a technical matter that
    belongs to the entity type or the profile.
    """
    tier_slo = policy["tiers"][tier]["slo"]
    windows = tier_slo.get("burn_windows") or []
    return {
        name: {"target": target, "burn_alerts": list(windows)}
        for name, target in (tier_slo.get("objectives") or {}).items()
    }


def _environment_layer(profiles_doc: dict, env: str) -> dict:
    """The per-environment adjustments, if any. Whether an environment
    materializes objectives AT ALL is not settled here — see `_environment_gate`,
    because that decision must not be overridable by a later layer."""
    by_env = profiles_doc.get("by_environment") or {}
    return (by_env.get("overrides") or {}).get(env) or {}


def _environment_gate(policy: dict, profiles_doc: dict, env: str) -> bool:
    """Can this environment materialize an objective at all?

    environments.yaml already answers it as `slo_impact`: an environment whose
    own policy says its failures do not consume budget cannot carry a promise.
    Applied as a gate rather than as a merged field on purpose — the profile
    layer resolves AFTER the environment layer, so a profile with
    `enabled: true` would otherwise switch production objectives on in staging,
    which is how non-production ends up paging.
    """
    by_env = profiles_doc.get("by_environment") or {}
    if not by_env.get("materialize_when_slo_impact", True):
        return True
    return bool(policy["environments"][env].get("slo_impact"))


# -----------------------------------------------------------------------------
# Invariants — applied AFTER the chain, because a tier must not be able to
# override a constraint of the vendor's API.
# -----------------------------------------------------------------------------
def _apply_invariants(policy: dict, objective: dict, warnings: list[str]) -> dict:
    """Non-negotiable corrections no layer is allowed to undo.

    Today there is one, and it comes from a real failed plan: Datadog rejects a
    burn_rate() alert on a monitor-based SLO that has any non-metric member
    ("Alerting on monitor based SLOs currently supports metric monitors"). A
    tier0 datastore therefore cannot have fast/medium/slow burn alerts on a
    service-check-backed availability objective, no matter what its tier says —
    so the chain resolves the tier's windows and then this drops them, with the
    reason recorded rather than silently applied.
    """
    if objective.get("type") == "monitor" and objective.get("burn_alerts"):
        members = objective.get("member_archetypes") or []
        non_metric = sorted(
            m for m in members
            if policy["archetypes"].get(m, {}).get("monitor_type") != "query alert"
        )
        if non_metric:
            objective["burn_alerts"] = []
            objective["provenance"]["burn_alerts"] = "invariant:non_metric_members"
            warnings.append(
                f"burn alerts dropped: monitor SLO members {non_metric} are not metric "
                "monitors, and Datadog only supports burn_rate() on metric members"
            )
    return objective


# -----------------------------------------------------------------------------
# Substitution
# -----------------------------------------------------------------------------
def latency_bucket(threshold: dict | None) -> str:
    """The telemetry tag value that carries an objective's latency boundary.

    A Datadog metric SLI is a ratio of two counts, so the boundary has to exist
    as a tag on the count before the SLI can read it (see slo_profiles.yaml).
    This is the one function that decides the tag's spelling; the emitter
    contract in the profile and the SLI query must agree with it.
    """
    if not threshold:
        return ""
    value = threshold.get("value")
    unit = threshold.get("unit", "")
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return f"under_{value}{unit}"


def _substitute(query: str, service: str, env: str, threshold: dict | None) -> str:
    return (query
            .replace("__SERVICE__", service)
            .replace("__ENV__", env)
            .replace("__LATENCY_BUCKET__", latency_bucket(threshold)))


# -----------------------------------------------------------------------------
# The chain
# -----------------------------------------------------------------------------
def resolve_objectives(policy: dict, service: dict, env: str = "prod") -> dict:
    """Every objective this service resolves to, enabled or not.

    Disabled objectives are returned too (with `enabled: False`), because "this
    service could carry a latency objective and has not asked for one" is a
    governance answer, and dropping them here would make it unanswerable.
    """
    profiles_doc = policy["slo_profiles_doc"]
    sa = service["service_archetype"]
    domain = policy["service_archetypes"][sa]["domain"]
    declared = service.get("slo") or {}
    profile_name = declared.get("profile")
    profile = (profiles_doc.get("profiles") or {}).get(profile_name, {}) if profile_name else {}

    layer_objectives = {
        "entity_type": _objectives_of((profiles_doc.get("by_entity_type") or {}).get(sa, {})),
        "platform": _objectives_of((profiles_doc.get("by_platform") or {}).get(domain, {})),
        "criticality": _criticality_layer(policy, service["tier"]),
        "environment": _environment_layer(profiles_doc, env),
        "slo_profile": _objectives_of(profile),
        "service_override": declared.get("objectives") or {},
    }

    # Only an entity type can INTRODUCE an objective: it is the layer that owns
    # the SLI. A profile or a service that names an objective the entity type
    # does not define would produce an SLO with no query at all, which is caught
    # by validate() rather than created and left silently green.
    names = sorted(layer_objectives["entity_type"])
    env_allows = _environment_gate(policy, profiles_doc, env)

    resolved: dict[str, dict] = {}
    for name in names:
        acc: dict = {}
        prov: dict = {}
        _merge_layer(acc, prov, profiles_doc.get("defaults") or {}, "enterprise_defaults")
        for layer in LAYERS[1:]:
            fields = layer_objectives[layer].get(name)
            if fields:
                _merge_layer(acc, prov, fields, layer)

        if not env_allows:
            acc["enabled"] = False
            prov["enabled"] = "environment"

        acc["name"] = name
        acc["provenance"] = prov
        acc["warnings"] = []
        acc.setdefault("member_archetypes", [])
        acc.setdefault("burn_alerts", [])
        _apply_invariants(policy, acc, acc["warnings"])

        threshold = acc.get("threshold")
        if acc.get("sli"):
            acc["query"] = {
                "numerator": _substitute(acc["sli"]["numerator"], service["name"], env, threshold),
                "denominator": _substitute(acc["sli"]["denominator"], service["name"], env, threshold),
            }
        else:
            acc["query"] = None
        resolved[name] = acc
    return resolved


def materializes_per_service_slos(policy: dict, service: dict) -> bool:
    """Does this service get its own SLOs at all? (§14)

    Either the tier asks for per-service scope (today: tier0 only, which is what
    keeps the object count bounded by mission-critical services rather than by
    estate size), or the service opted in by declaring an `slo:` block — the
    escape hatch for a tier1 service with one contractual endpoint, which should
    not have to be relabelled tier0 to make a promise.
    """
    tier_slo = policy["tiers"][service["tier"]]["slo"]
    criticality = policy["slo_profiles_doc"].get("criticality") or {}
    wanted = criticality.get("materialize_when_scope", "per_service")
    opt_in = bool(criticality.get("opt_in_via_service_yaml", True)) and bool(service.get("slo"))
    return tier_slo.get("scope") == wanted or opt_in


def resolved_slos(policy: dict, services: dict, env: str = "prod") -> dict:
    """slo_id → the SLO the platform will create for it.

    The shape matches what `modules/slo` consumes and what a live Datadog SLO
    carries in its tags, so the coverage report can join the two directly.
    """
    out: dict[str, dict] = {}
    for name, service in sorted(services.items()):
        if not materializes_per_service_slos(policy, service):
            continue
        domain = policy["service_archetypes"][service["service_archetype"]]["domain"]
        for obj_name, obj in resolve_objectives(policy, service, env).items():
            if not obj.get("enabled"):
                continue
            out[slo_id_for(name, obj_name)] = {
                "slo_id": slo_id_for(name, obj_name),
                "name": f"{name} {obj_name} ({service['tier']})",
                "objective": obj_name,
                "scope": "service",
                "service": name,
                "team": service["team"],
                "domain": domain,
                "tier": service["tier"],
                "env": env,
                "entity_type": service["service_archetype"],
                "profile": (service.get("slo") or {}).get("profile"),
                "type": obj["type"],
                "target": obj["target"],
                "timeframe": obj["timeframe"],
                "threshold": obj.get("threshold"),
                "burn_alerts": obj.get("burn_alerts", []),
                "member_archetypes": obj.get("member_archetypes", []),
                "query": obj.get("query"),
                "telemetry_dependency": obj.get("telemetry_dependency"),
                "provenance": obj["provenance"],
                "warnings": obj["warnings"],
            }
    return out


# -----------------------------------------------------------------------------
# Validation — the lint rules validate_policy.py reports under [SLO_PROFILE]
# -----------------------------------------------------------------------------
def validate(policy: dict, services: dict | None = None) -> list[str]:
    """Everything about profiles and service declarations that can be checked
    without talking to Datadog. Returned as strings so validate_policy.py can
    print them in its own format."""
    doc = policy["slo_profiles_doc"]
    services = oc.load_services() if services is None else services
    errors: list[str] = []

    def err(where: str, msg: str) -> None:
        errors.append(f"[SLO_PROFILE] {where}: {msg}")

    names = set(doc.get("objective_names") or [])
    windows = set(policy["global"]["burn_rate_windows"])
    archetypes = policy["archetypes"]
    entity_types = set(policy["service_archetypes"])

    def check_objective(where: str, obj_name: str, obj: dict, *, full: bool) -> None:
        if obj_name not in names:
            err(where, f"objective {obj_name!r} is not one of {sorted(names)}")
        if "target" in obj and not (0 < float(obj["target"]) < 100):
            err(where, f"target {obj['target']} must be a percentage above 0 and below 100")
        if "timeframe" in obj and obj["timeframe"] not in VALID_TIMEFRAMES:
            err(where, f"timeframe {obj['timeframe']!r} is not one of {list(VALID_TIMEFRAMES)}")
        if "type" in obj and obj["type"] not in ("metric", "monitor"):
            err(where, f"type {obj['type']!r} must be metric or monitor")
        for w in obj.get("burn_alerts") or []:
            if w not in windows:
                err(where, f"burn window {w!r} is not defined in global.yaml")
        for m in obj.get("member_archetypes") or []:
            if m not in archetypes:
                err(where, f"member_archetype {m!r} does not exist")
        threshold = obj.get("threshold")
        if threshold is not None:
            unknown = sorted(set(threshold) - {"statistic", "operator", "value", "unit"})
            if unknown:
                err(where, f"threshold has unknown field(s) {unknown}")
        if not full:
            # A later layer states only what it CHANGES — `threshold: {value: 200}`
            # is a complete statement of intent once merged. Completeness is
            # therefore asserted on the entity type (which introduces the
            # objective) and on the resolved result, never on a partial layer.
            return
        # `full` — the objective as an entity type declares it, where the SLI
        # and the boundary both have to be complete.
        if threshold is not None:
            for f in ("statistic", "operator", "value"):
                if f not in threshold:
                    err(where, f"threshold is missing `{f}` — an objective without a stated "
                               "boundary cannot be measured or reviewed")
            if isinstance(threshold.get("value"), (int, float)) and "unit" not in threshold:
                err(where, "a numeric threshold must carry a `unit`; a bare number is not a boundary")
        if obj.get("type") == "metric" and not obj.get("sli"):
            err(where, "metric objectives need an `sli` with a numerator and a denominator")
        if obj.get("type") == "monitor" and not obj.get("member_archetypes"):
            err(where, "monitor objectives need `member_archetypes`")
        for side in ("numerator", "denominator"):
            if obj.get("sli") and side not in obj["sli"]:
                err(where, f"sli is missing its {side}")

    # --- the profile catalog itself ------------------------------------------
    for et, block in (doc.get("by_entity_type") or {}).items():
        if et not in entity_types:
            err(f"by_entity_type {et}", "is not a registered service archetype")
        for obj_name, obj in _objectives_of(block).items():
            check_objective(f"by_entity_type {et}.{obj_name}", obj_name, obj, full=True)

    domains = set(policy["domains"])
    for plat, block in (doc.get("by_platform") or {}).items():
        if plat not in domains:
            err(f"by_platform {plat}", "is not a registered domain, so the layer never applies")
        for obj_name, obj in _objectives_of(block).items():
            check_objective(f"by_platform {plat}.{obj_name}", obj_name, obj, full=False)
        # See the note in slo_profiles.yaml: criticality resolves AFTER platform.
        for obj_name, obj in _objectives_of(block).items():
            for field in ("target", "burn_alerts"):
                if field in obj:
                    err(f"by_platform {plat}.{obj_name}",
                        f"sets `{field}`, which the criticality layer resolves later and would "
                        "overwrite. Put it in a profile, or enforce it as an invariant")

    for pid, profile in (doc.get("profiles") or {}).items():
        where = f"profile {pid}"
        if not profile.get("entity_types"):
            err(where, "must declare `entity_types` — a profile that can be applied to "
                       "anything can be applied to something it cannot measure")
        for et in profile.get("entity_types") or []:
            if et not in entity_types:
                err(where, f"entity_type {et!r} is not a registered service archetype")
        for obj_name, obj in _objectives_of(profile).items():
            check_objective(f"{where}.{obj_name}", obj_name, obj, full=False)
            for et in profile.get("entity_types") or []:
                declared = _objectives_of((doc.get("by_entity_type") or {}).get(et, {}))
                if obj_name not in declared:
                    err(where, f"enables {obj_name!r} for entity type {et!r}, which declares no "
                               f"SLI for it — the SLO would have no query at all")

    # --- service declarations -------------------------------------------------
    seen_ids: dict[str, str] = {}
    for name, service in sorted(services.items()):
        declared = service.get("slo") or {}
        where = f"service {name}"
        profile_name = declared.get("profile")
        if profile_name:
            profile = (doc.get("profiles") or {}).get(profile_name)
            if not profile:
                err(where, f"slo.profile {profile_name!r} is not in the profile catalog")
            elif service["service_archetype"] not in (profile.get("entity_types") or []):
                err(where, f"slo.profile {profile_name!r} applies to "
                           f"{profile.get('entity_types')}, not to a "
                           f"{service['service_archetype']}")
        for obj_name, obj in (declared.get("objectives") or {}).items():
            check_objective(f"{where}.objectives.{obj_name}", obj_name, obj, full=False)
            # A service override is the one layer with no reviewer above it: it
            # beats the tier, the platform and the profile. The written reason
            # is what makes that reviewable in the pull request, and what a
            # quarterly SLO review reads instead of guessing.
            if not obj.get("rationale"):
                err(f"{where}.objectives.{obj_name}",
                    "a service-level override must record a `rationale` — it wins over the "
                    "tier, the platform and the profile, so the reason has to be written down")

        if not materializes_per_service_slos(policy, service):
            continue
        for slo_id, slo in resolved_slos(policy, {name: service}).items():
            if slo_id in seen_ids:
                err(where, f"resolves {slo_id!r}, which {seen_ids[slo_id]} also resolves")
            seen_ids[slo_id] = name
            if slo["type"] == "metric":
                for side in ("numerator", "denominator"):
                    q = (slo["query"] or {}).get(side, "")
                    if not q:
                        err(where, f"{slo_id} has no SLI {side}")
                    elif "__" in q:
                        err(where, f"{slo_id} SLI {side} still contains an unresolved "
                                   f"placeholder: {q}")
            if slo["team"] not in policy["teams"]:
                err(where, f"{slo_id} is owned by {slo['team']!r}, which is not a registered team")
            # Completeness is asserted on the RESOLVED threshold, because that
            # is the only place all the layers have been applied.
            th = slo.get("threshold")
            if th is not None and any(f not in th for f in ("statistic", "operator", "value")):
                err(where, f"{slo_id} resolves an incomplete threshold {th} — the objective "
                           "states no boundary that could be measured or reviewed")
    return errors


def main() -> int:
    """Print the resolved per-service objectives — the answer to 'what does this
    service actually promise, and which layer decided that?'"""
    import argparse
    import json

    ap = argparse.ArgumentParser()
    ap.add_argument("--service", help="only this service")
    ap.add_argument("--env", default="prod")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    policy = oc.load_policy()
    services = oc.load_services()
    if args.service:
        services = {k: v for k, v in services.items() if k == args.service}
    slos = resolved_slos(policy, services, args.env)

    if args.json:
        print(json.dumps(slos, indent=2, sort_keys=True, default=str))
    else:
        for slo_id, s in sorted(slos.items()):
            print(f"{slo_id}\n  {s['objective']:<13} target {s['target']}  {s['type']}  "
                  f"{s['timeframe']}  burn={s['burn_alerts'] or '-'}")
            print(f"  set by: " + ", ".join(
                f"{k}←{v}" for k, v in sorted(s["provenance"].items())
                if k in ("target", "type", "timeframe", "burn_alerts", "enabled")))
            for w in s["warnings"]:
                print(f"  ! {w}")
    errors = validate(policy, services)
    for e in errors:
        print(f"POLICY VIOLATION: {e}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
