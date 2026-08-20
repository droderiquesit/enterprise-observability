"""ACT MODE (§44) — inspect, validate, resolve, generate, plan. Never apply.

The whole of Act mode is a FUNNEL into one exit:

    MCP → YAML → git branch → pull request → CI validation → Terraform → Datadog

Nothing here writes to Datadog. `mcp/obs_state.py` can only issue GET, and
nothing in this module talks to Datadog at all — it produces text, and
`mcp/obs_gitops.py` puts that text in a pull request. If somebody wants a
monitor in production they get a reviewed commit, which is the same path a
human uses. That is the point: an agent that can bypass code review has quietly
removed code review for everybody.

The validators are not re-implementations. `validate_monitors.validate` is the
exact function the CI gate runs, called against a temporary file because that
is its interface (it checks `name == path.stem`, which is a real rule: deleting
the file must delete the right monitor).
"""
from __future__ import annotations

import fnmatch
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import yaml

# Importing obs_state first is load-bearing: it is what puts tools/ on sys.path,
# so every `tools/` import below has to come after it.
from obs_state import REPO_ROOT

import generate_runbooks                    # noqa: E402  (tools/ — on the path)
import obs_common as oc                     # noqa: E402
import validate_monitors                    # noqa: E402
import validate_policy                      # noqa: E402

import obs_governance as gov                # noqa: E402

# ---------------------------------------------------------------------------
# THE WRITE FENCE. Act mode may only ever propose changes to files a service
# team is supposed to own. Everything else in this repository is either the
# INTERPRETER (stacks/, modules/), the CATALOG that every team shares
# (policy/archetypes/), generated output, or the CI gate itself — and an agent
# editing its own gate is not a feature.
#
# Matching is on the repo-relative path with fnmatch, and DENY is evaluated
# first so a new ALLOW pattern can never silently widen the fence.
# ---------------------------------------------------------------------------
ALLOWED_WRITE_PATTERNS = (
    "platform/entities/*.yaml",             # one file onboards an entity
    "platform/monitors/*.yaml",             # one file adds a self-service monitor
    "platform/runbooks/*.md",               # the human sections of a runbook
)
ALLOWED_INSERT_TARGETS = {
    # Adding an SLO is a change to a shared catalog, so it is an ANCHORED
    # INSERT into one named file rather than a whole-file write: an agent
    # cannot rewrite the other 22 objectives while adding one.
    "platform/policy/slos.yaml": "slos",
}
DENIED_WRITE_PATTERNS = (
    ("platform/policy/archetypes/*", "the shared monitor catalog — a change here changes "
                                     "monitoring for every team at once and belongs in a "
                                     "human-authored PR"),
    ("stacks/*", "Terraform: the interpreter, not the configuration"),
    ("modules/*", "Terraform: the interpreter, not the configuration"),
    (".github/*", "the CI gate — an agent must not be able to edit the check that "
                  "reviews it"),
    ("tests/*", "the test suite, including the plan-derived fixtures"),
    ("tools/*", "the platform tooling"),
    ("docs/*", "documentation is generated or human-authored, never agent-authored"),
    ("README.md", "the repository's front door"),
    ("generated/*", "generated output is never committed"),
    ("mcp/*", "this server's own source"),
)


class WriteFenceError(gov.GovernanceError):
    """A proposed path is outside what Act mode may touch.

    A GovernanceError rather than a plain exception so the router reports it as
    a REFUSAL with a remedy, not as an internal tool failure — hitting the
    fence is a policy decision working correctly, and the audit line should say
    `deny`, not `error`.
    """
    code = "write_fence_denied"


def assert_writable(rel_path: str) -> None:
    p = str(rel_path).replace("\\", "/").lstrip("./")
    remedy = (f"writable: {', '.join(ALLOWED_WRITE_PATTERNS)}; anchored insert into "
              f"{', '.join(ALLOWED_INSERT_TARGETS)}. Anything else is a human-authored PR.")
    if ".." in Path(p).parts or Path(p).is_absolute():
        raise WriteFenceError(f"{rel_path!r}: path traversal is refused", remedy)
    for pattern, why in DENIED_WRITE_PATTERNS:
        if fnmatch.fnmatch(p, pattern):
            raise WriteFenceError(f"{p!r} is not writable by Act mode: {why}", remedy)
    if p in ALLOWED_INSERT_TARGETS:
        return
    if not any(fnmatch.fnmatch(p, pat) for pat in ALLOWED_WRITE_PATTERNS):
        raise WriteFenceError(f"{p!r} is not writable by Act mode", remedy)


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------
def _infer_kind(doc: dict) -> str:
    if isinstance(doc, dict) and "entity" in doc:
        return "entity"
    if isinstance(doc, dict) and "service" in doc:
        return "service"
    if isinstance(doc, dict) and "monitor" in doc:
        return "monitor"
    return "unknown"


def _validate_entity(state, ent: dict) -> list[str]:
    """Schema + cross-reference checks for an entity registration.

    Both halves are the REAL ones CI runs — platform/schemas/entity.schema.json
    and tools/entity_resolver.validate() — so an entity the MCP accepts is an
    entity the pull-request gate accepts. Re-implementing either here would
    make the MCP a second opinion about what is valid, and the whole point of
    Act mode is that it proposes changes the gate will agree with.
    """
    import entity_resolver

    errors: list[str] = []
    schema = json.loads((REPO_ROOT / "platform" / "schemas" / "entity.schema.json").read_text())
    try:
        import jsonschema
        for e in sorted(jsonschema.Draft202012Validator(schema).iter_errors({"entity": ent}),
                        key=lambda e: list(e.path)):
            errors.append(f"schema: {'/'.join(str(x) for x in e.path)}: {e.message}")
    except ImportError:                     # pragma: no cover — jsonschema is a hard dep
        errors.append("jsonschema is not installed; schema validation was skipped")

    entities = oc.load_entities()
    if not errors:
        errors += entity_resolver.validate(ent, state.policy, entities)

    if ent.get("name") and ent["name"] in entities:
        errors.append(f"entity {ent['name']!r} is already registered — this would be an "
                      "edit, not an onboarding; confirm that is intended")
    return errors


def _validate_service(state, svc: dict) -> list[str]:
    """Schema + the policy references the schema cannot express.

    The JSON Schema is the same file CI validates against
    (platform/schemas/service.schema.json); the extra checks below are the ones
    that need the policy loaded — a schema cannot know whether `team: sre` is a
    registered team.
    """
    errors: list[str] = []
    schema = json.loads((REPO_ROOT / "platform" / "schemas" / "service.schema.json").read_text())
    try:
        import jsonschema
        for e in sorted(jsonschema.Draft202012Validator(schema).iter_errors({"service": svc}),
                        key=lambda e: list(e.path)):
            errors.append(f"schema: {'/'.join(str(x) for x in e.path)}: {e.message}")
    except ImportError:                     # pragma: no cover — jsonschema is a hard dep
        errors.append("jsonschema is not installed; schema validation was skipped")

    policy = state.policy
    if svc.get("team") and svc["team"] not in policy["teams"]:
        errors.append(f"team {svc['team']!r} is not registered in "
                      "platform/policy/teams.yaml")
    sa = svc.get("service_archetype")
    if sa and sa not in policy["service_archetypes"]:
        errors.append(f"service_archetype {sa!r} is not in "
                      "platform/policy/service_archetypes.yaml")
    for dep in svc.get("dependencies", []):
        if dep not in state.services and dep not in policy["teams"]:
            # A dependency on something outside the registry is normal (Entra ID,
            # a vendor). Recorded as a note, not an error — over-strict onboarding
            # is how teams end up not onboarding.
            pass
    if svc.get("name") and svc["name"] in state.services:
        errors.append(f"service {svc['name']!r} is already registered — this would be an "
                      "edit, not an onboarding; confirm that is intended")
    return errors


def _validate_monitor(state, doc: dict) -> list[str]:
    """Run the real CI validator against a temporary file.

    validate_monitors.validate() takes a Path because one of its rules is that
    the manifest's `name` must equal the FILENAME — deleting the file has to
    delete the right monitor. Writing the candidate to `<name>.yaml` in a temp
    dir is what lets that rule be checked on content that is not on disk yet.
    """
    name = ((doc or {}).get("monitor") or {}).get("name") or "candidate"
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / f"{name}.yaml"
        path.write_text(yaml.safe_dump(doc, sort_keys=False))
        return validate_monitors.validate(path, state.policy, state.services)


def validate_manifest(state, text: str, kind: str | None = None) -> dict:
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        return {"kind": kind or "unknown", "subject": None, "valid": False,
                "errors": [f"unparseable YAML: {exc}"], "doc": None}
    if not isinstance(doc, dict):
        return {"kind": kind or "unknown", "subject": None, "valid": False,
                "errors": ["the manifest must be a YAML mapping"], "doc": None}

    kind = kind or _infer_kind(doc)
    if kind == "entity":
        ent = doc.get("entity") or {}
        errors = _validate_entity(state, ent)
        subject = ent.get("name")
    elif kind == "service":
        svc = doc.get("service") or {}
        errors = _validate_service(state, svc)
        subject = svc.get("name")
    elif kind == "monitor":
        errors = _validate_monitor(state, doc)
        subject = (doc.get("monitor") or {}).get("name")
    else:
        return {"kind": "unknown", "subject": None, "valid": False,
                "errors": ["manifest must have a top-level `entity:`, `service:` "
                           "or `monitor:` key"],
                "doc": doc}
    return {"kind": kind, "subject": subject, "valid": not errors,
            "errors": errors, "doc": doc}


# ---------------------------------------------------------------------------
# resolution — the SAME resolvers profile_engine and Terraform use
# ---------------------------------------------------------------------------
def resolve_monitoring_profile(state, *, service_archetype: str, tier: str, env: str,
                               compliance_scope: str | None = None,
                               domain: str | None = None) -> dict:
    """Which monitoring profile and alert band this entity lands on, and why.

    Implemented by driving profile_engine.assign() with a single synthetic
    resource rather than re-deriving the rules here. The resolution order,
    the qa/dev clamp, the security overlay and the exception lookup are then
    provably identical to what the platform does to the real estate.
    """
    policy = state.policy
    if service_archetype not in policy["service_archetypes"]:
        raise ValueError(f"unknown service_archetype {service_archetype!r}")
    if tier not in policy["tiers"]:
        raise ValueError(f"unknown tier {tier!r}")
    if env not in policy["environments"]:
        raise ValueError(f"unknown env {env!r}")

    sa = policy["service_archetypes"][service_archetype]
    probe = {
        "id": "probe:resolve", "kind": "service", "name": "probe",
        "env": env, "region": "global", "service": "__probe__",
        "team": None,
        "tags": {"env": env, "tier": tier, "service_archetype": service_archetype,
                 **({"compliance_scope": compliance_scope} if compliance_scope else {})},
        "source": "mcp-probe",
    }
    result = profile_probe(state, probe)
    ep = policy["environments"][env]
    return {
        "service_archetype": service_archetype,
        "tier": tier, "env": env,
        "domain": domain or sa["domain"],
        "monitoring_profile": result["monitoring_profile"],
        "alert_band": result["alert_band"],
        "support_model": result["support_model"],
        "observe_only_reason": result["observe_only_reason"],
        "packs": sa["packs"],
        "required_telemetry": sa.get("required_telemetry", []),
        "default_slis": sa.get("default_slis", []),
        "environment_policy": {
            "alerting": ep["alerting"], "bands_instantiated": ep["bands_instantiated"],
            "priority_ceiling": ep["priority_ceiling"],
            "paging_allowed": ep["paging_allowed"],
            "servicenow_allowed": ep["servicenow_allowed"],
        },
        "cited_rules": [f"service_archetypes.{service_archetype}", f"tiers.{tier}",
                        f"environments.{env}", "tiers.profile_to_band"],
        "resolver": "tools/profile_engine.py::assign",
    }


def profile_probe(state, resource: dict) -> dict:
    import profile_engine
    out = profile_engine.assign({"resources": [resource]}, state.policy, state.services)
    return out["assignments"][0]


def resolve_slo_profile(state, *, service: str | None = None, tier: str,
                        service_archetype: str) -> dict:
    """Which objective(s) this entity gets, from which layer, and why.

    DELEGATES to tools/slo_resolver.py rather than reimplementing the rules.
    This function used to answer from `slos.yaml -> tier0_slo_template`: one
    availability objective, one target, applied to every tier0 service. That
    template no longer exists — it was replaced by the §12 layered chain — and
    the `.get()` reading it had been returning None for a while without
    anything failing, so the MCP was quietly answering "no template" instead of
    "here are your two objectives".
    """
    import slo_resolver

    policy = state.policy
    sa = policy["service_archetypes"][service_archetype]
    domain = sa["domain"]
    tier_slo = policy["tiers"][tier]["slo"]
    domain_slos = sorted(sid for sid, s in policy["slos"].items()
                         if s.get("scope") == "domain" and s.get("domain") == domain)

    # The registered entity if there is one, so a declared scope/profile/override
    # is honoured; otherwise the minimum record the resolver needs, which is what
    # makes this answerable for a service that does not exist yet.
    registered = state.services.get(service) if service else None
    svc = dict(registered) if registered else {
        "name": service or "<unregistered>", "tier": tier,
        "service_archetype": service_archetype, "team": "<unknown>",
    }
    svc.setdefault("tier", tier)

    per_service = slo_resolver.materializes_per_service_slos(policy, svc)
    objectives = slo_resolver.resolve_objectives(policy, svc, "prod") if per_service else {}
    declared = (svc.get("slo") or {})

    resolved = {
        name: {
            "enabled": o.get("enabled", False),
            "type": o.get("type"),
            "target": o.get("target"),
            "timeframe": o.get("timeframe"),
            "threshold": o.get("threshold"),
            "burn_alerts": o.get("burn_alerts", []),
            "slo_id": slo_resolver.slo_id_for(service, name) if service else None,
            # Which of the eight layers set each field. This is the answer to
            # "why does my service have this target", and it is computed, not
            # narrated.
            "provenance": o.get("provenance", {}),
            "telemetry_dependency": o.get("telemetry_dependency"),
            "warnings": o.get("warnings", []),
        }
        for name, o in objectives.items()
    }

    return {
        "service": service, "tier": tier, "domain": domain,
        "scope": declared.get("scope") or tier_slo["scope"],
        "scope_declared_by": "entity" if declared.get("scope") else "tier",
        "required": tier_slo["required"],
        "burn_windows": tier_slo["burn_windows"],
        "error_budget_policy": (tier_slo.get("error_budget_policy") or "").strip(),
        "domain_slos": domain_slos,
        "per_service": per_service,
        "per_service_slo_id": (slo_resolver.slo_id_for(service, "availability")
                               if per_service and service else None),
        "slo_profile": declared.get("profile"),
        "objectives": resolved,
        "enabled_objectives": sorted(n for n, o in resolved.items() if o["enabled"]),
        "cited_rules": [f"tiers.{tier}.slo"] + (
            ["slo_profiles.by_entity_type." + service_archetype,
             "slo_profiles.by_platform." + domain, "slo_profiles.criticality"]
            + ([f"slo_profiles.profiles.{declared['profile']}"] if declared.get("profile") else [])
            if per_service else [f"slos[scope=domain,domain={domain}]"]),
        "registered": registered is not None,
        # The limits that REMAIN. The earlier pair — "cannot declare multiple
        # objectives (§11)" and "cannot override the domain target (§12)" — were
        # true of the tier0 template and are not true of the layered chain; the
        # first is now false outright, and repeating it would understate what
        # the platform can do.
        "limits": ([] if registered else
                   [f"{service!r} is not registered, so any declared slo.scope, "
                    f"slo.profile or per-objective override is not reflected here"])
                  + ([] if per_service else
                     [f"a domain-scoped entity shares its domain's targets (§12); to "
                      f"promise its own, it must declare slo.scope: per_service"])
                  + ["only the entity type can INTRODUCE an objective — a profile or "
                     "per-service override may retune one, never add one"],
    }


def missing_telemetry(state, *, service_archetype: str, observed=None) -> dict:
    """What this entity must emit for its monitors to be able to fire.

    `required_telemetry` in service_archetypes.yaml is a COARSE, per-archetype
    declaration (`apm_traces`, `http_metrics`). §38 records that individual
    monitor archetypes declare no telemetry requirement at all, so the
    per-monitor list below is DERIVED from the metric namespaces each query
    reads. Both are returned, labelled, and the derivation is disclosed.
    """
    policy = state.policy
    sa = policy["service_archetypes"][service_archetype]
    observed = set(observed or [])
    declared = list(sa.get("required_telemetry", []))

    per_archetype = {}
    for pack in sa["packs"]:
        for aid in policy["packs"][pack]["archetypes"]:
            arch = policy["archetypes"].get(aid)
            if not arch:
                continue
            metrics = sorted(set(generate_runbooks.metrics_in(arch.get("query") or "")))
            per_archetype[aid] = {"pack": pack, "metrics": metrics,
                                  "mandatory": bool(arch.get("mandatory"))}

    all_metrics = sorted({m for v in per_archetype.values() for m in v["metrics"]})
    missing = sorted(m for m in all_metrics if m not in observed)
    return {
        "service_archetype": service_archetype,
        "declared_required_telemetry": declared,
        "declared_missing": [t for t in declared if t not in observed],
        "derived_metrics_required": all_metrics,
        "derived_metrics_missing": missing if observed else all_metrics,
        "per_archetype": per_archetype,
        "observed": sorted(observed),
        "derivation": ("metric names parsed out of each archetype's query "
                       "(generate_runbooks.metrics_in)"),
        "known_gaps": [
            "§38 — archetypes carry no `telemetry:` requirement, so the per-monitor list "
            "is derived, not declared",
            "§8 — nothing emits the `alert_band` tag onto telemetry, so every query that "
            "filters on it currently selects an empty set (docs/telemetry-gaps.md)",
        ],
    }


# ---------------------------------------------------------------------------
# onboarding preview
# ---------------------------------------------------------------------------
def preview_onboarding(state, service: dict) -> dict:
    """Everything that would happen if this service were registered."""
    policy = state.policy
    name = service.get("name")
    tier = service.get("tier")
    sa_id = service.get("service_archetype")
    envs = service.get("envs") or []
    errors = _validate_service(state, service)
    if errors and any(e.startswith("schema:") for e in errors):
        return {"service": name, "valid": False, "errors": errors}

    sa = policy["service_archetypes"][sa_id]
    per_env, joins = [], {}
    for env in envs:
        res = resolve_monitoring_profile(state, service_archetype=sa_id, tier=tier, env=env,
                                         compliance_scope=service.get("compliance_scope"))
        band = res["alert_band"]
        joined = []
        for pack in sa["packs"]:
            for aid in policy["packs"][pack]["archetypes"]:
                arch = policy["archetypes"].get(aid)
                if not arch:
                    continue
                if env in arch["envs"] and band in arch["bands"] and \
                        band in policy["environments"][env]["bands_instantiated"]:
                    priority = oc.resolve_priority(policy, arch["impact_class"], band, env)
                    joined.append({
                        "archetype": aid, "title": arch["title"], "pack": pack,
                        "priority": priority,
                        "pages": oc.pages(policy, priority, band, env),
                        "mandatory": bool(arch.get("mandatory")),
                        "runbook": arch["runbook"], "slo_id": arch["slo_id"],
                    })
                    joins[aid] = True
        per_env.append({"env": env, "monitoring_profile": res["monitoring_profile"],
                        "alert_band": band,
                        "observe_only_reason": res["observe_only_reason"],
                        "monitors_joined": sorted(joined, key=lambda j: j["archetype"]),
                        "monitors_joined_count": len(joined)})

    slo = resolve_slo_profile(state, service=name, tier=tier, service_archetype=sa_id)
    telem = missing_telemetry(state, service_archetype=sa_id)
    runbooks = sorted({policy["archetypes"][a]["runbook"] for a in joins
                       if a in policy["archetypes"]})

    return {
        "service": name, "valid": not errors, "errors": errors,
        "tier": tier, "service_archetype": sa_id, "domain": sa["domain"],
        "team": service.get("team"),
        "packs": sa["packs"],
        "per_environment": per_env,
        "distinct_archetypes_joined": len(joins),
        "slo": slo,
        "telemetry": telem,
        "runbooks_reachable": runbooks,
        # THE HEADLINE NUMBER, and the reason this platform exists.
        "new_datadog_objects_created": 0 if tier != "tier0" else len(slo["burn_windows"]),
        "objects_note": (
            "Registering a service creates NO new monitors: it joins existing grouped "
            "monitors as a new GROUP, selected by tag. A tier0 service is the one "
            "exception — it gets its own SLO and one burn-rate monitor per window."),
    }


def preview_manifest(state, text: str, kind: str | None = None) -> dict:
    """`what would happen if this YAML were merged` — validation + delta."""
    v = validate_manifest(state, text, kind)
    result = {"kind": v["kind"], "subject": v["subject"], "valid": v["valid"],
              "errors": v["errors"], "resolution": {}, "delta": {}}
    if v["kind"] in ("entity", "service") and v["doc"]:
        # preview_onboarding() speaks the service shape, so an entity is
        # projected onto it by the SAME projection every other consumer uses
        # rather than by a second one written here.
        if v["kind"] == "entity":
            svc = oc.entity_as_service(v["doc"]["entity"])
        else:
            svc = v["doc"]["service"]
        if not any(e.startswith("schema:") for e in v["errors"]):
            preview = preview_onboarding(state, svc)
            result["resolution"] = preview
            result["resolution"]["cited_rules"] = [
                f"service_archetypes.{svc.get('service_archetype')}",
                f"tiers.{svc.get('tier')}", "tiers.profile_to_band"]
            result["delta"] = {
                "monitors_created": preview["new_datadog_objects_created"],
                "monitors_joined": sum(e["monitors_joined_count"]
                                       for e in preview["per_environment"]),
                "slos_created": 1 if preview["slo"]["scope"] == "per_service" else 0,
                "summary": (
                    f"{sum(e['monitors_joined_count'] for e in preview['per_environment'])} "
                    f"existing monitor instances gain a group; "
                    f"{preview['new_datadog_objects_created']} new Datadog objects."),
            }
        else:
            result["delta"] = {"summary": "schema-invalid; no delta computed"}
    elif v["kind"] == "monitor" and v["doc"]:
        m = v["doc"]["monitor"]
        envs = m.get("env", [])
        result["resolution"] = {
            "archetype": m.get("archetype"), "service": m.get("service"),
            "envs": envs, "slo": m.get("slo"), "runbook": m.get("runbook"),
            "workflow": m.get("workflow"),
            "cited_rules": [f"archetypes.{m.get('archetype')}", f"slos.{m.get('slo')}",
                            f"runbooks.{m.get('runbook')}", f"workflows.{m.get('workflow')}"],
        }
        result["delta"] = {
            "monitors_created": len(envs),
            "monitors_joined": 0, "slos_created": 0,
            "summary": (f"{len(envs)} new self-service monitor instance(s) "
                        f"({', '.join(envs)}) — self-service monitors DO create objects, "
                        "which is why the manifest requires a justification when it "
                        "duplicates a catalog archetype."),
        }
    else:
        result["delta"] = {"summary": "unrecognized manifest; no delta computed"}
    return result


# ---------------------------------------------------------------------------
# generation
# ---------------------------------------------------------------------------
def generate_entity_yaml(state, spec: dict) -> dict:
    """One registration file, in the ENTITY shape (platform/entities/).

    `kind` is written explicitly rather than defaulted to `service`, because
    defaulting it is the §5 defect this registry exists to fix: a datastore
    registered as a service produces wrong ownership, a wrong dependency map
    and a wrong scorecard, and nothing fails to say so. When the caller does
    not supply one, it is DERIVED from the service archetype through the same
    table the resolver uses — never guessed from the name.
    """
    name = spec["name"]
    sa = spec["service_archetype"]
    kind = spec.get("kind") or oc.entity_kind_of_service_archetype(state.policy, sa)
    entity = {
        "kind": kind,
        "name": name,
        "team": spec["team"],
        # §10: the entity model's name for `tier`.
        "criticality": spec.get("criticality") or spec["tier"],
        "service_archetype": sa,
        "description": spec["description"],
        "envs": spec.get("envs") or ["prod"],
    }
    for opt in ("platform", "domain", "region", "env", "dependencies",
                "compliance_scope", "idempotent", "links", "oncall", "slo"):
        if spec.get(opt):
            entity[opt] = spec[opt]
    header = (
        "# Registered through the MCP server (Act mode). Reviewed as a pull request\n"
        "# like every other change: the fields below are the ENTIRE developer\n"
        "# interface — profile, alert band, monitors, routing, runbooks and SLO are\n"
        "# all derived from them by platform/policy/.\n")
    return {"path": f"platform/entities/{name}.yaml",
            "content": header + yaml.safe_dump({"entity": entity}, sort_keys=False, width=100),
            "kind": "entity"}


def generate_monitor_yaml(state, spec: dict) -> dict:
    name = spec["name"]
    monitor = {"name": name, "archetype": spec["archetype"], "service": spec["service"],
               "team": spec["team"], "env": spec.get("env") or ["prod"],
               "slo": spec["slo"], "runbook": spec["runbook"], "workflow": spec["workflow"]}
    for opt in ("priority", "tier", "domain", "resource_type", "monitor_type", "detection",
                "impact_class", "query", "thresholds", "predictive", "group_by",
                "notification_profile", "summary", "impact", "justification",
                "notify_no_data", "auto_resolve_hours", "evaluation_window"):
        if spec.get(opt) is not None:
            monitor[opt] = spec[opt]
    header = (
        "# Self-service monitor, generated through the MCP server (Act mode).\n"
        "# A self-service monitor DOES create a Datadog object, unlike a service\n"
        "# registration — which is why tools/validate_monitors.py demands a written\n"
        "# justification whenever it duplicates a catalog archetype.\n")
    return {"path": f"platform/monitors/{name}.yaml",
            "content": header + yaml.safe_dump({"monitor": monitor}, sort_keys=False, width=100),
            "kind": "monitor"}


def generate_slo_yaml(state, spec: dict) -> dict:
    """A YAML BLOCK to insert under `slos:` in the shared catalog.

    Returned as an insert rather than a file because platform/policy/slos.yaml
    holds every other objective in the org; see ALLOWED_INSERT_TARGETS.
    """
    sid = spec["slo_id"]
    if not sid.startswith("slo-"):
        raise ValueError("slo_id must start with `slo-` (validate_monitors enforces it)")
    body = {sid: {
        "name": spec["name"],
        "scope": spec.get("scope", "domain"),
        "domain": spec["domain"],
        "service": spec["service"],
        "team": spec["team"],
        "type": spec.get("type", "metric"),
        "target": spec["target"],
        "timeframe": spec.get("timeframe", "30d"),
        **({"query": spec["query"]} if spec.get("query") else {}),
        **({"member_archetypes": spec["member_archetypes"]} if spec.get("member_archetypes") else {}),
        "burn_alerts": spec.get("burn_alerts", ["fast", "slow"]),
    }}
    block = yaml.safe_dump(body, sort_keys=False, width=100, default_flow_style=False)
    block = "\n".join("  " + line if line.strip() else line for line in block.splitlines())
    return {"path": "platform/policy/slos.yaml", "insert_under": "slos",
            "content": f"\n  # Added through the MCP server (Act mode).\n{block}\n",
            "kind": "slo", "slo_id": sid}


def generate_runbook(state, archetype: str) -> dict:
    """Reuse the platform's own runbook generator — not a second template."""
    arch = state.policy["archetypes"].get(archetype)
    if not arch:
        raise ValueError(f"archetype {archetype!r} does not exist")
    content = generate_runbooks.render(state.policy, archetype, arch)
    return {"path": f"platform/runbooks/{arch['runbook']}.md", "content": content,
            "kind": "runbook", "archetype": archetype,
            "note": ("Everything between the AUTOGENERATED markers is rewritten from the "
                     "catalog; sections a human appends after the end marker survive "
                     "regeneration.")}


GENERATORS = {"entity": generate_entity_yaml, "service": generate_entity_yaml, "monitor": generate_monitor_yaml,
              "slo": generate_slo_yaml}


def generate(state, kind: str, spec: dict) -> dict:
    if kind == "runbook":
        return generate_runbook(state, spec.get("archetype"))
    if kind not in GENERATORS:
        raise ValueError(f"unknown kind {kind!r}; expected one of "
                         f"{', '.join(sorted(GENERATORS))}, runbook")
    out = GENERATORS[kind](state, spec)
    assert_writable(out["path"])
    return out


# ---------------------------------------------------------------------------
# planning
# ---------------------------------------------------------------------------
def policy_plan(state, files: dict[str, str]) -> dict:
    """The plan that needs no Terraform: what these files do to the ESTATE.

    The platform's object count is a deterministic function of policy (that is
    the whole invariant), so the interesting part of a plan can be computed
    from the YAML alone. It is also the part a reviewer actually reads: "does
    this add Datadog objects, and does it stay inside the budget?"
    """
    policy = state.policy
    before = len(state.instances)
    budget = policy["global"]["cardinality"]["max_total_managed_monitors"]
    entries, errors = [], []
    created, joined = 0, 0

    for path, content in sorted(files.items()):
        assert_writable(path)
        if path.endswith(".md"):
            entries.append({"path": path, "change": "runbook content", "objects": 0})
            continue
        if path in ALLOWED_INSERT_TARGETS:
            entries.append({"path": path, "change": "SLO catalog insert",
                            "objects": "1 SLO + its burn-rate monitors"})
            continue
        preview = preview_manifest(state, content)
        errors.extend(f"{path}: {e}" for e in preview["errors"])
        created += preview["delta"].get("monitors_created", 0) or 0
        joined += preview["delta"].get("monitors_joined", 0) or 0
        entries.append({"path": path, "kind": preview["kind"], "subject": preview["subject"],
                        "valid": preview["valid"], "delta": preview["delta"]})

    lint = validate_policy.lint()
    return {
        "files": entries,
        "errors": errors,
        "policy_lint_errors": lint,
        "estate": {
            "managed_monitors_now": len(state.managed_monitors),
            "archetype_instances_now": before,
            "monitors_created_by_this_change": created,
            "monitor_groups_joined": joined,
            "budget": budget,
            "within_budget": (len(state.managed_monitors) + created) <= budget,
        },
        "environments_targeted": sorted(target_environments(files)),
    }


def target_environments(files: dict[str, str]) -> set[str]:
    """Which environments a change set reaches — the input to the env gate."""
    envs: set[str] = set()
    for path, content in files.items():
        if not path.endswith(".yaml"):
            continue
        try:
            doc = yaml.safe_load(content)
        except yaml.YAMLError:
            continue
        if not isinstance(doc, dict):
            continue
        # `entity` FIRST, and never omitted: an unrecognized registration shape
        # yields an empty env set, and an empty env set means both the
        # environment authorization and the production second-approver gate see
        # nothing to gate. A registration format the fence lets through but this
        # function does not parse is an open prod gate, not a missing feature.
        if "entity" in doc:
            envs.update(doc["entity"].get("envs") or [])
        elif "service" in doc:
            envs.update(doc["service"].get("envs") or [])
        elif "monitor" in doc:
            envs.update(doc["monitor"].get("env") or [])
        elif path in ALLOWED_INSERT_TARGETS:
            # An SLO in the shared catalog is production by construction: every
            # SLI query in slos.yaml is scoped `env:prod`.
            envs.add("prod")
    return envs


def terraform_plan(state, repo_root: Path | None = None, stack: str = "coverage") -> dict:
    """OFFLINE terraform plan, only if explicitly enabled and available.

    Two hard conditions, both fail-closed:
      * OBS_MCP_TERRAFORM=1 must be set — a plan shells out and takes minutes,
        so it is never a side effect of asking a question;
      * DD_API_KEY/DD_APP_KEY are FORCED to the literal `offline` and
        `-var datadog_validate=false` is passed, so the plan cannot reach the
        real org even when live credentials are exported in the environment.

    The credentialed plan and the monitor-validation stage belong to
    .github/workflows/ci.yml. This is the local, offline half.
    """
    if os.environ.get("OBS_MCP_TERRAFORM") != "1":
        return {"ran": False,
                "reason": "terraform planning is opt-in; set OBS_MCP_TERRAFORM=1",
                "policy_plan_is_authoritative": True}
    binary = shutil.which("terraform") or shutil.which("tofu")
    if not binary:
        return {"ran": False, "reason": "no terraform/tofu binary on PATH"}
    root = Path(repo_root or REPO_ROOT) / "stacks" / stack
    env = {**os.environ, "DD_API_KEY": "offline", "DD_APP_KEY": "offline",
           "TF_IN_AUTOMATION": "1"}
    try:
        proc = subprocess.run(
            [binary, "plan", "-input=false", "-no-color", "-var", "datadog_validate=false"],
            cwd=root, env=env, capture_output=True, text=True, timeout=900)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ran": False, "reason": f"terraform plan failed to start: {exc}"}
    tail = "\n".join(proc.stdout.splitlines()[-60:])
    return {"ran": True, "binary": binary, "stack": stack, "exit_code": proc.returncode,
            "offline": True, "output_tail": tail,
            "stderr_tail": "\n".join(proc.stderr.splitlines()[-20:])}
