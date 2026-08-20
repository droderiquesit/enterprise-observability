#!/usr/bin/env python3
"""ENTITY RESOLVER — one YAML file, one correctly-typed catalog entity.

Takes an entity document from `platform/entities/` and resolves it to the four
things the Software Catalog needs and the old service-only model could not
produce (§5, §10):

  KIND          which Datadog v3 entity kind this becomes — or that it becomes
                none at all, which is the correct answer for a VM and for a
                repository
  TAGS          the catalog facets, derived from the same policy the tag
                standard describes, so the catalog and the telemetry agree
  OWNERSHIP     team, accountable owner, on-call carrier, contacts
  SYSTEMS       `spec.components` on a system and the derived
                `spec.componentOf` on each member, plus typed `dependsOn`

Everything here is a PURE FUNCTION of (entity, policy, entities). No Datadog
credentials, no network, no filesystem — `python -m pytest tests/
test_entity_model.py` exercises the whole module offline, and so does anything
that later wants to answer "what would this entity look like?" without an apply.

The kind rules themselves are NOT in this file: they are data, in
`platform/policy/entity_kinds.yaml`, because `modules/catalog_entity` has to
apply the same rules and neither language may own a rule the other
re-implements (see the module docstring in obs_common.py).

CLI: `python entity_resolver.py [--json]` prints the resolution of every
registered entity — the census the audit asks for in §5's validation column.
"""
from __future__ import annotations

import argparse
import json
import sys

import obs_common as oc

# A reference is `kind:name`. Bare names are legal in YAML — teams write
# `dependencies: [orders-sql]` — and are resolved against the registry, never
# guessed from the string.
DEFAULT_REF_KIND = "service"


# -----------------------------------------------------------------------------
# KIND
# -----------------------------------------------------------------------------
def infer_kind(entity: dict, policy: dict) -> str | None:
    """The kind an entity has, from its declaration or its service archetype.

    Deterministic and total: `kind:` wins when present; otherwise the
    service_archetype maps through `kind_by_service_archetype`, which covers
    every value in the vocabulary. Returns None when the entity is not a
    catalog entity at all — an `infrastructure_resource` is a host, not an
    entry in the Software Catalog, and that is the §5 defect in one line.
    """
    doc = policy["entity_kinds_doc"]
    if entity.get("kind"):
        return entity["kind"]
    sa = entity.get("service_archetype")
    if sa is None:
        return None
    return doc["kind_by_service_archetype"].get(sa)


def kind_policy(kind: str | None, policy: dict) -> dict:
    return policy["entity_kinds_doc"]["entity_kinds"].get(kind or "", {})


def datadog_kind(kind: str | None, policy: dict) -> str | None:
    """Our kind → the kind actually written into the v3 document.

    Not an identity function: `frontend_app` becomes `service` because the v3
    entity union has no UI variant, and `repository` becomes nothing at all.
    """
    return kind_policy(kind, policy).get("datadog_kind")


def emits(kind: str | None, policy: dict) -> bool:
    return bool(kind_policy(kind, policy).get("emits", False))


# -----------------------------------------------------------------------------
# REFERENCES, DEPENDENCIES, SYSTEMS
# -----------------------------------------------------------------------------
def entity_ref(ref: str, entities: dict, policy: dict) -> str:
    """`orders-sql` → `datastore:orders-sql`; `queue:orders-topic` → itself.

    An unregistered name resolves to `service:<name>` — the honest default for
    something outside our catalog (`entra-id`, `warehouse`), and the same
    answer every time regardless of file order.
    """
    if ":" in ref:
        return ref
    target = entities.get(ref)
    kind = infer_kind(target, policy) if target else None
    return f"{datadog_kind(kind, policy) or DEFAULT_REF_KIND}:{ref}"


def resolve_dependencies(entity: dict, entities: dict, policy: dict) -> list[str]:
    """`spec.dependsOn`, typed and sorted.

    Empty for a kind whose v3 spec has no `dependsOn` — datastore, queue, api
    and system carry componentOf/lifecycle/tier/type only, so a dependency
    written there is discarded by the API. The schema rejects it before it gets
    this far; this function refuses to emit it in case a caller skipped the
    schema.
    """
    kind = infer_kind(entity, policy)
    if not kind_policy(kind, policy).get("spec_depends_on"):
        return []
    return sorted(entity_ref(d, entities, policy) for d in entity.get("dependencies", []))


def resolve_components(entity: dict, entities: dict, policy: dict) -> list[str]:
    """`spec.components` for a system — the declared membership, typed."""
    if not kind_policy(infer_kind(entity, policy), policy).get("spec_components"):
        return []
    return sorted(entity_ref(c, entities, policy) for c in entity.get("components", []))


def resolve_system_membership(entities: dict, policy: dict) -> dict[str, list[str]]:
    """name → the `system:` references it is a component of.

    DERIVED, never declared: membership lives on the system's `components:`
    list and nowhere else, so this is the only place the reverse edge exists.
    A member named by two systems gets both, sorted.
    """
    out: dict[str, list[str]] = {name: [] for name in entities}
    for sysname, ent in sorted(entities.items()):
        if not kind_policy(infer_kind(ent, policy), policy).get("spec_components"):
            continue
        for comp in ent.get("components", []):
            name = comp.split(":", 1)[-1]
            if name in out:
                out[name].append(f"system:{sysname}")
    return {k: sorted(set(v)) for k, v in out.items()}


# -----------------------------------------------------------------------------
# OWNERSHIP
# -----------------------------------------------------------------------------
def resolve_ownership(entity: dict, policy: dict) -> dict:
    """Team, accountable owner, on-call carrier and contacts.

    `team` is who gets routed to; `owner` is who answers for the thing
    existing; `oncall.team` is who carries the pager when that is somebody
    else (a shared datastore owned by data-engineering but carried by the DBA
    rotation). The old service registration had one field for all three.

    Only an `email` contact is emitted. Datadog's v3 contact `type` is an
    untyped string in the generated client, and the Teams channel already
    reaches people through the routing rules in modules/notification_rules —
    a second, unverified channel in the catalog would be a claim we cannot
    check.
    """
    team = entity.get("team")
    team_doc = policy["teams"].get(team, {})
    team_email = team_doc.get("email")
    owner = entity.get("owner") or team_email
    oncall_team = (entity.get("oncall") or {}).get("team") or team
    contacts = [{"name": f"{team} email", "type": "email", "contact": team_email}] \
        if team_email else []
    additional_owners = ([{"name": oncall_team, "type": "operator"}]
                         if oncall_team != team else [])
    return {
        "team": team,
        "team_email": team_email,
        "owner": owner,
        "oncall_team": oncall_team,
        "oncall_schedule": (entity.get("oncall") or {}).get("schedule"),
        "oncall_escalation_policy": (entity.get("oncall") or {}).get("escalation_policy"),
        "contacts": contacts,
        "additional_owners": additional_owners,
    }


# -----------------------------------------------------------------------------
# DERIVED POLICY VALUES
# -----------------------------------------------------------------------------
def resolve_domain(entity: dict, policy: dict) -> str:
    """Explicit `domain:`, else the archetype's domain, else `platform`.

    A queue and a system have no service archetype, which is exactly why the
    field is declarable — the fallback exists so that resolution never fails,
    not so that it can be left out.
    """
    if entity.get("domain"):
        return entity["domain"]
    sa = entity.get("service_archetype")
    if sa:
        return policy["service_archetypes"][sa]["domain"]
    return "platform"


def resolve_monitoring_profile(entity: dict, policy: dict) -> str:
    """Declared override, else the tier's profile. Same chain profile_engine
    applies to a discovered resource, so a registered entity and a discovered
    one cannot land on different profiles for the same tier."""
    if entity.get("monitoring_profile"):
        return entity["monitoring_profile"]
    return policy["tiers"][entity["criticality"]]["monitoring_profile"]


def resolve_alert_band(entity: dict, policy: dict) -> str:
    return policy["tiers_doc"]["profile_to_band"][resolve_monitoring_profile(entity, policy)]


def resolve_slo_profile(entity: dict, policy: dict) -> str:
    """Declared `slo.profile`, else the tier's `slo.scope`."""
    declared = (entity.get("slo") or {}).get("profile")
    return declared or policy["tiers"][entity["criticality"]]["slo"]["scope"]


# -----------------------------------------------------------------------------
# TAGS
# -----------------------------------------------------------------------------
def resolve_tags(entity: dict, policy: dict) -> list[str]:
    """The catalog facets, sorted so the emitted document is byte-stable.

    These are CATALOG tags, on the entity. They are not telemetry tags and
    emitting `alert_band` here does NOT close the §8 gap: the queries select on
    the band as it appears on the *metric*, which nothing writes yet. The band
    is present because a catalog entity that cannot be joined to the monitors
    covering it is half a catalog.
    """
    kind = infer_kind(entity, policy)
    tags = {
        "entity_kind": kind,
        "env": entity.get("env", "prod"),
        "team": entity["team"],
        "tier": entity["criticality"],
        "criticality": entity["criticality"],
        "domain": resolve_domain(entity, policy),
        "monitoring_profile": resolve_monitoring_profile(entity, policy),
        "alert_band": resolve_alert_band(entity, policy),
        "slo_profile": resolve_slo_profile(entity, policy),
        "managed_by": "terraform",
    }
    if kind_policy(kind, policy).get("performance_data"):
        # Only where the telemetry really is keyed by `service`. A datastore is
        # keyed by db_instance and a queue by namespace; claiming otherwise
        # produces a catalog entity whose "performance" tab is empty.
        tags["service"] = entity["name"]
    for key in ("service_archetype", "platform", "region", "compliance_scope"):
        if entity.get(key):
            tags[key] = entity[key]
    own = resolve_ownership(entity, policy)
    if own["oncall_team"] != entity["team"]:
        tags["oncall_team"] = own["oncall_team"]
    return sorted(f"{k}:{v}" for k, v in tags.items())


# -----------------------------------------------------------------------------
# FULL RESOLUTION
# -----------------------------------------------------------------------------
def resolve(entity: dict, policy: dict, entities: dict | None = None) -> dict:
    """Everything the catalog module needs about one entity, in one dict."""
    entities = entities if entities is not None else {}
    kind = infer_kind(entity, policy)
    kp = kind_policy(kind, policy)
    own = resolve_ownership(entity, policy)
    return {
        "name": entity["name"],
        "kind": kind,
        "datadog_kind": datadog_kind(kind, policy),
        "emits": emits(kind, policy),
        "not_emitted_reason": None if emits(kind, policy) else _why_not(kind, policy),
        "display_name": entity.get("display_name"),
        "description": entity.get("description", ""),
        "lifecycle": entity.get("lifecycle", "production"),
        # Datadog's own examples use "1"/"2"; this platform's vocabulary is
        # tier0..tier3 and the `tier` TAG is part of the owner-applied tag
        # contract, so spec.tier carries the same string the telemetry does.
        "tier": entity["criticality"],
        "spec_type": kp.get("spec_type_override") or entity.get("platform"),
        "domain": resolve_domain(entity, policy),
        "monitoring_profile": resolve_monitoring_profile(entity, policy),
        "alert_band": resolve_alert_band(entity, policy),
        "slo_profile": resolve_slo_profile(entity, policy),
        "tags": resolve_tags(entity, policy),
        "depends_on": resolve_dependencies(entity, entities, policy),
        "components": resolve_components(entity, entities, policy),
        "component_of": resolve_system_membership(entities, policy).get(entity["name"], []),
        "performance_data_tags": ([f"service:{entity['name']}"]
                                  if kp.get("performance_data") else []),
        "links": entity.get("links", []),
        **own,
    }


def _why_not(kind: str | None, policy: dict) -> str:
    if kind is None:
        return ("no entity kind: infrastructure resources are hosts in Datadog's "
                "infrastructure list, not Software Catalog entities")
    note = kind_policy(kind, policy).get("note", "")
    return " ".join(note.split()) or f"kind {kind!r} does not emit a Datadog entity"


def entity_document(resolved: dict) -> dict:
    """The v3 document, as `datadog_software_catalog.entity` receives it.

    modules/catalog_entity builds the SAME structure in HCL from the same
    policy file — this is the reference implementation, and what the tests
    assert against, so a change to one without the other is visible.
    """
    kp_spec: dict = {}
    if resolved["lifecycle"]:
        kp_spec["lifecycle"] = resolved["lifecycle"]
    if resolved["tier"]:
        kp_spec["tier"] = resolved["tier"]
    if resolved["spec_type"]:
        kp_spec["type"] = resolved["spec_type"]
    if resolved["depends_on"]:
        kp_spec["dependsOn"] = resolved["depends_on"]
    if resolved["components"]:
        kp_spec["components"] = resolved["components"]
    if resolved["component_of"]:
        kp_spec["componentOf"] = resolved["component_of"]

    metadata: dict = {
        "name": resolved["name"],
        "description": resolved["description"],
        "owner": resolved["team"],
        "tags": resolved["tags"],
    }
    if resolved.get("display_name"):
        metadata["displayName"] = resolved["display_name"]
    if resolved["contacts"]:
        metadata["contacts"] = resolved["contacts"]
    if resolved["additional_owners"]:
        metadata["additionalOwners"] = resolved["additional_owners"]
    if resolved["links"]:
        metadata["links"] = [{"name": link["name"], "type": link["type"],
                              "url": link["url"]} for link in resolved["links"]]

    doc: dict = {
        "apiVersion": "v3",
        "kind": resolved["datadog_kind"],
        "metadata": metadata,
        "spec": kp_spec,
    }
    if resolved["performance_data_tags"]:
        doc["datadog"] = {"performanceData": {"tags": resolved["performance_data_tags"]}}
    return doc


# -----------------------------------------------------------------------------
# VALIDATION — the mechanical form of every rule above
# -----------------------------------------------------------------------------
def validate(entity: dict, policy: dict, entities: dict) -> list[str]:
    """Everything JSON Schema cannot check: cross-references and consistency.

    Called by tools/validate_policy.py, so a bad entity fails the PR gate
    rather than the apply.
    """
    doc = policy["entity_kinds_doc"]
    name = entity.get("name", "<unnamed>")
    errs: list[str] = []

    kind = entity.get("kind")
    if kind not in doc["entity_kinds"]:
        errs.append(f"kind {kind!r} is not a declared entity kind")
        return errs
    dd = datadog_kind(kind, policy)
    if dd is not None and dd not in doc["datadog_entity_kinds"]:
        errs.append(f"kind {kind!r} maps to Datadog kind {dd!r}, which the v3 "
                    f"entity union does not accept")

    sa = entity.get("service_archetype")
    if kind_policy(kind, policy).get("requires_archetype") and not sa:
        errs.append(f"kind {kind!r} selects its monitors from packs, so it must "
                    f"declare a service_archetype")
    if sa is not None:
        if sa not in policy["service_archetypes"]:
            errs.append(f"service_archetype {sa!r} is not in the catalog")
        else:
            expected = doc["kind_by_service_archetype"][sa]
            if expected is None:
                errs.append(
                    f"service_archetype {sa!r} is not a catalog entity — a host, VM, "
                    f"ESXi host, network device or cluster node is INFRASTRUCTURE, "
                    f"covered by the host-core pack through tags. Registering it here "
                    f"would put it in the Software Catalog as a {kind!r}")
            elif expected != kind:
                errs.append(f"service_archetype {sa!r} implies kind {expected!r}, "
                            f"not {kind!r}")

    if entity.get("team") not in policy["teams"]:
        errs.append(f"team {entity.get('team')!r} is not registered in teams.yaml")
    oncall_team = (entity.get("oncall") or {}).get("team")
    if oncall_team and oncall_team not in policy["teams"]:
        errs.append(f"oncall.team {oncall_team!r} is not registered in teams.yaml")

    env = entity.get("env")
    if env and env not in entity.get("envs", []):
        errs.append(f"env {env!r} is not one of envs {entity.get('envs')}")

    domain = entity.get("domain")
    if domain and domain not in policy["domains"]:
        errs.append(f"domain {domain!r} is not in domains.yaml")

    slo_profile = (entity.get("slo") or {}).get("profile")
    if slo_profile and slo_profile not in doc["slo_profiles"]:
        errs.append(f"slo.profile {slo_profile!r} is not one of {doc['slo_profiles']}")

    if entity.get("dependencies") and not kind_policy(kind, policy).get("spec_depends_on"):
        errs.append(f"kind {kind!r} has no `dependsOn` in its v3 spec, so these "
                    f"dependencies would be silently discarded by the API")
    for comp in entity.get("components", []):
        target = comp.split(":", 1)[-1]
        if target not in entities:
            errs.append(f"component {comp!r} is not a registered entity — a system "
                        f"cannot contain something the catalog does not know")
        elif comp != entity_ref(target, entities, policy) and ":" in comp:
            errs.append(f"component {comp!r} names the wrong kind for {target!r} "
                        f"(expected {entity_ref(target, entities, policy)!r})")
    for dep in entity.get("dependencies", []):
        target = dep.split(":", 1)[-1]
        if ":" in dep and target in entities and dep != entity_ref(target, entities, policy):
            errs.append(f"dependency {dep!r} names the wrong kind for {target!r} "
                        f"(expected {entity_ref(target, entities, policy)!r})")
    if name != entity.get("name"):        # defensive; name is schema-required
        errs.append("entity has no name")
    return errs


def census(policy: dict, entities: dict) -> dict:
    """Entity-kind census — the evidence §5 asks for, computable offline."""
    rows = [resolve(e, policy, entities) for _, e in sorted(entities.items())]
    by_kind: dict[str, int] = {}
    by_datadog_kind: dict[str, int] = {}
    for r in rows:
        by_kind[r["kind"] or "none"] = by_kind.get(r["kind"] or "none", 0) + 1
        key = r["datadog_kind"] or "not emitted"
        by_datadog_kind[key] = by_datadog_kind.get(key, 0) + 1
    return {
        "total": len(rows),
        "emitted": sum(1 for r in rows if r["emits"]),
        "by_kind": by_kind,
        "by_datadog_kind": by_datadog_kind,
        "entities": rows,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true", help="print the full resolution")
    args = ap.parse_args()

    policy = oc.load_policy()
    entities = oc.load_entities()
    report = census(policy, entities)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    print(f"{report['total']} entities, {report['emitted']} emitted to Datadog")
    for r in report["entities"]:
        target = r["datadog_kind"] or f"— ({r['not_emitted_reason']})"
        print(f"  {r['name']:<28} {r['kind']:<14} → {target}")
    print("\nby Datadog kind: " + json.dumps(report["by_datadog_kind"], sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
