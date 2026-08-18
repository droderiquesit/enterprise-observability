#!/usr/bin/env python3
"""AUTHORITATIVE RESOURCE INVENTORY.

Coverage is only meaningful against a known denominator. This builds it.

Sources (--live): Datadog hosts, service catalog, Kubernetes and cloud resource
metadata, plus optional CMDB/cloud exports dropped into
platform/inventory-sources/*.json.

--synthetic N generates a deterministic N-resource estate for scale testing at
the design target (100,000+ services / 1,000,000+ resources), including a
deliberate ~3% of badly-tagged resources so the governance paths are exercised
rather than assumed.

Output: generated/inventory.json — the ONLY input to the profile engine and the
coverage report, so there is exactly one denominator in the system.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from pathlib import Path

import obs_common as oc

# kind, service_archetype, weight (resources of this kind per 20 resources)
KINDS = [
    ("host", "infrastructure_resource", 5),
    ("service", "api", 3),
    ("kube_deployment", "worker", 3),
    ("database", "datastore", 2),
    ("pipeline", "batch_job", 2),
    ("queue", "event_consumer", 2),
    ("azure_resource", "platform_service", 1),
    ("certificate", "platform_service", 1),
    ("log_source", "platform_service", 1),
]


def fetch_live() -> list[dict]:
    headers = oc.dd_headers()
    site = oc.dd_site()
    resources: list[dict] = []

    # --- hosts ---------------------------------------------------------------
    start, page = 0, 1000
    while True:
        r = oc.dd_request("GET", f"{site}/api/v1/hosts", headers=headers,
                          params={"start": start, "count": page})
        r.raise_for_status()
        hosts = r.json().get("host_list", [])
        for h in hosts:
            tags = oc.tags_to_map(sum(h.get("tags_by_source", {}).values(), []))
            resources.append({
                "id": f"host:{h['name']}",
                "kind": "host",
                "name": h["name"],
                "env": tags.get("env", "unknown"),
                "region": tags.get("region", "unknown"),
                "service": tags.get("service"),
                "team": tags.get("team"),
                "tags": tags,
                "source": "datadog_hosts",
            })
        if len(hosts) < page:
            break
        start += page

    # --- service catalog -----------------------------------------------------
    page_number = 0
    while True:
        r = oc.dd_request("GET", f"{site}/api/v2/services/definitions",
                          headers=headers,
                          params={"page[size]": 100, "page[number]": page_number})
        r.raise_for_status()
        batch = r.json().get("data", [])
        for svc in batch:
            schema = svc.get("attributes", {}).get("schema", {})
            name = schema.get("dd-service") or svc.get("id")
            tags = oc.tags_to_map(schema.get("tags", []))
            resources.append({
                "id": f"service:{name}",
                "kind": "service",
                "name": name,
                "env": tags.get("env", "prod"),
                "region": tags.get("region", "global"),
                "service": name,
                "team": schema.get("team") or tags.get("team"),
                "tags": tags,
                "source": "service_catalog",
            })
        if len(batch) < 100:
            break
        page_number += 1

    # --- additional exports (CMDB, cloud inventory, Kubernetes) --------------
    src_dir = oc.PLATFORM_DIR / "inventory-sources"
    if src_dir.is_dir():
        for f in sorted(src_dir.glob("*.json")):
            resources.extend(json.loads(f.read_text()))
    return resources


def synthesize(n_resources: int, seed: int = 7) -> list[dict]:
    """Deterministic synthetic estate at the design target."""
    rng = random.Random(seed)
    envs = ["prod", "prod", "prod", "prod", "stage", "qa", "dev", "dev"]
    regions = ["eastus2", "centralus", "westeurope", "onprem-dc1", "onprem-dc2"]
    teams = list(oc.load_policy()["teams"].keys())
    tiers = ["tier0", "tier1", "tier1", "tier2", "tier2", "tier2", "tier3", "tier3"]
    n_services = max(1, n_resources // 12)
    weighted = [k for k in KINDS for _ in range(k[2])]

    resources = []
    for i in range(n_resources):
        kind, sa, _ = weighted[i % len(weighted)]
        svc = f"svc-{i % n_services:06d}"
        env = envs[i % len(envs)]
        # ~3% of the estate is deliberately broken so the governance paths are
        # exercised by the tests rather than assumed to work.
        broken = rng.random() < 0.03
        tags = {
            "env": env,
            "region": regions[i % len(regions)],
            "service": svc,
            "tier": tiers[i % len(tiers)],
            "service_archetype": sa,
            "cluster": f"cluster-{i % 200:03d}",
        }
        if not broken:
            tags["team"] = teams[i % len(teams)]
        if rng.random() < 0.02:
            tags["env"] = "production"        # invalid vocabulary value, on purpose
        if rng.random() < 0.01:
            tags["tier"] = "gold"             # invalid tier, on purpose
        resources.append({
            "id": f"{kind}:{hashlib.md5(f'{kind}{i}'.encode()).hexdigest()[:12]}",
            "kind": kind,
            "name": f"{kind}-{i:07d}",
            "env": tags["env"],
            "region": tags["region"],
            "service": svc,
            "team": tags.get("team"),
            "tags": tags,
            "source": "synthetic",
        })
    return resources


def main() -> int:
    ap = argparse.ArgumentParser()
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--live", action="store_true")
    mode.add_argument("--synthetic", type=int, metavar="N")
    ap.add_argument("--out", type=Path, default=oc.GENERATED_DIR / "inventory.json")
    args = ap.parse_args()

    resources = fetch_live() if args.live else synthesize(args.synthetic)

    inventory = {
        "generated_at": oc.utcnow().isoformat(),
        "resource_count": len(resources),
        "service_count": len({r["service"] for r in resources if r.get("service")}),
        "resources": resources,
    }
    oc.write_json(args.out, inventory)
    print(f"inventory: {inventory['resource_count']} resources, "
          f"{inventory['service_count']} services -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
