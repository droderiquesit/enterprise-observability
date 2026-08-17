#!/usr/bin/env python3
"""MONITOR COVERAGE MATRIX GENERATOR.

The matrix is GENERATED from the archetype catalog, never hand-written. A
hand-maintained coverage matrix is out of date the day after it is written and
becomes actively misleading; this one cannot drift, because it is produced by
the same expansion Terraform performs.

Outputs docs/monitor-coverage-matrix.md and generated/coverage_matrix.json.
CI regenerates it and fails if the committed copy differs (`--check`).
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

import obs_common as oc

MATRIX_PATH = oc.REPO_ROOT / "docs" / "monitor-coverage-matrix.md"

DETECTION_LABEL = {
    "anomaly": "Anomaly",
    "seasonal_anomaly": "Seasonal anomaly",
    "forecast": "Forecast",
    "outlier": "Outlier",
    "rate_of_change": "Rate of change",
    "threshold": "Threshold*",
    "service_check": "Service check",
    "event": "Event",
    "slo_burn": "SLO burn",
    "composite": "Composite",
}


def _routing(policy: dict, inst: dict) -> tuple[str, str, str]:
    """(teams, servicenow, oncall) for a resolved instance."""
    profile = policy["notification_profiles"]["notification_profiles"][
        inst["notification_profile"]]
    route = profile["routes"].get(inst["priority"])
    if route is None:
        return "—", "—", "—"
    teams = "yes"
    snow = route.get("servicenow", "none")
    snow = {
        "none": "—",
        "incident_p1": "Incident P1",
        "incident_p2": "Incident P2",
        "task_p3": "Task",
        "task_p3_when_sustained": "Task (sustained)",
    }.get(snow, snow)
    oncall = "PAGE" if route.get("page") else "—"
    return teams, snow, oncall


def build(policy: dict) -> list[dict]:
    rows = []
    for inst in oc.expand_instances(policy):
        a = policy["archetypes"][inst["archetype"]]
        teams, snow, oncall = _routing(policy, inst)
        rows.append({
            "domain": inst["domain"],
            "resource_type": inst["resource_type"],
            "monitor": a["title"],
            "archetype": inst["archetype"],
            "signal": inst["signal"],
            "detection": DETECTION_LABEL.get(inst["detection"], inst["detection"]),
            "env": inst["env"],
            "band": inst["band"],
            "priority": inst["priority"],
            "slo": inst["slo_id"],
            "teams": teams,
            "servicenow": snow,
            "oncall": oncall,
            "runbook": inst["runbook"],
            "automation": inst["workflow"],
            "automation_class": policy["workflows"][inst["workflow"]]["class"],
            "window": inst["evaluation_window"],
            "grouping": ", ".join(inst["group_by"]) or "—",
            "notify_by": ", ".join(inst["notify_by"]) or "—",
            "mandatory": "yes" if inst["mandatory"] else "no",
        })
    return rows


def render(policy: dict, rows: list[dict]) -> str:
    by_domain = defaultdict(list)
    for r in rows:
        by_domain[r["domain"]].append(r)

    total = len(rows)
    paging = sum(1 for r in rows if r["oncall"] == "PAGE")
    predictive = sum(1 for r in rows
                     if r["detection"] in ("Anomaly", "Seasonal anomaly", "Forecast",
                                           "Outlier", "Rate of change"))
    out = [
        "# Monitor Coverage Matrix",
        "",
        "> **Generated file — do not edit.** Produced by `tools/generate_matrix.py` from",
        "> `platform/policy/archetypes/`. CI regenerates it on every PR and fails if this",
        "> copy is stale, so it cannot drift away from what Terraform actually deploys.",
        "",
        "## Summary",
        "",
        f"- **{len(policy['archetypes'])} archetypes** → **{total} monitor instances** "
        f"(archetype × environment × alert band)",
        f"- **{paging}** instances ({100*paging//max(total,1)}%) are permitted to page; "
        "everything else is a ticket or informational",
        f"- **{predictive}** instances ({100*predictive//max(total,1)}%) use predictive "
        "detection (anomaly, seasonal, forecast, outlier, rate-of-change)",
        f"- **{len(policy['slos'])} domain SLOs** plus one per tier0 service",
        "",
        "Instances marked `Threshold*` use a fixed number. Every one of them carries a",
        "written `rationale_fixed_threshold` in the catalog explaining why the number",
        "itself is the operational contract — CI rejects any that do not.",
        "",
        "## Legend",
        "",
        "| Column | Meaning |",
        "|---|---|",
        "| Detection | How the condition is detected. `Threshold*` = fixed number with recorded rationale. |",
        "| Env | Environment the instance is created in. `dev` never appears — it does not alert by policy. |",
        "| Band | Alert band the monitor selects on: `critical` (tier0/1), `standard` (tier2), `baseline` (QA / low value). |",
        "| Pri | Resolved priority: matrix[impact_class][band] clamped by the environment ceiling. |",
        "| Teams | Microsoft Teams notification. |",
        "| SNOW | ServiceNow record created. |",
        "| Page | Whether Datadog On-Call pages a human. |",
        "| Grouping | Multi-alert group keys — resources are groups, never separate monitors. |",
        "| Collapse | `notify_by` key: evaluate per group, notify once per collapse key. |",
        "",
    ]

    for domain in sorted(by_domain):
        drows = sorted(by_domain[domain], key=lambda r: (r["archetype"], r["env"], r["band"]))
        d = policy["domains"][domain]
        out += [
            f"## {d['display']}",
            "",
            f"Owner: `{d['owner_team']}` · Default SLO: `{d['default_slo']}` · "
            f"{len(drows)} instances",
            "",
            "| Monitor | Signal | Detection | Env | Band | Pri | SLO | Teams | SNOW | Page | Runbook | Automation | Window | Grouping | Collapse |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for r in drows:
            out.append(
                f"| {r['monitor']} | {r['signal']} | {r['detection']} | {r['env']} | "
                f"{r['band']} | **{r['priority']}** | `{r['slo']}` | {r['teams']} | "
                f"{r['servicenow']} | {r['oncall']} | `{r['runbook']}` | "
                f"`{r['automation']}` ({r['automation_class'].replace('_', ' ')}) | "
                f"{r['window']} | {r['grouping']} | {r['notify_by']} |"
            )
        out.append("")

    return "\n".join(out) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="fail if the committed matrix is stale")
    ap.add_argument("--out", type=Path, default=MATRIX_PATH)
    args = ap.parse_args()

    policy = oc.load_policy()
    rows = build(policy)
    rendered = render(policy, rows)
    oc.write_json(oc.GENERATED_DIR / "coverage_matrix.json", rows)

    if args.check:
        current = args.out.read_text() if args.out.exists() else ""
        if current != rendered:
            print("MATRIX STALE: docs/monitor-coverage-matrix.md does not match the catalog.")
            print("Run: python tools/generate_matrix.py")
            return 1
        print(f"matrix: up to date ({len(rows)} rows)")
        return 0

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(rendered)
    print(f"matrix: wrote {len(rows)} rows -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
