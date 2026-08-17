#!/usr/bin/env python3
"""Build the authoritative resource/service inventory.

Sources (--live): Datadog hosts API, Service Catalog, plus optional CMDB/cloud
exports dropped into platform/inventory-sources/*.json. Offline (--fixtures):
JSON fixtures with identical shape. --synthetic N generates a deterministic
N-resource estate for scale testing (100k services / 1M+ resources).

Output: generated/inventory.json — every downstream stage (profile engine,
coverage report) consumes ONLY this file, making coverage measurable from a
single authoritative inventory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path

import obs_common as oc

KINDS = [
    # kind, domain, resource_type, per-service weight
    ("host", "infrastructure", "host", 4),
    ("k8s_deployment", "cloud", "kube_deployment", 3),
    ("database", "data", "db_instance", 1),
    ("pipeline", "data", "pipeline", 1),
    ("queue", "cloud", "namespace", 1),
    ("certificate", "security", "check_id", 1),
    ("log_source", "security", "log_source", 1),
]


def fetch_live() -> list[dict]:
    import requests

    headers = oc.dd_headers()
    site = oc.dd_site()
    resources: list[dict] = []

    # Hosts
    start, page = 0, 1000
    while True:
        r = requests.get(
            f"{site}/api/v1/hosts",
            headers=headers,
            params={"start": start, "count": page},
            timeout=60,
        )
        r.raise_for_status()
        hosts = r.json().get("host_list", [])
        for h in hosts:
            tags = _tags_to_map(sum(h.get("tags_by_source", {}).values(), []))
            resources.append(
                {
                    "id": f"host:{h['name']}",
                    "kind": "host",
                    "name": h["name"],
                    "env": tags.get("env", "unknown"),
                    "region": tags.get("region", "unknown"),
                    "service": tags.get("service"),
                    "team": tags.get("team"),
                    "tags": tags,
                    "source": "datadog_hosts",
                }
            )
        if len(hosts) < page:
            break
        start += page

    # Service catalog (v2 definitions)
    r = requests.get(
        f"{site}/api/v2/services/definitions",
        headers=headers,
        params={"page[size]": 100},
        timeout=60,
    )
    r.raise_for_status()
    for svc in r.json().get("data", []):
        schema = svc.get("attributes", {}).get("schema", {})
        name = schema.get("dd-service") or svc.get("id")
        tags = _tags_to_map(schema.get("tags", []))
        resources.append(
            {
                "id": f"service:{name}",
                "kind": "service",
                "name": name,
                "env": tags.get("env", "prod"),
                "region": tags.get("region", "global"),
                "service": name,
                "team": schema.get("team"),
                "tags": tags,
                "source": "service_catalog",
            }
        )

    # Optional additional exports (CMDB, cloud inventories)
    src_dir = oc.REPO_ROOT / "platform" / "inventory-sources"
    if src_dir.is_dir():
        for f in sorted(src_dir.glob("*.json")):
            resources.extend(json.loads(f.read_text()))
    return resources


def _tags_to_map(tags: list[str]) -> dict:
    out = {}
    for t in tags:
        if ":" in t:
            k, v = t.split(":", 1)
            out.setdefault(k, v)
    return out


def synthesize(n_resources: int, seed: int = 7) -> list[dict]:
    """Deterministic synthetic estate: ~100k services across 1M+ resources."""
    rng = random.Random(seed)
    envs = ["prod", "prod", "prod", "staging", "dev", "sandbox"]
    regions = ["eastus2", "centralus", "westeurope", "onprem-dc1", "onprem-dc2"]
    teams = list(oc.load_policy()["teams"]["teams"].keys())
    n_services = max(1, n_resources // 12)
    weighted_kinds = [k for k in KINDS for _ in range(k[3])]
    resources = []
    for i in range(n_resources):
        kind, domain, rtype, _ = weighted_kinds[i % len(weighted_kinds)]
        svc = f"svc-{i % n_services:06d}"
        env = envs[i % len(envs)]
        # ~3% of resources deliberately missing ownership/tags to exercise
        # the unowned/invalid-tag detection paths.
        broken = rng.random() < 0.03
        tags = {
            "env": env,
            "region": regions[i % len(regions)],
            "service": svc,
            "criticality": f"tier{1 + (i % 4)}",
        }
        if not broken:
            tags["team"] = teams[i % len(teams)]
            tags["owner"] = tags["team"]
        if rng.random() < 0.02:
            tags["env"] = "production"  # invalid vocabulary value on purpose
        resources.append(
            {
                "id": f"{kind}:{hashlib.md5(f'{kind}{i}'.encode()).hexdigest()[:12]}",
                "kind": kind,
                "name": f"{kind}-{i:07d}",
                "env": tags["env"],
                "region": tags["region"],
                "service": svc,
                "team": tags.get("team"),
                "tags": tags,
                "source": "synthetic",
            }
        )
    return resources


def main() -> None:
    ap = argparse.ArgumentParser()
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--live", action="store_true")
    mode.add_argument("--fixtures", type=Path)
    mode.add_argument("--synthetic", type=int, metavar="N")
    ap.add_argument("--out", type=Path, default=oc.GENERATED_DIR / "inventory.json")
    args = ap.parse_args()

    if args.live:
        resources = fetch_live()
    elif args.fixtures:
        resources = json.loads((args.fixtures / "inventory.json").read_text())["resources"]
    else:
        resources = synthesize(args.synthetic)

    inventory = {
        "generated_at": oc.utcnow().isoformat(),
        "resource_count": len(resources),
        "service_count": len({r["service"] for r in resources if r.get("service")}),
        "resources": resources,
    }
    oc.write_json(args.out, inventory)
    print(f"inventory: {inventory['resource_count']} resources, {inventory['service_count']} services -> {args.out}")


if __name__ == "__main__":
    main()
