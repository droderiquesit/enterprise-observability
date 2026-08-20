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
  7. telemetry         available sources → what that band can ACTUALLY deliver

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

import applicability
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


# =============================================================================
# BEGIN telemetry availability (§16/§38) — step 7 of the resolution order.
#
# A monitoring profile is a PROMISE: "these signal classes are watched on this
# resource". Until now the promise was made from tags alone, so a tier0 service
# with no APM instrumentation resolved to `critical` and got a full pack of
# monitors that could never produce a series. Every one of them reports OK, so
# the resource is indistinguishable from a genuinely healthy one — the profile
# claimed coverage it could not deliver, and nothing said so.
#
# This step does not change how a profile is CHOSEN. It checks what the chosen
# profile can actually deliver against the telemetry the resource emits, and:
#
#   * records the shortfall on every assignment (telemetry_coverage_pct plus
#     the named missing sources), so the gap is a number somebody owns;
#   * demotes to observe_only ONLY when nothing at all can fire, because an
#     alerting profile whose every monitor is silent is a false claim of
#     coverage, and observe_only is the one profile that states the truth
#     ("collected, not alerted") and demands a recorded reason.
#
# Partial gaps deliberately do NOT demote: three working monitors out of eight
# is real coverage, and quietly dropping the resource to observe_only would
# throw away the three that work.
#
# telemetry=None leaves every assignment unchanged and coverage null. Absence of
# a telemetry survey is not evidence that telemetry is absent, and guessing
# either way here would be a fabricated input to a governance report.
# =============================================================================
def _telemetry_index(telemetry: dict | None) -> dict | None:
    """Estate description → {estate_sources, by_id, by_service}.

    Accepts the same document tools/applicability.py reads (see
    tests/fixtures/telemetry_estate.json) so there is one description of what
    the estate emits, not one per consumer.
    """
    if not telemetry:
        return None
    by_id, by_service = {}, {}
    for e in telemetry.get("entities", []) or []:
        sources = set(e.get("telemetry", []) or [])
        if e.get("id"):
            by_id[e["id"]] = sources
        # Indexed by service too because a host and the service it runs share
        # instrumentation the inventory records against only one of them.
        if e.get("service"):
            by_service.setdefault(e["service"], set()).update(sources)
    return {
        "estate": set(telemetry.get("telemetry", []) or []),
        "by_id": by_id,
        "by_service": by_service,
    }


def _telemetry_for(tel: dict, resource_id: str, service: str | None) -> set[str]:
    return (tel["estate"]
            | tel["by_id"].get(resource_id, set())
            | tel["by_service"].get(service, set()))


# END telemetry availability (§16/§38)
# =============================================================================


def assign(inventory: dict, policy: dict, services: dict | None = None,
           telemetry: dict | None = None) -> dict:
    services = services if services is not None else {}
    tel = _telemetry_index(telemetry)
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

        # --- 2b. platform — WHAT IT RUNS ON, which selects the technology packs
        # A registration is a reviewed decision and outranks a tag, the same
        # precedence tier uses below. Neither present means None, and None
        # means the engine-agnostic packs alone: a datastore whose technology
        # nothing records must not be measured against SQL Server, Cosmos and
        # Snowflake at once and reported as covering all three.
        platform = None
        _reg = services.get(r.get("service")) if r.get("service") else None
        if _reg and _reg.get("platform"):
            platform = _reg["platform"]
        elif tags.get("platform"):
            platform = tags["platform"]

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
            # QA and DEV only ever run the baseline packs, whatever the tier
            # says. Dev used to land on observe_only via `alerting: false`;
            # now that dev alerts, the same clamp that keeps QA quiet is what
            # keeps dev to liveness and telemetry health.
            if env in ("qa", "dev") and profile in ("standard", "critical"):
                profile = "baseline"

        band = profile_to_band[profile]

        # --- 7. telemetry availability ---------------------------------------
        telemetry_available: list[str] | None = None
        telemetry_missing: list[str] = []
        telemetry_coverage: float | None = None
        if tel is not None:
            sources = _telemetry_for(tel, r["id"], svc)
            verdict = applicability.evaluate_archetypes(
                policy, applicability.pack_archetypes(policy, sa, platform), sources)
            n_ok = len(verdict["applicable"])
            n_blocked = len(verdict["blocked_by_missing_telemetry"])
            telemetry_available = sorted(sources)
            telemetry_missing = sorted(
                {m for row in verdict["blocked_by_missing_telemetry"]
                 for m in row["missing"]})
            telemetry_coverage = applicability.coverage_pct(n_ok, n_blocked)
            if telemetry_missing:
                violations.append(
                    "telemetry_missing:" + ",".join(telemetry_missing))
            if profile != "observe_only" and n_ok == 0 and n_blocked > 0:
                profile = "observe_only"
                band = profile_to_band[profile]
                reason = (
                    "no telemetry source available for any monitor in this "
                    f"resource's packs — missing {', '.join(telemetry_missing)}. "
                    "An alerting profile here would report OK on monitors that "
                    "can never evaluate."
                )

        assignments.append(
            {
                "id": r["id"],
                "kind": r["kind"],
                "service": svc,
                "service_archetype": sa,
                "platform": platform,
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
                "telemetry_available": telemetry_available,
                "telemetry_missing": telemetry_missing,
                "telemetry_coverage_pct": telemetry_coverage,
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
        # Null when no telemetry survey was supplied — see _telemetry_index.
        "telemetry_surveyed": sum(
            1 for a in assignments if a["telemetry_coverage_pct"] is not None),
        "telemetry_blocked": sum(
            1 for a in assignments if a["telemetry_missing"]),
        "telemetry_demoted_to_observe_only": sum(
            1 for a in assignments
            if a["telemetry_coverage_pct"] == 0.0 and a["telemetry_missing"]),
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
    ap.add_argument("--telemetry", type=Path, default=None,
                    help="Estate telemetry survey (see tests/fixtures/"
                         "telemetry_estate.json). Omit it and every profile is "
                         "resolved from tags alone, with telemetry coverage "
                         "reported as null rather than assumed.")
    args = ap.parse_args()

    inventory = json.loads(args.inventory.read_text())
    policy = oc.load_policy()
    services = oc.load_services()
    telemetry = json.loads(args.telemetry.read_text()) if args.telemetry else None
    result = assign(inventory, policy, services, telemetry)
    oc.write_json(args.out, result)
    oc.write_json(args.tfvars_out, service_catalog_tfvars(result, policy, args.catalog_limit))
    print(json.dumps(result["summary"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
