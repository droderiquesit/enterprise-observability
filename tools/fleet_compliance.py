#!/usr/bin/env python3
"""FLEET COMPLIANCE — the agent-side denominator (§39).

`coverage_report.py` answers "is anything unmonitored?" from the monitor side.
This answers the question underneath it: **is the telemetry those monitors read
actually being collected?** A 100%-covered estate whose agents are not deployed
reports green and sees nothing, which is the failure mode this repository keeps
naming and, until now, did not measure.

Eight conditions make a host non-compliant. They are DEFINED IN POLICY
(platform/policy/agent_profiles.yaml → compliance.checks) and only implemented
here, so the standard and the measurement cannot drift:

    agent_missing        never reported at all
    agent_offline        reported once, silent since
    agent_out_of_date    below the minimum supported version
    integration_missing  an assigned profile requires a check the host lacks
    dbm_missing          SQL Server host without Database Monitoring
    apm_missing          application host with no trace telemetry
    tags_missing         Tier 1 tags absent or out of vocabulary
    ownership_missing    no `team` resolving to teams.yaml

THE DENOMINATOR IS THE INVENTORY, NOT THE HOST LIST. Computing agent coverage
from the hosts Datadog knows about always returns 100%, because a host without
an agent is not in that list. `build_inventory.py` output is therefore the
required set; the Datadog host list only supplies evidence about the hosts that
did report.

A host counts ONCE regardless of how many findings it has. The number answers
"how much of the fleet is fully instrumented", and per-finding weighting would
let a fleet improve its score without a single host becoming correct.

Modes:
    --fixtures DIR   offline, against tests/fixtures (CI and local)
    --live           Datadog /api/v1/hosts + the committed inventory
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import obs_common as oc

# Inventory kinds that are REQUIRED to carry an agent. `esxi_host` is
# deliberately absent: ESXi runs no third-party agent and is collected through
# the vCenter integration, so counting ESXi hosts as agent-missing would
# manufacture a permanent, unfixable gap. Same reasoning excludes
# `azure_resource` (Azure Monitor) and `network_device` (SNMP).
AGENT_REQUIRED_KINDS = {"host", "vm"}

# Entries in a profile's `integrations:` list that are NOT reported as host
# apps and have their own check instead. Routing them here rather than through
# integration_missing keeps `dbm_missing` and `apm_missing` meaningful.
SPECIAL_INTEGRATIONS = {"apm": "apm_missing", "dbm": "dbm_missing"}


# -----------------------------------------------------------------------------
# Normalisation — one shape, whether the source is the live API or a fixture
# -----------------------------------------------------------------------------
def normalize_host(raw: dict) -> dict:
    """A Datadog `/api/v1/hosts` record → the facts the checks need.

    Live and fixture paths BOTH go through this, so a fixture that passes is
    evidence about the live path rather than about the fixture format.
    """
    meta = raw.get("meta") or {}
    tags = oc.tags_to_map(sum((raw.get("tags_by_source") or {}).values(), []))
    platform = str(meta.get("platform") or tags.get("os") or "").lower()
    # Datadog reports "Windows Server 2022" / "Linux" / "Darwin". Only the
    # family matters for profile assignment, and only two families exist here.
    os_family = "windows" if "win" in platform else ("linux" if platform else "")
    return {
        "name": raw.get("name") or raw.get("host_name") or "",
        "up": bool(raw.get("up", False)),
        "last_reported_ts": raw.get("last_reported_time") or 0,
        "agent_version": str(meta.get("agent_version") or ""),
        "os_family": os_family,
        "apps": sorted({str(a).lower() for a in (raw.get("apps") or [])}),
        "tags": tags,
    }


def parse_version(v: str) -> tuple:
    """`7.55.1` → (7, 55, 1). Unparseable → (0, 0, 0), i.e. out of date.

    Treating an unreadable version as ancient is the safe direction: it puts a
    host on the remediation list instead of silently exempting it.
    """
    parts = []
    for chunk in str(v).split("-")[0].split("."):
        parts.append(int(chunk) if chunk.isdigit() else 0)
    return tuple((parts + [0, 0, 0])[:3])


# -----------------------------------------------------------------------------
# Profile assignment — from entity tags, exactly as the standard describes
# -----------------------------------------------------------------------------
def assign_profiles(facts: dict, agent_profiles: dict) -> list[str]:
    """Which profiles this entity should carry.

    `all_hosts: true` matches everything; every other key is a tag whose value
    must appear in the rule's allowed list. An entity may match several role
    profiles and must match at most one OS profile — the os_family fact is
    single-valued, so that holds by construction.

    A profile whose match keys reference a tag the entity does not carry does
    NOT match. That is the honest behaviour: an untagged datastore is not
    assumed to be SQL Server, it is reported as untagged by `tags_missing`.
    """
    out = []
    for pid, prof in agent_profiles["agent_profiles"].items():
        match = prof.get("match") or {}
        if match.get("all_hosts"):
            out.append(pid)
            continue
        if all(facts.get(key) in allowed for key, allowed in match.items()):
            out.append(pid)
    return sorted(out)


def required_integrations(profile_ids: list[str], agent_profiles: dict) -> dict:
    """profile → the integrations it requires, minus the specially-checked ones."""
    out: dict[str, list[str]] = {}
    for pid in profile_ids:
        ints = agent_profiles["agent_profiles"][pid].get("integrations") or []
        out[pid] = [i for i in ints if i not in SPECIAL_INTEGRATIONS]
    return out


# -----------------------------------------------------------------------------
# The evaluation
# -----------------------------------------------------------------------------
def evaluate(inventory: dict, hosts: list[dict], policy: dict,
             agent_profiles: dict, now_ts: float) -> dict:
    fleet = agent_profiles["fleet"]
    vocab = policy["global"]["tag_vocabulary"]
    min_version = parse_version(fleet["minimum_agent_version"])
    offline_after = float(fleet["offline_after_minutes"]) * 60.0
    base = agent_profiles["agent_profiles"]["base-infrastructure"]
    required_tags = base["agent_config"]["required_host_tags"]
    exempt_rules = fleet.get("exempt_when_tags") or []

    by_name = {h["name"]: h for h in (normalize_host(r) for r in hosts) if h["name"]}

    findings: dict[str, list] = defaultdict(list)
    per_host: list[dict] = []
    exempt: list[str] = []
    profile_counts: Counter = Counter()

    for res in inventory["resources"]:
        if res.get("kind") not in AGENT_REQUIRED_KINDS:
            continue
        name = res.get("name") or ""
        tags = dict(res.get("tags") or {})

        if any(tags.get(r["tag"]) in r["values"] for r in exempt_rules):
            exempt.append(name)
            continue

        host = by_name.get(name)
        # Entity tags win over agent tags: the inventory is the platform's
        # record of intent, and an agent tag that disagrees with it is itself a
        # finding (coverage_report C3), not a correction to apply here.
        if host:
            merged = dict(host["tags"])
            merged.update(tags)
        else:
            merged = tags

        facts = {
            "os_family": host["os_family"] if host else "",
            "service_archetype": merged.get("service_archetype"),
            "db_engine": merged.get("db_engine"),
            "env": merged.get("env"),
        }
        profiles = assign_profiles(facts, agent_profiles)
        for pid in profiles:
            profile_counts[pid] += 1

        problems: list[str] = []

        # --- agent presence and health ---------------------------------------
        if host is None:
            problems.append("agent_missing")
        else:
            silent_for = now_ts - float(host["last_reported_ts"] or 0)
            if not host["up"] or silent_for > offline_after:
                problems.append("agent_offline")
            if parse_version(host["agent_version"]) < min_version:
                problems.append("agent_out_of_date")

        # --- what the assigned profiles require -------------------------------
        # Only checkable where an agent reported: a missing agent already
        # implies every integration is missing, and listing eight consequences
        # of one cause makes the report harder to act on, not easier.
        if host is not None:
            apps = set(host["apps"])
            for pid, ints in required_integrations(profiles, agent_profiles).items():
                # An OS profile could not be assigned without an os_family
                # fact; skipping is right, and the host is already flagged by
                # whichever check produced the missing fact.
                for integration in ints:
                    if integration not in apps:
                        problems.append("integration_missing")
                        findings["integration_missing"].append(
                            {"host": name, "profile": pid, "integration": integration})
            if "sqlserver" in profiles:
                if "dbm" not in apps and merged.get("dbm") != "true":
                    problems.append("dbm_missing")
            if "application" in profiles:
                if "apm" not in apps:
                    problems.append("apm_missing")

        # --- tags and ownership ----------------------------------------------
        bad_tags = []
        for tag in required_tags:
            value = merged.get(tag)
            if value is None:
                bad_tags.append(f"missing_tag:{tag}")
            elif tag in vocab and value not in vocab[tag]:
                bad_tags.append(f"invalid_{tag}:{value}")
        if bad_tags:
            problems.append("tags_missing")
            findings["tags_missing"].append({"host": name, "violations": bad_tags})

        team = merged.get("team")
        if not team or team not in policy["teams"]:
            problems.append("ownership_missing")
            findings["ownership_missing"].append({"host": name, "team": team})

        problems = sorted(set(problems))
        for p in problems:
            # integration_missing / tags_missing / ownership_missing already
            # recorded their detail above; the rest carry only the host.
            if p not in ("integration_missing", "tags_missing", "ownership_missing"):
                findings[p].append({"host": name})
        per_host.append({
            "host": name,
            "kind": res.get("kind"),
            "env": merged.get("env"),
            "profiles": profiles,
            "agent_version": host["agent_version"] if host else None,
            "findings": problems,
            "compliant": not problems,
        })

    required = len(per_host)
    compliant = sum(1 for h in per_host if h["compliant"])
    ratio = agent_profiles["compliance"]["ratio"]
    pct = round(compliant / required * 100, 1) if required else 0.0

    return {
        "generated_at": oc.utcnow().isoformat(),
        "summary": {
            "hosts_required": required,
            "hosts_compliant": compliant,
            "hosts_exempt": len(exempt),
            "compliance_pct": pct,
            "target_pct": ratio["report_targets"]["target_pct"],
            "gate_enabled": ratio["report_targets"]["gate"],
            "minimum_agent_version": fleet["minimum_agent_version"],
            "hosts_reporting": len(by_name),
            "finding_counts": {k: len(v) for k, v in sorted(findings.items())},
            "profile_assignments": dict(sorted(profile_counts.items())),
        },
        # A denominator of zero is NOT 100% compliant. It means nothing is
        # known, and the report must say which of the two it is — an empty
        # inventory has produced false green in more organisations than any
        # threshold ever has.
        "measured": required > 0,
        "exempt_hosts": sorted(exempt),
        "findings": {k: v[:200] for k, v in sorted(findings.items())},
        "hosts": sorted(per_host, key=lambda h: h["host"]),
    }


def to_markdown(report: dict, agent_profiles: dict) -> str:
    s = report["summary"]
    titles = {cid: c["title"] for cid, c in agent_profiles["compliance"]["checks"].items()}
    lines = [
        "# Fleet Compliance Report",
        "",
    ]
    if not report["measured"]:
        lines += [
            "**Not measured.** No agent-bearing resources are in the inventory, so "
            "there is no denominator. This is not 0% and it is not 100% — it means "
            "`build_inventory.py` has not yet discovered any host or VM.",
            "",
        ]
    lines += [
        f"- Fleet compliance: **{s['compliance_pct']}%** "
        f"({s['hosts_compliant']}/{s['hosts_required']} hosts fully instrumented) "
        f"· target {s['target_pct']}%",
        f"- Reporting agents seen: {s['hosts_reporting']} · exempt hosts: {s['hosts_exempt']}",
        f"- Minimum supported agent: {s['minimum_agent_version']}",
        f"- Gate: {'blocking' if s['gate_enabled'] else 'report-only (see agent_profiles.yaml → ratio.report_targets)'}",
        "",
        "| Check | Hosts affected |",
        "|---|---|",
    ]
    for cid, title in titles.items():
        n = s["finding_counts"].get(cid, 0)
        lines.append(f"| {cid} — {title} | {n}{'' if n == 0 else ' ⚠️'} |")
    lines += ["", "| Profile | Hosts assigned |", "|---|---|"]
    for pid, n in s["profile_assignments"].items():
        lines.append(f"| {pid} | {n} |")
    lines.append("")
    for cid, items in report["findings"].items():
        if not items:
            continue
        lines.append(f"## {cid} — {len(items)} shown (capped at 200)")
        for it in items[:20]:
            lines.append(f"- `{json.dumps(it, sort_keys=True)}`")
        lines.append("")
    return "\n".join(lines)


# -----------------------------------------------------------------------------
def fetch_live_hosts() -> list[dict]:
    """Every host Datadog has seen, including the ones that stopped reporting.

    `include_muted_hosts_data` and a large `count` are both deliberate: a muted
    host is still a fleet member, and paging through 1000 at a time is what the
    hosts endpoint's rate limit tolerates.
    """
    headers = oc.dd_headers()
    site = oc.dd_site()
    out: list[dict] = []
    start, page = 0, 1000
    while True:
        r = oc.dd_request("GET", f"{site}/api/v1/hosts", headers=headers,
                          params={"start": start, "count": page,
                                  "include_muted_hosts_data": "true"})
        r.raise_for_status()
        batch = r.json().get("host_list", [])
        out.extend(batch)
        if len(batch) < page:
            return out
        start += page


def main() -> int:
    ap = argparse.ArgumentParser()
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--live", action="store_true")
    mode.add_argument("--fixtures", type=Path)
    ap.add_argument("--inventory", type=Path, default=oc.GENERATED_DIR / "inventory.json",
                    help="ignored in --fixtures mode, which reads fleet_inventory.json")
    ap.add_argument("--out-json", type=Path, default=oc.GENERATED_DIR / "fleet_compliance.json")
    ap.add_argument("--out-md", type=Path, default=oc.GENERATED_DIR / "fleet_compliance.md")
    ap.add_argument("--min-compliance", type=float, default=None,
                    help="fail below this percentage. Omitted by default: gating "
                         "before the first rollout wave only produces a job "
                         "everyone learns to ignore")
    args = ap.parse_args()

    policy = oc.load_policy()
    agent_profiles = oc.load_agent_profiles()

    if args.live:
        # The inventory is the DENOMINATOR, and it is produced by an earlier
        # deploy step. When that step is skipped — because something before it
        # failed — this one used to raise FileNotFoundError and turn a report
        # into a second red step, obscuring the real failure above it.
        #
        # Absent input is reported the same way an empty denominator is: NOT
        # MEASURED. That is this tool's whole thesis — "a denominator of zero is
        # not 100% compliant, it means nothing is known" — and it would be a
        # poor advertisement for it to crash rather than say so.
        if not args.inventory.exists():
            print(f"fleet compliance: NOT MEASURED — no inventory at "
                  f"{args.inventory}. It is built by the coverage/compliance "
                  f"step; if that step was skipped or failed, fix that first. "
                  f"Compliance is measured against the inventory, never against "
                  f"the hosts Datadog can already see.")
            return 0 if args.min_compliance is None else 1
        inventory = json.loads(args.inventory.read_text())
        hosts = fetch_live_hosts()
        now_ts = oc.utcnow().timestamp()
    else:
        inventory = json.loads((args.fixtures / "fleet_inventory.json").read_text())
        hosts = json.loads((args.fixtures / "fleet_hosts.json").read_text())
        # Fixture timestamps are relative to a fixed `now` recorded in the
        # fixture itself. Using the wall clock would make "offline" true for
        # every host the day after the fixture was written, and the test would
        # pass for the wrong reason.
        now_ts = float(inventory["fixture_now_ts"])

    report = evaluate(inventory, hosts, policy, agent_profiles, now_ts)
    oc.write_json(args.out_json, report)
    args.out_md.parent.mkdir(parents=True, exist_ok=True)
    args.out_md.write_text(to_markdown(report, agent_profiles))
    print(json.dumps(report["summary"], indent=2))

    if args.min_compliance is None:
        return 0
    if not report["measured"]:
        print("FAIL: --min-compliance was requested but there is no denominator")
        return 1
    ok = report["summary"]["compliance_pct"] >= args.min_compliance
    print(f"fleet compliance gate: {'OK' if ok else 'FAIL'} "
          f"({report['summary']['compliance_pct']}% vs {args.min_compliance}%)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
