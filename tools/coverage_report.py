#!/usr/bin/env python3
"""Coverage & compliance report — the evidence engine for 100% coverage.

Joins the authoritative inventory + profile assignments against the live (or
fixture) monitor/SLO estate and reports, per the platform definition of
coverage:

  C1  unmonitored resources (alerting profile but no covering archetype)
  C2  resources without owners
  C3  missing or invalid required tags
  C4  services without SLOs
  C5  monitors without runbooks
  C6  monitors without Workflow Automation
  C7  monitors without on-call routing (team+severity tags)
  C8  duplicate / overlapping monitors (same dedup scope or query)
  C9  unmanaged (click-ops) monitors
  C10 resources assigned the wrong monitoring profile
  C11 high-cardinality / excessively grouped monitors
  C12 expired exceptions
  C13 SLOs with silent telemetry (broken numerators / deleted member monitors)

Modes: --live (Datadog API) or --fixtures DIR (monitors.json, slos.json).
Outputs generated/coverage_report.{json,md}; exit 1 if any check fails, so the
scheduled CI job turns red the moment governance drifts.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import obs_common as oc

# Which resource kinds each archetype class of coverage applies to — used to
# decide whether an alerting-profile resource is actually covered by a pack.
KIND_TO_ARCHETYPE_GROUPS = {
    "host": ["host-unavailable", "host-cpu-anomaly", "memory-pressure", "disk-capacity-forecast"],
    "service": ["app-error-rate-anomaly", "app-latency-degradation", "app-telemetry-loss"],
    "k8s_deployment": ["k8s-workload-unavailable"],
    "database": ["db-replication-lag", "db-connection-saturation"],
    "pipeline": ["pipeline-freshness", "pipeline-job-failure"],
    "queue": ["queue-backlog-forecast"],
    "certificate": ["certificate-expiry", "external-cert-expiry"],
    "log_source": ["security-log-source-missing"],
}

REQUIRED_MONITOR_TAGS = ["env", "service", "team", "owner", "domain", "criticality",
                         "monitoring_profile", "managed_by", "severity", "slo_id"]


def fetch_live():
    import requests
    headers = oc.dd_headers()
    site = oc.dd_site()
    monitors, page = [], 0
    while True:
        r = requests.get(f"{site}/api/v1/monitor",
                         headers=headers, params={"page": page, "page_size": 200}, timeout=60)
        r.raise_for_status()
        batch = r.json()
        monitors.extend(batch)
        if len(batch) < 200:
            break
        page += 1
    slos, offset = [], 0
    while True:
        r = requests.get(f"{site}/api/v1/slo", headers=headers,
                         params={"limit": 100, "offset": offset}, timeout=60)
        r.raise_for_status()
        batch = r.json().get("data", [])
        slos.extend(batch)
        if len(batch) < 100:
            break
        offset += 100
    return monitors, slos


def tags_map(tag_list):
    out = {}
    for t in tag_list or []:
        if ":" in t:
            k, v = t.split(":", 1)
            out.setdefault(k, v)
    return out


def run_checks(inventory, assignments, monitors, slos, policy):
    g = policy["global"]
    checks = {f"C{i}": [] for i in range(1, 14)}
    counts = {}

    amap = {a["id"]: a for a in assignments["assignments"]}
    monitor_tags = {m["id"]: tags_map(m.get("tags")) for m in monitors}
    managed = {mid for mid, t in monitor_tags.items() if t.get("managed_by") == "terraform"}
    archetypes_deployed = {t.get("archetype") for t in monitor_tags.values() if t.get("archetype")}
    envs_deployed = defaultdict(set)
    for t in monitor_tags.values():
        if t.get("archetype"):
            envs_deployed[t["archetype"]].add(t.get("env"))

    slo_services = set()
    slo_ids_seen = set()
    for s in slos:
        st = tags_map(s.get("tags", [])) if isinstance(s.get("tags"), list) else {}
        slo_ids_seen.add(st.get("slo_id"))
        for svc in s.get("service_tags") or ([st["service"]] if "service" in st else []):
            slo_services.add(svc)

    # --- Resource-side checks (bounded memory: single pass) ------------------
    services_seen = set()
    for a in assignments["assignments"]:
        svc = a.get("service")
        if svc:
            services_seen.add((svc, a["domain"]))
        if a["owner_source"] == "unowned_pool":
            checks["C2"].append(a["id"])
        bad_tags = [v for v in a["violations"] if v.startswith(("invalid_", "unknown_team"))]
        if bad_tags:
            checks["C3"].append({"id": a["id"], "violations": bad_tags})
        if a["monitoring_profile"] == "observe_only":
            continue  # explicitly not alerted — reported separately below
        expected = KIND_TO_ARCHETYPE_GROUPS.get(a["kind"], [])
        covered = any(
            arch in archetypes_deployed and a["env"] in envs_deployed.get(arch, ())
            for arch in expected
        )
        if expected and not covered:
            checks["C1"].append({"id": a["id"], "kind": a["kind"], "env": a["env"]})
        # C10: profile sanity — security-domain resources must be
        # security_sensitive; tier1 must not sit on plain standard.
        if a["domain"] == "security" and a["monitoring_profile"] != "security_sensitive":
            checks["C10"].append({"id": a["id"], "profile": a["monitoring_profile"]})
        if a["criticality"] == "tier1" and a["monitoring_profile"] == "standard":
            checks["C10"].append({"id": a["id"], "profile": "standard-but-tier1"})

    # C4: services (by SLO-carrying domains) without any SLO association.
    domain_slo_services = {policy["slos"][sid]["service"] for sid in policy["slos"]}
    for svc, domain in sorted(services_seen):
        # Platform-level SLOs cover services through their domain platform SLO;
        # a service is uncovered only if neither it nor its domain platform
        # service carries an SLO.
        domain_platform_covered = any(
            policy["slos"][sid]["domain"] == domain for sid in policy["slos"]
        )
        if svc not in slo_services and svc not in domain_slo_services and not domain_platform_covered:
            checks["C4"].append(svc)

    # --- Monitor-side checks -------------------------------------------------
    seen_dedup = {}
    seen_query = {}
    for m in monitors:
        t = monitor_tags[m["id"]]
        name = m.get("name", str(m["id"]))
        if m["id"] not in managed:
            checks["C9"].append({"id": m["id"], "name": name})
            continue  # unmanaged monitors fail C9; contract checks target managed set
        if not t.get("runbook"):
            checks["C5"].append(name)
        if not t.get("automation_ref"):
            checks["C6"].append(name)
        if not (t.get("team") and t.get("severity")):
            checks["C7"].append(name)
        missing = [rt for rt in REQUIRED_MONITOR_TAGS if rt not in t]
        if missing:
            checks["C3"].append({"id": f"monitor:{m['id']}", "violations": [f"missing_tag:{x}" for x in missing]})
        dk = t.get("dedup_key")
        if dk:
            if dk in seen_dedup:
                checks["C8"].append({"a": seen_dedup[dk], "b": name, "dedup_key": dk})
            else:
                seen_dedup[dk] = name
        q = (m.get("query") or "").strip()
        if q:
            if q in seen_query:
                checks["C8"].append({"a": seen_query[q], "b": name, "query": q[:80]})
            else:
                seen_query[q] = name
        gb = q.count(" by {") and q.split(" by {")[1].split("}")[0].count(",") + 1 or 0
        if gb > g["cardinality"]["max_group_by_keys"]:
            checks["C11"].append({"name": name, "group_keys": gb})

    # C12: expired exceptions.
    import datetime as dt
    today = dt.date.today()
    for e in policy["exceptions"]:
        expires = e["expires"]
        if isinstance(expires, str):
            expires = dt.date.fromisoformat(expires)
        if expires < today:
            checks["C12"].append(e["id"])

    # C13: SLO integrity — declared catalog SLOs missing from the org, and
    # SLOs whose custom-metric telemetry is known-silent.
    for sid, s in policy["slos"].items():
        if "datadog_id" in s and sid not in slo_ids_seen:
            checks["C13"].append({"slo_id": sid, "problem": "declared datadog_id not found in org"})
        if s.get("telemetry_dependency"):
            checks["C13"].append({"slo_id": sid, "problem": f"telemetry dependency: {s['telemetry_dependency']}"})
    for s in slos:
        status = (s.get("overall_status") or [{}])[0] if isinstance(s.get("overall_status"), list) else {}
        if status.get("error"):
            checks["C13"].append({"slo": s.get("name"), "problem": status["error"]})

    observe_only = [a["id"] for a in assignments["assignments"] if a["monitoring_profile"] == "observe_only"]
    counts = {k: len(v) for k, v in checks.items()}
    total_alertable = assignments["summary"]["total"] - len(observe_only)
    covered = total_alertable - len(checks["C1"])
    return {
        "summary": {
            "resources_total": assignments["summary"]["total"],
            "resources_observe_only": len(observe_only),
            "resources_alertable": total_alertable,
            "resources_covered": covered,
            "coverage_pct": round(100.0 * covered / total_alertable, 3) if total_alertable else 100.0,
            "monitors_total": len(monitors),
            "monitors_managed": len(managed),
            "check_counts": counts,
            "pass": all(v == 0 for v in counts.values()),
        },
        "checks": {k: v[:200] for k, v in checks.items()},  # cap detail lists
        "observe_only_sample": observe_only[:50],
    }


CHECK_TITLES = {
    "C1": "Unmonitored resources", "C2": "Resources without owners",
    "C3": "Missing/invalid tags", "C4": "Services without SLOs",
    "C5": "Monitors without runbooks", "C6": "Monitors without workflows",
    "C7": "Monitors without on-call routing", "C8": "Duplicate/overlapping monitors",
    "C9": "Unmanaged (click-ops) monitors", "C10": "Wrong monitoring profile",
    "C11": "High-cardinality monitors", "C12": "Expired exceptions",
    "C13": "SLO integrity / silent telemetry",
}


def to_markdown(report: dict) -> str:
    s = report["summary"]
    lines = [
        "# Coverage & Compliance Report", "",
        f"- Resources: **{s['resources_total']}** ({s['resources_observe_only']} observe-only by policy)",
        f"- Coverage of alertable estate: **{s['coverage_pct']}%** ({s['resources_covered']}/{s['resources_alertable']})",
        f"- Monitors: {s['monitors_total']} total, {s['monitors_managed']} Terraform-managed",
        f"- Overall: **{'PASS' if s['pass'] else 'FAIL'}**", "",
        "| Check | Findings |", "|---|---|",
    ]
    for cid, title in CHECK_TITLES.items():
        lines.append(f"| {cid} {title} | {s['check_counts'].get(cid, 0)} |")
    lines.append("")
    for cid, items in report["checks"].items():
        if items:
            lines.append(f"## {cid} {CHECK_TITLES[cid]} ({len(items)} shown, capped at 200)")
            for it in items[:20]:
                lines.append(f"- `{json.dumps(it) if not isinstance(it, str) else it}`")
            lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--live", action="store_true")
    mode.add_argument("--fixtures", type=Path)
    ap.add_argument("--inventory", type=Path, default=oc.GENERATED_DIR / "inventory.json")
    ap.add_argument("--assignments", type=Path, default=oc.GENERATED_DIR / "assignments.json")
    ap.add_argument("--out-json", type=Path, default=oc.GENERATED_DIR / "coverage_report.json")
    ap.add_argument("--out-md", type=Path, default=oc.GENERATED_DIR / "coverage_report.md")
    args = ap.parse_args()

    inventory = json.loads(args.inventory.read_text())
    assignments = json.loads(args.assignments.read_text())
    if args.live:
        monitors, slos = fetch_live()
    else:
        monitors = json.loads((args.fixtures / "monitors.json").read_text())
        slos = json.loads((args.fixtures / "slos.json").read_text())

    policy = oc.load_policy()
    report = run_checks(inventory, assignments, monitors, slos, policy)
    oc.write_json(args.out_json, report)
    args.out_md.parent.mkdir(parents=True, exist_ok=True)
    args.out_md.write_text(to_markdown(report))
    print(json.dumps(report["summary"], indent=2))
    return 0 if report["summary"]["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
