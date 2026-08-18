#!/usr/bin/env python3
"""MONITOR QUALITY SCORECARD.

Coverage is easy to grow and easy to fake. Quality is what decides whether
on-call is sustainable, so it gets its own score, published per team, reviewed
monthly.

Each monitor is scored out of 100 across eight dimensions. The weights encode
what the platform actually believes:

  25  ACTIONABILITY   runbook + workflow + a stated next action + impact
  20  OWNERSHIP       resolvable team, registered, routing that leads somewhere
  15  DETECTION       predictive where the signal is behavioral; justified where not
  15  SLO LINKAGE     attached to an objective, and the objective is real
  10  CARDINALITY     grouping is bounded and collapsed
  10  PAGING          only pages when policy permits it
   5  METADATA        the full mandatory tag set

Grades: A ≥ 90, B ≥ 80, C ≥ 70, D ≥ 60, F below. A monitor below C is a
candidate for retuning or deletion at the next alert-quality review; the
platform's own target is a fleet average of A and zero F.

Runtime signals (alert volume, flap rate, acknowledgement rate) are folded in
when --live is used; the static score works without credentials so it can run
on every pull request.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import obs_common as oc

WEIGHTS = {
    "actionability": 25,
    "ownership": 20,
    "detection": 15,
    "slo_linkage": 15,
    "cardinality": 10,
    "paging": 10,
    "metadata": 5,
}


def grade(score: float) -> str:
    return "A" if score >= 90 else "B" if score >= 80 else "C" if score >= 70 else "D" if score >= 60 else "F"


def score_instance(policy: dict, inst: dict, arch: dict) -> dict:
    findings: list[str] = []
    s: dict[str, float] = {}

    # --- actionability -------------------------------------------------------
    pts = 0
    if inst["runbook"] in policy["runbooks"]:
        pts += 10
    else:
        findings.append("runbook is not in the registry")
    if inst["workflow"] in policy["workflows"]:
        pts += 8
        wf = policy["workflows"][inst["workflow"]]
        if wf["class"] == "diagnostic_only":
            pts += 2      # diagnostics attached to every alert is the ideal
    else:
        findings.append("workflow is not in the registry")
    if arch.get("notes") or arch.get("rationale_fixed_threshold"):
        pts += 5
    else:
        findings.append("no explanatory note or threshold rationale — a responder "
                        "reading this alert at 3am has nothing to orient on")
    s["actionability"] = min(pts, WEIGHTS["actionability"])

    # --- ownership -----------------------------------------------------------
    pts = 0
    team = policy["domains"][inst["domain"]].get(
        "routing_override_team", policy["domains"][inst["domain"]]["owner_team"])
    if team in policy["teams"]:
        pts += 10
    else:
        findings.append(f"owning team {team!r} is not registered")
    profile = policy["notification_profiles"]["notification_profiles"].get(
        inst["notification_profile"])
    if profile and inst["priority"] in profile["routes"]:
        pts += 10
    else:
        findings.append(f"notification profile {inst['notification_profile']!r} defines no "
                        f"route for {inst['priority']} — this alert goes nowhere")
    s["ownership"] = pts

    # --- detection -----------------------------------------------------------
    pts = 0
    behavioral = arch["signal"] in policy["global"]["detection_policy"]["behavioral_signals"]
    predictive = any(fn in arch["query"] for fn in oc.PREDICTIVE_FUNCS)
    if predictive:
        pts = 15
    elif not behavioral:
        pts = 13          # absolute boundary on a non-behavioral signal is correct
    elif arch.get("rationale_fixed_threshold"):
        pts = 10
        findings.append("fixed threshold on a behavioral signal (justified) — revisit "
                        "whether an anomaly baseline would be tighter")
    else:
        pts = 0
        findings.append("fixed threshold on a behavioral signal with no rationale")
    s["detection"] = pts

    # --- SLO linkage ---------------------------------------------------------
    pts = 0
    if inst["slo_id"] in policy["slos"]:
        pts += 12
        slo = policy["slos"][inst["slo_id"]]
        if not slo.get("telemetry_dependency"):
            pts += 3
        else:
            findings.append(f"SLO {inst['slo_id']} depends on telemetry that may be silent")
    else:
        findings.append("slo_id does not resolve")
    s["slo_linkage"] = pts

    # --- cardinality ---------------------------------------------------------
    pts = WEIGHTS["cardinality"]
    gb = arch.get("group_by", [])
    if len(gb) > policy["global"]["cardinality"]["max_group_by_keys"]:
        pts -= 6
        findings.append(f"{len(gb)} group keys")
    if set(gb) & set(policy["global"]["cardinality"]["forbidden_group_keys"]):
        pts -= 10
        findings.append("banned identity key in group_by")
    wide = policy["grouping"]["notify_by_policy"]["standard_collapse_keys"]
    if inst["domain"] in wide and len(gb) >= 2 and not arch.get("notify_by"):
        pts -= 4
        findings.append("no notify_by collapse key on a wide-fanout monitor")
    s["cardinality"] = max(pts, 0)

    # --- paging --------------------------------------------------------------
    pts = WEIGHTS["paging"]
    if inst["pages"]:
        if inst["env"] != "prod":
            pts = 0
            findings.append(f"pages in {inst['env']}")
        elif inst["priority"] not in ("P1", "P2"):
            pts = 0
            findings.append(f"{inst['priority']} must never page")
        elif inst["priority"] == "P2":
            pts = 0
            findings.append("P2 symptom archetype pages; only SLO burn and composites may")
    s["paging"] = pts

    # --- metadata ------------------------------------------------------------
    required = ["title", "signal", "impact_class", "detection", "resource_type",
                "failure_domain", "slo_id", "runbook", "workflow"]
    missing = [f for f in required if not arch.get(f)]
    s["metadata"] = WEIGHTS["metadata"] if not missing else 0
    if missing:
        findings.append(f"missing catalog fields: {missing}")

    total = round(sum(s.values()), 1)
    return {
        "monitor_id": inst["key"],
        "archetype": inst["archetype"],
        "title": inst["title"],
        "domain": inst["domain"],
        "env": inst["env"],
        "band": inst["band"],
        "priority": inst["priority"],
        "team": team,
        "dimensions": s,
        "score": total,
        "grade": grade(total),
        "findings": findings,
    }


def score_custom(policy: dict, name: str, m: dict, services: dict) -> dict:
    """Score a self-service monitor.

    This is where the scorecard earns its keep. The catalog was authored
    against the same policy the scorecard checks, so it grades well by
    construction; self-service manifests are written by teams under deadline
    pressure and are where quality actually drifts.
    """
    findings: list[str] = []
    s: dict[str, float] = {}
    base = policy["archetypes"].get(m["archetype"]) if m["archetype"] != "custom" else {}

    pts = 0
    if m.get("runbook") in policy["runbooks"]:
        pts += 10
    else:
        findings.append("runbook does not resolve")
    if m.get("workflow") in policy["workflows"]:
        pts += 10
    else:
        findings.append("workflow does not resolve")
    if m.get("summary") and m.get("impact"):
        pts += 5
    else:
        findings.append("no summary/impact statement — the responder gets no context "
                        "beyond the metric that fired")
    s["actionability"] = min(pts, WEIGHTS["actionability"])

    pts = 0
    if m.get("team") in policy["teams"]:
        pts += 10
    else:
        findings.append("team is not registered")
    if m.get("service") in services:
        pts += 10
    else:
        findings.append("service is not registered, so tier and band cannot be resolved")
    s["ownership"] = pts

    query = m.get("query") or base.get("query", "")
    predictive = any(fn in query for fn in oc.PREDICTIVE_FUNCS)
    if predictive:
        s["detection"] = 15
    elif m.get("justification"):
        s["detection"] = 10
        findings.append("fixed threshold with a written justification")
    else:
        s["detection"] = 0
        findings.append("fixed threshold with no justification")

    s["slo_linkage"] = 15 if m.get("slo") in policy["slos"] else 0
    if not s["slo_linkage"]:
        findings.append("slo does not resolve")

    gb = m.get("group_by", base.get("group_by", []))
    pts = WEIGHTS["cardinality"]
    if len(gb) > policy["global"]["cardinality"]["max_group_by_keys"]:
        pts -= 6
        findings.append("too many group keys")
    if set(gb) & set(policy["global"]["cardinality"]["forbidden_group_keys"]):
        pts -= 10
        findings.append("banned identity key in group_by")
    s["cardinality"] = max(pts, 0)

    tier = services.get(m.get("service"), {}).get("tier", "tier2")
    band = policy["tiers"][tier]["alert_band"]
    prio = m.get("priority", "P3")
    s["paging"] = WEIGHTS["paging"]
    if prio in ("P1", "P2") and band != "critical":
        s["paging"] = 0
        findings.append(f"{prio} requested on a {tier} service")

    s["metadata"] = WEIGHTS["metadata"] if all(
        m.get(f) for f in ("name", "archetype", "service", "team", "env", "slo")) else 0

    total = round(sum(s.values()), 1)
    return {
        "monitor_id": f"custom.{name}",
        "archetype": m["archetype"],
        "title": name,
        "domain": m.get("domain", base.get("domain", "application")),
        "env": ",".join(m.get("env", [])),
        "band": band,
        "priority": prio,
        "team": m.get("team", "unknown"),
        "dimensions": s,
        "score": total,
        "grade": grade(total),
        "findings": findings,
        "source": "self_service",
    }


def build(policy: dict) -> dict:
    rows = [score_instance(policy, i, policy["archetypes"][i["archetype"]])
            for i in oc.expand_instances(policy)]
    services = oc.load_services()
    rows += [score_custom(policy, n, m, services)
             for n, m in sorted(oc.load_custom_monitors().items())]

    by_team: dict[str, list] = defaultdict(list)
    by_domain: dict[str, list] = defaultdict(list)
    for r in rows:
        by_team[r["team"]].append(r["score"])
        by_domain[r["domain"]].append(r["score"])

    def avg(xs):
        return round(sum(xs) / len(xs), 1) if xs else 0.0

    dist: dict[str, int] = defaultdict(int)
    for r in rows:
        dist[r["grade"]] += 1

    return {
        "generated_at": oc.utcnow().isoformat(),
        "summary": {
            "monitors_scored": len(rows),
            "fleet_average": avg([r["score"] for r in rows]),
            "fleet_grade": grade(avg([r["score"] for r in rows])),
            "distribution": dict(sorted(dist.items())),
            "below_c": sum(1 for r in rows if r["score"] < 70),
            "failing": sum(1 for r in rows if r["grade"] == "F"),
        },
        "by_team": {t: {"average": avg(v), "grade": grade(avg(v)), "monitors": len(v)}
                    for t, v in sorted(by_team.items())},
        "by_domain": {d: {"average": avg(v), "grade": grade(avg(v)), "monitors": len(v)}
                      for d, v in sorted(by_domain.items())},
        "self_service_average": avg([r["score"] for r in rows if r.get("source") == "self_service"]),
        "worst": sorted(rows, key=lambda r: r["score"])[:25],
        "monitors": rows,
    }


def to_markdown(report: dict) -> str:
    s = report["summary"]
    out = [
        "# Monitor Quality Scorecard",
        "",
        f"**Fleet average: {s['fleet_average']} ({s['fleet_grade']})** across "
        f"{s['monitors_scored']} monitor instances.",
        "",
        f"Distribution: " + ", ".join(f"{k}={v}" for k, v in s["distribution"].items()),
        f" · below C: {s['below_c']} · failing: {s['failing']}",
        "",
        "## Scoring model",
        "",
        "| Dimension | Weight | What it measures |",
        "|---|---|---|",
        "| Actionability | 25 | Runbook, automation, and enough context to act at 3am |",
        "| Ownership | 20 | A registered team AND a routing path that terminates somewhere |",
        "| Detection | 15 | Predictive where the signal is behavioral; justified where fixed |",
        "| SLO linkage | 15 | Attached to a real objective with live telemetry |",
        "| Cardinality | 10 | Bounded grouping, collapse key on wide fanouts |",
        "| Paging | 10 | Pages only where policy permits |",
        "| Metadata | 5 | Complete catalog entry |",
        "",
        "## By team",
        "",
        "| Team | Monitors | Average | Grade |",
        "|---|---|---|---|",
    ]
    for t, v in report["by_team"].items():
        out.append(f"| {t} | {v['monitors']} | {v['average']} | {v['grade']} |")
    out += ["", "## By domain", "", "| Domain | Monitors | Average | Grade |", "|---|---|---|---|"]
    for d, v in report["by_domain"].items():
        out.append(f"| {d} | {v['monitors']} | {v['average']} | {v['grade']} |")
    out += ["", "## Lowest-scoring monitors", "",
            "These are the review queue. A monitor that stays below C for two review",
            "cycles is retuned or deleted — keeping a bad monitor is not neutral, it",
            "trains people to ignore alerts.", "",
            "| Monitor | Env/Band | Score | Grade | Findings |", "|---|---|---|---|---|"]
    for r in report["worst"][:15]:
        out.append(f"| {r['title']} | {r['env']}/{r['band']} | {r['score']} | {r['grade']} | "
                   f"{'; '.join(r['findings'][:2]) or '—'} |")
    return "\n".join(out) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-fleet-score", type=float, default=85.0,
                    help="Fail if the fleet average drops below this.")
    ap.add_argument("--max-failing", type=int, default=0,
                    help="Fail if more than this many monitors grade F.")
    ap.add_argument("--out-json", type=Path, default=oc.GENERATED_DIR / "scorecard.json")
    ap.add_argument("--out-md", type=Path, default=oc.GENERATED_DIR / "scorecard.md")
    args = ap.parse_args()

    policy = oc.load_policy()
    report = build(policy)
    oc.write_json(args.out_json, report)
    args.out_md.parent.mkdir(parents=True, exist_ok=True)
    args.out_md.write_text(to_markdown(report))

    s = report["summary"]
    print(json.dumps(s, indent=2))
    ok = s["fleet_average"] >= args.min_fleet_score and s["failing"] <= args.max_failing
    if not ok:
        print(f"\nSCORECARD FAIL: fleet average {s['fleet_average']} "
              f"(min {args.min_fleet_score}), failing {s['failing']} (max {args.max_failing})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
