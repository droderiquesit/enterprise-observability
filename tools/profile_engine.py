#!/usr/bin/env python3
"""Profile engine: assign owner, environment, criticality, and monitoring
profile to every inventory resource, by policy — no per-team configuration.

Resolution order per resource (mirrors the configuration hierarchy):
  1. environment  → tags.env (normalized); invalid values flagged.
  2. criticality  → tags.criticality if valid, else tier default by env.
  3. owner/team   → tags.team → service-catalog team → domain owner team
                    → unowned pool (flagged violation).
  4. profile      → approved exception → security/regulated upgrades →
                    tier default → environment default.

Output:
  generated/assignments.json           per-resource assignment + reasons
  generated/services.auto.tfvars.json  service-catalog input for Terraform
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from collections import Counter
from pathlib import Path

import obs_common as oc

KIND_DOMAIN = {
    "host": "infrastructure",
    "service": "application",
    "k8s_deployment": "cloud",
    "database": "data",
    "pipeline": "data",
    "queue": "cloud",
    "certificate": "security",
    "log_source": "security",
}


def _active_exceptions(policy, today: dt.date):
    active = []
    for e in policy["exceptions"]:
        expires = e["expires"]
        if isinstance(expires, str):
            expires = dt.date.fromisoformat(expires)
        if expires >= today:
            active.append(e)
    return active


def assign(inventory: dict, policy: dict, today: dt.date | None = None) -> dict:
    today = today or oc.utcnow().date()
    envs = policy["environments"]
    tiers = policy["tiers"]
    valid_env = set(policy["global"]["tag_vocabulary"]["env"])
    valid_tier = set(policy["global"]["tag_vocabulary"]["criticality"])
    unowned_team = policy["teams"]["unowned_pool"]["team"]
    exceptions = _active_exceptions(policy, today)
    svc_exceptions = {
        (e["scope"].get("service"), e["scope"].get("env")): e
        for e in exceptions
        if e["control"] == "monitoring_profile" and "service" in e["scope"]
    }

    assignments = []
    for r in inventory["resources"]:
        tags = r.get("tags", {})
        violations = []

        env = r.get("env") or tags.get("env")
        if env not in valid_env:
            violations.append(f"invalid_env:{env}")
            env = "prod"  # safest assumption: treat unknown as prod until fixed

        tier = tags.get("criticality")
        if tier not in valid_tier:
            if tier:
                violations.append(f"invalid_criticality:{tier}")
            tier = "tier2" if env == "prod" else "tier3"

        team = r.get("team") or tags.get("team")
        owner_source = "tag"
        if not team:
            domain = KIND_DOMAIN.get(r["kind"], "application")
            team = policy["domains"][domain]["owner_team"]
            owner_source = "domain_default"
        if not team:
            team = unowned_team
            owner_source = "unowned_pool"
        if owner_source != "tag":
            violations.append(f"owner_inferred:{owner_source}")
        if team not in policy["teams"]["teams"]:
            violations.append(f"unknown_team:{team}")
            team = unowned_team
            owner_source = "unowned_pool"

        domain = KIND_DOMAIN.get(r["kind"], "application")

        # Profile resolution (highest layer first).
        exc = svc_exceptions.get((r.get("service"), env)) or svc_exceptions.get((r.get("service"), None))
        reason = None
        if exc:
            profile = exc["value"]
            reason = f"exception:{exc['id']}"
        elif envs[env]["default_profile"] == "observe_only":
            profile = "observe_only"
            reason = envs[env].get("observe_only_reason", "environment policy")
        elif domain == "security":
            profile = "security_sensitive"
        elif tags.get("compliance_scope"):
            profile = "regulated"
        elif tier == "tier4":
            profile = "observe_only"
            reason = tiers["tier4"].get("observe_only_reason", "tier policy")
        elif tier == "tier1":
            profile = "critical"
        else:
            profile = tiers[tier]["default_profile"]

        assignments.append(
            {
                "id": r["id"],
                "kind": r["kind"],
                "service": r.get("service"),
                "env": env,
                "region": r.get("region", "global"),
                "domain": domain,
                "team": team,
                "owner": team,
                "owner_source": owner_source,
                "criticality": tier,
                "monitoring_profile": profile,
                "observe_only_reason": reason if profile == "observe_only" else None,
                "violations": violations,
            }
        )

    summary = {
        "total": len(assignments),
        "by_profile": dict(Counter(a["monitoring_profile"] for a in assignments)),
        "by_env": dict(Counter(a["env"] for a in assignments)),
        "unowned": sum(1 for a in assignments if a["owner_source"] == "unowned_pool"),
        "with_violations": sum(1 for a in assignments if a["violations"]),
    }
    return {"generated_at": oc.utcnow().isoformat(), "summary": summary, "assignments": assignments}


def service_catalog_tfvars(result: dict, policy: dict, limit: int | None = None) -> dict:
    """Aggregate assignments to per-service catalog entries for Terraform."""
    services: dict[str, dict] = {}
    for a in result["assignments"]:
        svc = a.get("service")
        if not svc or a["env"] not in ("prod", "staging"):
            continue
        cur = services.get(svc)
        # Strictest tier wins across a service's resources.
        if cur is None or a["criticality"] < cur["tier"]:
            team = a["team"]
            email = policy["teams"]["teams"].get(team, {}).get("email", "unknown@acme.example")
            services[svc] = {
                "team": team,
                "owner_email": email,
                "description": f"Auto-onboarded from inventory ({a['kind']}).",
                "tier": a["criticality"],
                "domain": a["domain"],
                "monitoring_profile": a["monitoring_profile"],
                "env": a["env"],
                "links": [],
            }
    if limit:
        services = dict(sorted(services.items())[:limit])
    return {"services": services}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--inventory", type=Path, default=oc.GENERATED_DIR / "inventory.json")
    ap.add_argument("--out", type=Path, default=oc.GENERATED_DIR / "assignments.json")
    ap.add_argument("--tfvars-out", type=Path, default=oc.GENERATED_DIR / "services.auto.tfvars.json")
    ap.add_argument("--catalog-limit", type=int, default=500,
                    help="Cap service-catalog entries per apply batch (API-friendly rollout).")
    args = ap.parse_args()

    inventory = json.loads(args.inventory.read_text())
    policy = oc.load_policy()
    result = assign(inventory, policy)
    oc.write_json(args.out, result)
    oc.write_json(args.tfvars_out, service_catalog_tfvars(result, policy, args.catalog_limit))
    print(json.dumps(result["summary"], indent=2))


if __name__ == "__main__":
    main()
