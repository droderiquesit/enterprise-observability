#!/usr/bin/env python3
"""COVERAGE & COMPLIANCE REPORT — the evidence engine.

Joins the authoritative inventory and the profile assignments against the live
(or fixture) Datadog estate, and answers the only question that matters:

    "Is anything in this organization unmonitored, unowned, or unactionable —
     and can we prove it?"

Every check maps to a promise the framework makes. A red report is a governance
incident for the observability-platform team, not a warning.

  C1   resources with an alerting band but no covering monitor pack
  C2   resources without a resolvable owner
  C3   missing or invalid required tags (resources and monitors)
  C4   services with no SLO association
  C5   monitors without a runbook
  C6   monitors without workflow automation
  C7   monitors without resolvable routing (team + priority + profile)
  C8   duplicate or overlapping monitors
  C9   unmanaged (click-ops) monitors
  C10  resources on the wrong monitoring profile
  C11  cardinality risk: too many group keys or missing collapse keys
  C12  expired exceptions
  C13  SLO integrity — missing SLOs and silent telemetry
  C14  paging discipline: anything paging that policy says should not
  C15  monitors with no actionable response (no impact statement / no runbook)
  C16  monitors with no NATIVE runbook attachment (Datadog notebook asset)

Modes: --live (Datadog API) or --fixtures DIR.

TWO GATES read this one report (--gate, default governance):

  governance   blocks on EVERY finding. The nightly loop runs this; a red run
               opens a governance issue. Estate hygiene — unowned resources,
               click-ops monitors, missing tags on somebody else's service —
               is chased HERE, because here is where a human is on the hook.

  deploy       blocks only on defects in what the deploy pipeline itself owns:
               coverage of the alertable estate and the contract on the
               Terraform-managed monitors and SLOs it just applied. A deploy
               must not go permanently red because a resource outside the
               platform's control is missing a tag — that would train everyone
               to ignore the deploy gate, which is how real regressions ship.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from collections import defaultdict
from pathlib import Path

import obs_common as oc

CHECK_TITLES = {
    "C1": "Unmonitored resources",
    "C2": "Resources without owners",
    "C3": "Missing / invalid required tags",
    "C4": "Services without an SLO",
    "C5": "Monitors without a runbook",
    "C6": "Monitors without automation",
    "C7": "Monitors without routing",
    "C8": "Duplicate / overlapping monitors",
    "C9": "Unmanaged (click-ops) monitors",
    "C10": "Wrong monitoring profile",
    "C11": "Cardinality risk",
    "C12": "Expired exceptions",
    "C13": "SLO integrity / silent telemetry",
    "C14": "Paging discipline violations",
    "C15": "Monitors with no actionable response",
    "C16": "Monitors without a native runbook attachment",
}

# Checks whose findings describe the ESTATE rather than the platform: content
# the pipeline reports on but does not own (resource tagging, click-ops
# monitors, profile assignments, exception dates). Advisory for the deploy
# gate, blocking for governance. Two checks carry findings of BOTH kinds and
# are split per entry in _deploy_blocking below:
#   C3   `monitor:*` entries are managed monitors missing required tags — a
#        platform defect; resource entries are estate hygiene.
#   C13  a live SLO status error is a platform defect; a declared
#        `telemetry_dependency` is an estate note (the producer is deployed
#        outside this platform) and must not hold the deploy red forever.
ESTATE_CHECKS = {"C2", "C4", "C9", "C10", "C12"}


def _finding_class(cid: str, item) -> str:
    """Which KIND of finding this is, within a check.

    Two checks mix platform defects with estate hygiene, and the difference
    decides both who must act and whether a deploy should stop:
      C3   a `monitor:*` entry is a managed monitor missing a required tag —
           the platform's own defect. Anything else is a discovered resource
           somebody else owns.
      C13  a declared `telemetry_dependency` is a known, recorded gap. A live
           SLO status error is a real failure of a real objective.
    """
    if cid == "C3":
        return ("managed_monitors" if str(getattr(item, "get", lambda k, d=None: None)("id", "") or "").startswith("monitor:")
                else "discovered_resources")
    if cid == "C13":
        return "declared_telemetry_dependency" if isinstance(item, dict) and "slo_id" in item \
            else "live_slo_error"
    return "all"


def _blocks_deploy(cid: str, item) -> bool:
    """Does THIS finding block the deploy gate?

    Per-finding, not per-check: C3 and C13 each mix a platform defect with an
    estate observation, and only the platform half may stop a deploy.
    """
    if cid in ESTATE_CHECKS:
        return False
    if cid == "C3":
        return _finding_class(cid, item) == "managed_monitors"
    if cid == "C13":
        return _finding_class(cid, item) == "live_slo_error"
    return True


def _deploy_blocking(cid: str, items: list) -> int:
    """How many of a check's findings block the DEPLOY gate."""
    return sum(1 for it in items if _blocks_deploy(cid, it))


def acceptances(policy: dict, today: dt.date | None = None) -> dict:
    """Accepted governance findings — `control: finding_acceptance`.

    An acceptance records that a finding is KNOWN, OWNED and TIME-BOXED. It
    suppresses the failure, never the report. The nightly run therefore stays
    meaningful: a finding that grows past the accepted count, a new finding, or
    an expired acceptance all turn it red again.

    Expiry is evaluated here (unlike Terraform, which must stay deterministic):
    a governance run is allowed to know what day it is, and an acceptance that
    silently outlived its review is exactly what this must catch.
    """
    today = today or dt.date.today()
    out: dict[tuple[str, str], dict] = {}
    for e in policy["exceptions"]:
        if e.get("control") != "finding_acceptance":
            continue
        exp = e["expires"]
        if not isinstance(exp, dt.date):
            exp = dt.date.fromisoformat(str(exp))
        if exp < today:
            continue          # expired: stops suppressing, and C12 reports it
        sc = e.get("scope", {})
        out[(sc.get("check"), sc.get("applies_to", "all"))] = {
            "max": int(e["value"]), "exception": e["id"],
            "owner": e["owner"], "expires": str(exp),
        }
    return out


def fetch_live():
    headers = oc.dd_headers()
    site = oc.dd_site()
    monitors, page = [], 0
    while True:
        r = oc.dd_request("GET", f"{site}/api/v1/monitor", headers=headers,
                          params={"page": page, "page_size": 200})
        r.raise_for_status()
        batch = r.json()
        monitors.extend(batch)
        if len(batch) < 200:
            break
        page += 1
    slos, offset = [], 0
    while True:
        r = oc.dd_request("GET", f"{site}/api/v1/slo", headers=headers,
                          params={"limit": 100, "offset": offset})
        r.raise_for_status()
        batch = r.json().get("data", [])
        slos.extend(batch)
        if len(batch) < 100:
            break
        offset += 100
    return monitors, slos


def _covering_archetypes(policy: dict, service_archetype: str) -> set[str]:
    """The archetypes that MUST be deployed for this service archetype.

    Only `mandatory` archetypes count towards coverage. A resource is not
    "covered" because some optional member of one of its packs happens to exist
    — that reading would let an entire golden-signal pack be deleted while the
    report still claimed 100%.
    """
    sa = policy["service_archetypes"].get(service_archetype)
    if not sa:
        return set()
    out: set[str] = set()
    for pack in sa["packs"]:
        out.update(a for a in policy["packs"][pack]["archetypes"]
                   if policy["archetypes"].get(a, {}).get("mandatory"))
    return out


def run_checks(inventory, assignments, monitors, slos, policy) -> dict:
    g = policy["global"]
    checks: dict[str, list] = {f"C{i}": [] for i in range(1, 17)}

    monitor_tags = {m["id"]: oc.tags_to_map(m.get("tags")) for m in monitors}
    managed = {mid for mid, t in monitor_tags.items() if t.get("managed_by") == "terraform"}

    # Which (archetype, env, band) combinations are actually deployed.
    deployed = defaultdict(set)
    for t in monitor_tags.values():
        if t.get("archetype"):
            deployed[t["archetype"]].add((t.get("env"), t.get("alert_band")))

    slo_ids_seen = set()
    slo_services = set()
    for s in slos:
        st = oc.tags_to_map(s.get("tags", [])) if isinstance(s.get("tags"), list) else {}
        if st.get("slo_id"):
            slo_ids_seen.add(st["slo_id"])
        for svc in s.get("service_tags") or ([st["service"]] if "service" in st else []):
            slo_services.add(svc)

    # ---------------------------------------------------------- resource checks
    services_seen: set[tuple[str, str]] = set()
    observe_only = []
    for a in assignments["assignments"]:
        if a.get("service"):
            services_seen.add((a["service"], a["domain"]))

        if a["owner_source"] == "unowned_pool":
            checks["C2"].append(a["id"])

        bad = [v for v in a["violations"]
               if v.startswith(("invalid_", "unknown_team", "service_archetype_inferred"))]
        if bad:
            checks["C3"].append({"id": a["id"], "violations": bad})

        if a["alert_band"] == "none":
            observe_only.append(a["id"])
            # An observe_only resource with no recorded reason is a silent gap.
            if not a["observe_only_reason"]:
                checks["C10"].append({"id": a["id"], "problem": "observe_only with no recorded reason"})
            continue

        expected = _covering_archetypes(policy, a["service_archetype"])
        missing = [
            arch for arch in expected
            # An archetype only covers this resource where it is instantiated
            # for the resource's own environment AND alert band.
            if (a["env"], a["alert_band"]) not in deployed.get(arch, set())
            and a["env"] in policy["archetypes"][arch]["envs"]
            and a["alert_band"] in policy["archetypes"][arch]["bands"]
        ]
        if missing:
            checks["C1"].append({
                "id": a["id"], "kind": a["kind"], "env": a["env"],
                "band": a["alert_band"], "service_archetype": a["service_archetype"],
                "missing_archetypes": sorted(missing)[:5],
            })

        # C10 — profile sanity
        if a["domain"] == "security" and a["monitoring_profile"] not in ("regulated", "critical"):
            checks["C10"].append({"id": a["id"], "problem": f"security resource on {a['monitoring_profile']}"})
        if a["tier"] == "tier0" and a["alert_band"] != "critical" and a["env"] == "prod":
            checks["C10"].append({"id": a["id"], "problem": "tier0 not on the critical band"})

    # C4 — a service is covered if it, or its domain, carries an SLO
    domain_slo_services = {s["service"] for s in policy["slos"].values()}
    domains_with_slo = {s["domain"] for s in policy["slos"].values()}
    for svc, domain in sorted(services_seen):
        if svc in slo_services or svc in domain_slo_services or domain in domains_with_slo:
            continue
        checks["C4"].append(svc)

    # ----------------------------------------------------------- monitor checks
    seen_dedup: dict[str, str] = {}
    seen_query: dict[str, str] = {}
    for m in monitors:
        t = monitor_tags[m["id"]]
        name = m.get("name", str(m["id"]))

        if m["id"] not in managed:
            checks["C9"].append({"id": m["id"], "name": name})
            continue

        if not t.get("runbook"):
            checks["C5"].append(name)
        if not t.get("automation_ref"):
            checks["C6"].append(name)
        if not (t.get("team") and t.get("priority") and t.get("notification_profile")):
            checks["C7"].append(name)

        missing = [rt for rt in g["required_monitor_tags"] if rt not in t]
        if missing:
            checks["C3"].append({"id": f"monitor:{m['id']}",
                                 "violations": [f"missing_tag:{x}" for x in missing]})

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

        # C11 — cardinality observed at runtime
        if " by {" in q:
            keys = q.split(" by {")[1].split("}")[0].split(",")
            if len(keys) > g["cardinality"]["max_group_by_keys"]:
                checks["C11"].append({"name": name, "group_keys": len(keys)})
            banned = sorted({k.strip() for k in keys} & set(g["cardinality"]["forbidden_group_keys"]))
            if banned:
                checks["C11"].append({"name": name, "banned_group_keys": banned})

        # C14 — paging discipline. The `priority` tag is lowercase because
        # Datadog reserves that tag key and only accepts p1..p4. The archetype
        # tag encodes the paging SOURCE: `composite`, `slo-burn-*` (the tag
        # form of policy's `slo_burn`), or a plain symptom archetype.
        prio = (t.get("priority") or "").upper()
        paging = t.get("pages") == "true"
        p2_allowed = policy["priorities"]["paging_rule"]["p2_pages_only_from"]
        arch = str(t.get("archetype", ""))
        source = ("slo_burn" if arch.startswith("slo-burn")
                  else "composite" if arch == "composite" else "archetype")
        if paging:
            if t.get("env") != "prod":
                checks["C14"].append({"name": name, "problem": f"pages in {t.get('env')}"})
            elif t.get("alert_band") != "critical":
                checks["C14"].append({"name": name, "problem": f"pages on band {t.get('alert_band')}"})
            elif prio == "P2" and source not in p2_allowed:
                checks["C14"].append({
                    "name": name,
                    "problem": "P2 symptom monitor pages; policy allows P2 paging only "
                               f"from {', '.join(p2_allowed)}",
                })
            elif prio in ("P3", "P4"):
                checks["C14"].append({"name": name, "problem": f"{prio} must never page"})

        # C15 — actionability
        msg = m.get("message", "")
        if "**DO THIS NEXT:**" not in msg and "RUNBOOK" not in msg.upper():
            checks["C15"].append({"name": name, "problem": "message states no next action or runbook"})

        # C16 — the runbook is ATTACHED, not merely named.
        #
        # Read from the `runbook_notebook` tag rather than re-fetching every
        # monitor with `with_assets=true`: the factory writes the tag from the
        # same registry value it builds the asset from, so the tag is the
        # cheap, list-visible proof that the attachment was rendered. A monitor
        # that names a runbook it never attached is the exact failure this
        # check exists to catch — it looks covered and is not.
        if not t.get("runbook_notebook"):
            checks["C16"].append({
                "name": name,
                "runbook": t.get("runbook", "(none)"),
                "problem": "no Datadog notebook attached — the runbook is named but not "
                           "reachable from the monitor",
            })

        # A runbook URL in the alert body is a regression, not a fallback.
        if "http://" in msg or "https://" in msg:
            checks["C16"].append({
                "name": name,
                "problem": "alert body contains a URL; runbooks must be attached as a "
                           "monitor asset, never linked from the message",
            })

    # C12 — expired exceptions
    today = dt.date.today()
    for e in policy["exceptions"]:
        expires = e["expires"]
        if not isinstance(expires, dt.date):
            expires = dt.date.fromisoformat(str(expires))
        if expires < today:
            checks["C12"].append({"id": e["id"], "expired": str(expires), "owner": e["owner"]})

    # C13 — SLO integrity
    for sid, s in policy["slos"].items():
        if s.get("telemetry_dependency"):
            checks["C13"].append({"slo_id": sid, "problem": f"telemetry dependency: {s['telemetry_dependency']}"})
    for s in slos:
        status = (s.get("overall_status") or [{}])[0] if isinstance(s.get("overall_status"), list) else {}
        if status.get("error"):
            checks["C13"].append({"slo": s.get("name"), "problem": status["error"]})

    counts = {k: len(v) for k, v in checks.items()}
    blocking = {k: _deploy_blocking(k, v) for k, v in checks.items()}

    # --- accepted findings -----------------------------------------------------
    # Subtract owned, time-boxed acceptances from what FAILS the run, while
    # leaving every finding in the report. A run that fails on the same two
    # known findings every night cannot signal a regression, because nobody can
    # tell the new red from yesterday's red.
    # Acceptance is applied PER FINDING, inside its class, up to the accepted
    # budget. Subtracting a check-level total would let an accepted estate
    # finding cancel out a real platform defect in the same check — e.g. the
    # accepted backup-telemetry dependency silently absorbing a live SLO error.
    accepted_map = acceptances(policy)
    accepted, unaccepted, deploy_unaccepted, accepted_detail = {}, {}, {}, []
    for cid, items in checks.items():
        by_class: dict[str, list] = defaultdict(list)
        for it in items:
            by_class[_finding_class(cid, it)].append(it)

        acc_total, unacc_total, deploy_unacc = 0, 0, 0
        for klass, group in sorted(by_class.items()):
            rule = accepted_map.get((cid, klass)) or accepted_map.get((cid, "all"))
            budget = rule["max"] if rule else 0
            for i, it in enumerate(group):
                is_accepted = i < budget
                if is_accepted:
                    acc_total += 1
                else:
                    unacc_total += 1
                    if _blocks_deploy(cid, it):
                        deploy_unacc += 1
            if rule:
                accepted_detail.append({
                    "check": cid, "class": klass, "findings": len(group),
                    "accepted": min(len(group), budget),
                    "over_budget": max(0, len(group) - budget),
                    "exception": rule["exception"], "owner": rule["owner"],
                    "expires": rule["expires"],
                })
        accepted[cid] = acc_total
        unaccepted[cid] = unacc_total
        deploy_unaccepted[cid] = deploy_unacc
    total = assignments["summary"]["total"]
    alertable = assignments["summary"]["alertable"]
    covered = alertable - len(checks["C1"])
    return {
        "generated_at": oc.utcnow().isoformat(),
        "summary": {
            "resources_total": total,
            "resources_observe_only": len(observe_only),
            "resources_alertable": alertable,
            "resources_covered": covered,
            "coverage_pct": round(100.0 * covered / alertable, 3) if alertable else 100.0,
            "monitors_total": len(monitors),
            "monitors_managed": len(managed),
            "monitors_paging": sum(1 for t in monitor_tags.values() if t.get("pages") == "true"),
            "check_counts": counts,
            "accepted_counts": accepted,
            "unaccepted_counts": unaccepted,
            "deploy_blocking_counts": blocking,
            # `pass` now means "nothing unexpected": every finding is either
            # absent or covered by a live, owned, expiring acceptance.
            "deploy_unaccepted_counts": deploy_unaccepted,
            "pass": all(v == 0 for v in unaccepted.values()),
            "deploy_pass": all(v == 0 for v in deploy_unaccepted.values()),
        },
        "checks": {k: v[:200] for k, v in checks.items()},
        "accepted_findings": accepted_detail,
        "observe_only_sample": observe_only[:50],
    }


def to_markdown(report: dict) -> str:
    s = report["summary"]
    lines = [
        "# Coverage & Compliance Report",
        "",
        f"- Resources: **{s['resources_total']}** — {s['resources_observe_only']} observe-only "
        "by explicit policy, each with a recorded reason",
        f"- Coverage of the alertable estate: **{s['coverage_pct']}%** "
        f"({s['resources_covered']}/{s['resources_alertable']})",
        f"- Monitors: {s['monitors_total']} total, {s['monitors_managed']} Terraform-managed, "
        f"{s['monitors_paging']} able to page",
        f"- Governance gate (all checks, minus accepted): "
        f"**{'PASS' if s['pass'] else 'FAIL'}**",
        f"- Deploy gate (platform-integrity checks only): "
        f"**{'PASS' if s.get('deploy_pass', s['pass']) else 'FAIL'}**",
        "",
        "| Check | Findings | Deploy gate |",
        "|---|---|---|",
    ]
    blocking = s.get("deploy_blocking_counts", {})
    for cid, title in CHECK_TITLES.items():
        n = s["check_counts"].get(cid, 0)
        mark = "" if n == 0 else " ⚠️"
        b = blocking.get(cid, n)
        if cid in ESTATE_CHECKS:
            gate = "estate hygiene — advisory"
        elif cid in ("C3", "C13"):
            gate = f"split — {b} blocking"
        else:
            gate = "blocks"
        lines.append(f"| {cid} {title} | {n}{mark} | {gate} |")
    lines.append("")
    acc = report.get("accepted_findings") or []
    if acc:
        lines += ["## Accepted findings",
                  "",
                  "Known, owned and time-boxed. They are reported but do not fail the run; "
                  "anything beyond the accepted count does.",
                  "",
                  "| Check | Class | Findings | Accepted | Over budget | Exception | Owner | Expires |",
                  "|---|---|---|---|---|---|---|---|"]
        for a in acc:
            lines.append(
                f"| {a['check']} | {a['class']} | {a['findings']} | {a['accepted']} | "
                f"{a['over_budget']} | {a['exception']} | {a['owner']} | {a['expires']} |")
        lines.append("")
    for cid, items in report["checks"].items():
        if not items:
            continue
        lines.append(f"## {cid} {CHECK_TITLES[cid]} — {len(items)} shown (capped at 200)")
        for it in items[:20]:
            lines.append(f"- `{it if isinstance(it, str) else json.dumps(it)}`")
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
    ap.add_argument("--gate", choices=["deploy", "governance"], default="governance",
                    help="which gate decides the exit code (see module docstring); "
                         "the report itself always contains every finding")
    args = ap.parse_args()

    inventory = json.loads(args.inventory.read_text())
    assignments = json.loads(args.assignments.read_text())
    if args.live:
        monitors, slos = fetch_live()
    else:
        # tests/fixtures is the one fixture set in the repo; monitors_planned
        # is the terraform-plan-derived estate (see tools/refresh_fixtures.py).
        monitors = json.loads((args.fixtures / "monitors_planned.json").read_text())
        slos = json.loads((args.fixtures / "slos.json").read_text())

    policy = oc.load_policy()
    report = run_checks(inventory, assignments, monitors, slos, policy)
    oc.write_json(args.out_json, report)
    args.out_md.parent.mkdir(parents=True, exist_ok=True)
    args.out_md.write_text(to_markdown(report))
    print(json.dumps(report["summary"], indent=2))
    ok = (report["summary"]["deploy_pass"] if args.gate == "deploy"
          else report["summary"]["pass"])
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
