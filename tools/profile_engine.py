#!/usr/bin/env python3
"""PROFILE ENGINE — zero-touch onboarding, implemented.

Assigns every discovered resource an owner, environment, tier, monitoring
profile and ALERT BAND from policy alone. The alert_band it produces is the tag
the platform's monitors actually select on, so this is the component that turns
"a correctly tagged service" into "a monitored service" with no human step.

Resolution order (mirrors the configuration hierarchy):
  1. environment       tags.env, normalized; invalid values flagged, not dropped
  2. service archetype tags.service_archetype → which packs apply
  3. tier              tags.tier if valid, else inferred from environment
  4. owner             tags.team → registry → domain default → unowned pool
  5. profile           approved exception → overlay → tier default → env default
  6. band              profile → alert_band (what monitors select on)

Nothing is ever silently skipped. A resource that cannot be resolved gets the
safest assignment plus a recorded violation, because an unmonitored resource
that nobody knows about is the failure this whole platform exists to prevent.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import obs_common as oc

# Which technology domain a resource kind belongs to when no service archetype
# is declared. Used only as a fallback — the tag is authoritative.
KIND_DOMAIN = {
    "host": "infrastructure",
    "vm": "infrastructure",
    "service": "application",
    "api": "api",
    "kube_deployment": "kubernetes",
    "kube_node": "kubernetes",
    "database": "database",
    "pipeline": "data",
    "queue": "messaging",
    "certificate": "security",
    "log_source": "security",
    "esxi_host": "vmware",
    "azure_resource": "cloud",
    "network_device": "network",
    "batch_job": "integration",
    "synthetic_check": "saas",
}

KIND_SERVICE_ARCHETYPE = {
    "host": "infrastructure_resource",
    "vm": "infrastructure_resource",
    "esxi_host": "infrastructure_resource",
    "network_device": "infrastructure_resource",
    "kube_node": "infrastructure_resource",
    "database": "datastore",
    "queue": "event_consumer",
    "pipeline": "batch_job",
    "batch_job": "batch_job",
    "synthetic_check": "external_endpoint",
    "log_source": "platform_service",
    "certificate": "platform_service",
    "azure_resource": "platform_service",
    "kube_deployment": "worker",
    "service": "api",
    "api": "api",
}


def _exception_index(policy: dict) -> dict:
    idx = {}
    for e in policy["exceptions"]:
        if e["control"] != "monitoring_profile":
            continue
        scope = e["scope"]
        idx[(scope.get("service"), scope.get("env"))] = e
    return idx


def assign(inventory: dict, policy: dict, services: dict | None = None) -> dict:
    services = services if services is not None else {}
    vocab = policy["global"]["tag_vocabulary"]
    envs = policy["environments"]
    tiers = policy["tiers"]
    profile_to_band = policy["tiers_doc"]["profile_to_band"]
    valid_env = set(vocab["env"])
    valid_tier = set(vocab["tier"])
    valid_sa = set(vocab["service_archetype"])
    unowned_team = policy["teams_doc"]["unowned_pool"]["team"]
    exceptions = _exception_index(policy)

    assignments = []
    for r in inventory["resources"]:
        tags = r.get("tags", {})
        violations: list[str] = []

        # --- 1. environment ---------------------------------------------------
        env = r.get("env") or tags.get("env")
        if env not in valid_env:
            violations.append(f"invalid_env:{env}")
            # Treat an unknown environment as production. Being too loud about a
            # dev box is recoverable; being silent about a prod box is not.
            env = "prod"

        # --- 2. service archetype --------------------------------------------
        sa = tags.get("service_archetype")
        if sa not in valid_sa:
            if sa:
                violations.append(f"invalid_service_archetype:{sa}")
            sa = KIND_SERVICE_ARCHETYPE.get(r["kind"], "infrastructure_resource")
            violations.append("service_archetype_inferred")
        domain = policy["service_archetypes"].get(sa, {}).get(
            "domain", KIND_DOMAIN.get(r["kind"], "application")
        )

        # --- 3. tier ----------------------------------------------------------
        svc = r.get("service")
        registered = services.get(svc) if svc else None
        tier = tags.get("tier")
        if registered and registered.get("tier") in valid_tier:
            # A registration is a reviewed business decision and outranks a tag.
            tier = registered["tier"]
        elif tier not in valid_tier:
            if tier:
                violations.append(f"invalid_tier:{tier}")
            tier = "tier2" if env == "prod" else "tier3"
            violations.append("tier_inferred")

        # --- 4. ownership -----------------------------------------------------
        owner_source = "tag"
        team = tags.get("team") or r.get("team")
        if registered and registered.get("team"):
            team, owner_source = registered["team"], "registry"
        if not team:
            team = policy["domains"][domain]["owner_team"]
            owner_source = "domain_default"
        if team not in policy["teams"]:
            violations.append(f"unknown_team:{team}")
            team, owner_source = unowned_team, "unowned_pool"
        if owner_source in ("domain_default", "unowned_pool"):
            violations.append(f"owner_inferred:{owner_source}")

        # --- 5. monitoring profile -------------------------------------------
        exc = exceptions.get((svc, env)) or exceptions.get((svc, None))
        reason = None
        if exc:
            profile = exc["value"]
            reason = f"approved exception {exc['id']}: {exc['reason'].strip().splitlines()[0]}"
        elif not envs[env]["alerting"]:
            profile = "observe_only"
            reason = envs[env].get("observe_only_reason", f"{env} environment policy")
        elif domain == "security":
            profile = "regulated"          # security overlay on the critical band
        elif tags.get("compliance_scope") or (registered or {}).get("compliance_scope"):
            profile = "regulated"
        else:
            profile = tiers[tier]["monitoring_profile"]
            if profile == "observe_only":
                reason = tiers[tier].get("observe_only_reason", f"{tier} policy")
            # QA only ever runs the baseline packs, whatever the tier says.
            if env == "qa" and profile in ("standard", "critical"):
                profile = "baseline"

        band = profile_to_band[profile]

        assignments.append(
            {
                "id": r["id"],
                "kind": r["kind"],
                "service": svc,
                "service_archetype": sa,
                "env": env,
                "region": r.get("region", "global"),
                "domain": domain,
                "team": team,
                "owner": team,
                "owner_source": owner_source,
                "tier": tier,
                "monitoring_profile": profile,
                "alert_band": band,
                "support_model": tiers[tier]["support_model"],
                "observe_only_reason": reason if profile == "observe_only" else None,
                "registered": bool(registered),
                "violations": violations,
            }
        )

    summary = {
        "total": len(assignments),
        "by_profile": dict(Counter(a["monitoring_profile"] for a in assignments)),
        "by_band": dict(Counter(a["alert_band"] for a in assignments)),
        "by_env": dict(Counter(a["env"] for a in assignments)),
        "by_tier": dict(Counter(a["tier"] for a in assignments)),
        "by_service_archetype": dict(Counter(a["service_archetype"] for a in assignments)),
        "unowned": sum(1 for a in assignments if a["owner_source"] == "unowned_pool"),
        "registered": sum(1 for a in assignments if a["registered"]),
        "with_violations": sum(1 for a in assignments if a["violations"]),
        "alertable": sum(1 for a in assignments if a["alert_band"] != "none"),
        "observe_only": sum(1 for a in assignments if a["alert_band"] == "none"),
    }
    return {
        "generated_at": oc.utcnow().isoformat(),
        "summary": summary,
        "assignments": assignments,
    }


def service_catalog_tfvars(result: dict, policy: dict, limit: int | None = None) -> dict:
    """Aggregate to per-service catalog entries for Terraform."""
    tier_rank = {"tier0": 0, "tier1": 1, "tier2": 2, "tier3": 3}
    services: dict[str, dict] = {}
    for a in result["assignments"]:
        svc = a.get("service")
        if not svc or a["env"] not in ("prod", "stage"):
            continue
        cur = services.get(svc)
        # The strictest tier across a service's resources wins.
        if cur is None or tier_rank[a["tier"]] < tier_rank[cur["tier"]]:
            email = policy["teams"].get(a["team"], {}).get("email", "unknown@acme.example")
            services[svc] = {
                "team": a["team"],
                "owner_email": email,
                "description": f"Discovered from inventory ({a['kind']}, {a['service_archetype']}).",
                "tier": a["tier"],
                "domain": a["domain"],
                "monitoring_profile": a["monitoring_profile"],
                "env": a["env"],
                "links": [],
            }
    if limit:
        services = dict(sorted(services.items())[:limit])
    return {"services": services}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--inventory", type=Path, default=oc.GENERATED_DIR / "inventory.json")
    ap.add_argument("--out", type=Path, default=oc.GENERATED_DIR / "assignments.json")
    ap.add_argument("--tfvars-out", type=Path,
                    default=oc.GENERATED_DIR / "services.auto.tfvars.json")
    ap.add_argument("--catalog-limit", type=int, default=500,
                    help="Cap catalog entries per apply batch (API-friendly rollout).")
    args = ap.parse_args()

    inventory = json.loads(args.inventory.read_text())
    policy = oc.load_policy()
    services = oc.load_services()
    result = assign(inventory, policy, services)
    oc.write_json(args.out, result)
    oc.write_json(args.tfvars_out, service_catalog_tfvars(result, policy, args.catalog_limit))
    print(json.dumps(result["summary"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
