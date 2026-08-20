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

ENTITY-AWARE SCORING (§41)
--------------------------
The fleet model above grades every monitor against one set of weights, and that
set was written for a request-path service. A database instance and a rack of
hosts fail differently and are worth different things, so each monitor is ALSO
scored against the rule set for the kind of entity it watches — service,
datastore or infrastructure — using the weights in
`platform/policy/scorecards.yaml`.

The entity score does not replace the fleet score, deliberately. The fleet
number gates the deploy pipeline at ≥ 85; re-weighting it in place would change
what that gate means without anybody deciding to change it, and no one could
tell a real regression from the reweight. Both numbers are published: the fleet
score gates, the per-kind scores drive the monthly review.
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


# -----------------------------------------------------------------------------
# ENTITY-AWARE LAYER (§41)
#
# The seven dimensions are scored ONCE, by the fleet model, and read twice. This
# is not an optimisation: two scoring implementations would eventually disagree
# about what "actionability" means, and then the two published numbers would be
# arguing with each other in the same report.
# -----------------------------------------------------------------------------
def _ratios(dimensions: dict) -> dict:
    """Raw fleet points -> 0..1 per dimension, so any weighting can reuse them."""
    return {d: min(1.0, max(0.0, pts / WEIGHTS[d])) for d, pts in dimensions.items()}


def entity_rules(policy: dict, kind: str, inst: dict, arch: dict,
                 durability_ok: set[str]) -> tuple[float, list[str]]:
    """The kind-specific half of the model: `durability`, plus hard rules.

    Returns the durability RATIO (0..1; meaningless for non-datastores, which
    carry no durability weight) and the findings the rules produced.

    Every rule here was run against the committed catalog before it was written.
    Three of the four find nothing today and exist to stop a regression; the
    fourth finds a real backlog. A rule that can never fire and a rule that
    fires on everything are equally useless.
    """
    findings: list[str] = []
    rt = arch["resource_type"]
    durability = 0.0

    if kind == "service":
        # A customer_impact service monitor with no resolvable objective leaves a
        # responder unable to tell "degraded" from "breaking a promise".
        if arch["impact_class"] == "customer_impact" and inst["slo_id"] not in policy["slos"]:
            findings.append("customer-impact service monitor with no resolvable SLO — "
                            "there is no way to say how bad this is")

    elif kind == "datastore":
        durability = 1.0 if rt in durability_ok else 0.0
        if not durability:
            findings.append(
                f"no durability horizon for `{rt}`: the catalog has no forecast, "
                "backup, replication or freshness archetype for this technology, so "
                "loss and exhaustion are only visible once they have happened")
        # Capacity has lead time by definition. Paging on it wakes somebody for
        # work that could have waited, which is how the pages that could not wait
        # stop being read.
        if inst["pages"] and arch["signal"] in ("capacity", "saturation"):
            findings.append(f"datastore {arch['signal']} signal pages; capacity has lead "
                            "time and belongs in the morning, not at 3am")

    elif kind == "infrastructure":
        gb = arch.get("group_by", [])
        if len(gb) >= 2 and not arch.get("notify_by"):
            findings.append(f"fleet resource grouped by {gb} with no notify_by collapse "
                            "key — one rack event notifies once per member")

    return durability, findings


def score_entity(policy: dict, row: dict, inst: dict, arch: dict,
                 durability_ok: set[str]) -> dict:
    """Re-score one monitor against the rules for the KIND of thing it watches."""
    kind = oc.entity_kind(policy, arch["resource_type"])
    spec = policy["scorecards"]["entity_kinds"][kind]
    weights = spec["weights"]
    ratios = _ratios(row["dimensions"])

    durability, findings = entity_rules(policy, kind, inst, arch, durability_ok)
    ratios["durability"] = durability

    dims = {d: round(ratios.get(d, 0.0) * w, 1) for d, w in weights.items()}
    total = round(sum(dims.values()), 1)
    return {
        "entity_kind": kind,
        "entity_dimensions": dims,
        "entity_score": total,
        "entity_grade": grade(total),
        "entity_findings": findings,
    }


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


def _custom_entity_kind(policy: dict, m: dict, services: dict) -> str:
    """Entity kind for a self-service manifest.

    A manifest names an archetype (whose resource_type classifies it) or the
    literal `custom`, in which case the registered service's archetype decides.
    A manifest that resolves to neither is graded as a service — the strictest
    of the three on objectives, which is the right way to be wrong here.
    """
    base = policy["archetypes"].get(m.get("archetype"))
    if base:
        return oc.entity_kind(policy, base["resource_type"])
    sa = services.get(m.get("service"), {}).get("service_archetype")
    return oc.entity_kind_of_service_archetype(policy, sa) if sa else "service"


def build(policy: dict) -> dict:
    durability_ok = oc.durability_covered_types(policy)

    rows = []
    for i in oc.expand_instances(policy):
        arch = policy["archetypes"][i["archetype"]]
        row = score_instance(policy, i, arch)
        row.update(score_entity(policy, row, i, arch, durability_ok))
        rows.append(row)

    services = oc.load_services()
    for n, m in sorted(oc.load_custom_monitors().items()):
        row = score_custom(policy, n, m, services)
        # Self-service manifests have no archetype instance to run the
        # kind-specific rules against, so they are re-weighted but not
        # rule-checked. Saying so in the row is better than a silent zero on a
        # dimension the manifest never had a chance to earn.
        kind = _custom_entity_kind(policy, m, services)
        weights = policy["scorecards"]["entity_kinds"][kind]["weights"]
        ratios = _ratios(row["dimensions"])
        # `durability` is a property of the archetype catalog for a technology,
        # not of one manifest. Neither penalise nor credit it here: award the
        # dimension at the technology's own coverage.
        base = policy["archetypes"].get(m.get("archetype"))
        ratios["durability"] = 1.0 if (base and base["resource_type"] in durability_ok) else 0.0
        dims = {d: round(ratios.get(d, 0.0) * w, 1) for d, w in weights.items()}
        row.update({
            "entity_kind": kind,
            "entity_dimensions": dims,
            "entity_score": round(sum(dims.values()), 1),
            "entity_grade": grade(round(sum(dims.values()), 1)),
            "entity_findings": [],
        })
        rows.append(row)

    by_team: dict[str, list] = defaultdict(list)
    by_domain: dict[str, list] = defaultdict(list)
    by_kind: dict[str, list] = defaultdict(list)
    for r in rows:
        by_team[r["team"]].append(r["score"])
        by_domain[r["domain"]].append(r["score"])
        by_kind[r["entity_kind"]].append(r)

    def avg(xs):
        return round(sum(xs) / len(xs), 1) if xs else 0.0

    dist: dict[str, int] = defaultdict(int)
    for r in rows:
        dist[r["grade"]] += 1

    kinds = policy["scorecards"]["entity_kinds"]
    by_entity_kind = {}
    for kind, spec in sorted(kinds.items()):
        group = by_kind.get(kind, [])
        a = avg([r["entity_score"] for r in group])
        by_entity_kind[kind] = {
            "monitors": len(group),
            "average": a,
            "grade": grade(a),
            "min_score": spec["min_score"],
            "meets_minimum": a >= spec["min_score"],
            # The fleet number for the same monitors, so a kind that scores
            # differently under the two models is visible rather than arguable.
            "fleet_average": avg([r["score"] for r in group]),
            "below_minimum": sum(1 for r in group if r["entity_score"] < spec["min_score"]),
            "judged_on": " ".join(spec["judged_on"].split()),
        }

    entity_findings = defaultdict(int)
    for r in rows:
        for f in r.get("entity_findings", []):
            entity_findings[f.split(":")[0].split(" — ")[0]] += 1

    return {
        "generated_at": oc.utcnow().isoformat(),
        "summary": {
            "monitors_scored": len(rows),
            "fleet_average": avg([r["score"] for r in rows]),
            "fleet_grade": grade(avg([r["score"] for r in rows])),
            "distribution": dict(sorted(dist.items())),
            "below_c": sum(1 for r in rows if r["score"] < 70),
            "failing": sum(1 for r in rows if r["grade"] == "F"),
            "entity_kinds_meeting_minimum": sum(
                1 for v in by_entity_kind.values() if v["meets_minimum"]),
            "entity_kinds": len(by_entity_kind),
        },
        "by_team": {t: {"average": avg(v), "grade": grade(avg(v)), "monitors": len(v)}
                    for t, v in sorted(by_team.items())},
        "by_domain": {d: {"average": avg(v), "grade": grade(avg(v)), "monitors": len(v)}
                      for d, v in sorted(by_domain.items())},
        "by_entity_kind": by_entity_kind,
        "entity_findings": dict(sorted(entity_findings.items(),
                                       key=lambda kv: -kv[1])),
        "self_service_average": avg([r["score"] for r in rows if r.get("source") == "self_service"]),
        "worst": sorted(rows, key=lambda r: r["score"])[:25],
        "worst_by_entity": sorted(rows, key=lambda r: r["entity_score"])[:25],
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

    out += ["", "## By entity kind — the same monitors, judged by what they watch", "",
            "A service, a datastore and a rack of hosts fail differently, so each is",
            "scored against its own weights from `platform/policy/scorecards.yaml`.",
            "The fleet column is the single-model score for the same monitors: where",
            "the two columns disagree, the entity model is asking the harder question.",
            "",
            "| Entity kind | Monitors | Entity avg | Grade | Minimum | Fleet avg | Judged on |",
            "|---|---|---|---|---|---|---|"]
    for k, v in report["by_entity_kind"].items():
        mark = "" if v["meets_minimum"] else " ⚠️"
        out.append(f"| {k} | {v['monitors']} | {v['average']}{mark} | {v['grade']} | "
                   f"{v['min_score']} | {v['fleet_average']} | {v['judged_on']} |")
    ef = report.get("entity_findings") or {}
    if ef:
        out += ["", "### Entity-rule findings", "",
                "These exist only in the entity model — the fleet model has no dimension",
                "that could have caught them.", "",
                "| Finding | Monitors |", "|---|---|"]
        for f, n in ef.items():
            out.append(f"| {f} | {n} |")
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
    ap.add_argument("--enforce-entity-minimums", action="store_true",
                    help="Also fail if any entity kind falls below its min_score in "
                         "platform/policy/scorecards.yaml. OFF by default so the deploy "
                         "gate keeps meaning exactly what it meant before §41 — the "
                         "governance run and the test suite are where erosion is caught.")
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
    print(json.dumps(report["by_entity_kind"], indent=2))
    ok = s["fleet_average"] >= args.min_fleet_score and s["failing"] <= args.max_failing
    if not ok:
        print(f"\nSCORECARD FAIL: fleet average {s['fleet_average']} "
              f"(min {args.min_fleet_score}), failing {s['failing']} (max {args.max_failing})")
    if args.enforce_entity_minimums:
        for kind, v in report["by_entity_kind"].items():
            if not v["meets_minimum"]:
                ok = False
                print(f"ENTITY SCORECARD FAIL: {kind} averages {v['average']} "
                      f"(min {v['min_score']}), {v['below_minimum']} below minimum")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
