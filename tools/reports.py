#!/usr/bin/env python3
"""REPORT ENGINE — the five report families of §34.

    "What question is somebody actually asking, and can we answer it from what
     the estate already emits?"

THE CONSTRAINT THAT SHAPES THIS FILE. Every report answers its question from
telemetry and platform data that ALREADY EXIST. Not one report may require a new
dashboard, a new monitor, or a new metric. That rule is what stops a report
catalog from becoming the thing §33 just spent fifteen dashboards learning not
to build: a surface per question, each one plausible on its own and collectively
unmaintainable.

The catalog lives in `platform/policy/reports.yaml` — id, family, audience, the
question in the reader's own words, the data sources, the cadence, and what the
reader is expected to DO. This file implements exactly those ids; the test suite
asserts the two agree in both directions.

MODES

  --fixtures DIR   offline, against tests/fixtures. Runs on every pull request,
                   with no credentials, which is why the ops family is useful at
                   review time and not only at 6am on a Tuesday.
  --live           against the live Datadog estate, including the runtime facts
                   (monitor state, alert volume, hourly transitions) that no
                   amount of static analysis can produce.

WHAT OFFLINE MEANS FOR A RUNTIME QUESTION. Three of the operations reports ask
questions only the running estate can answer: which monitors never fire, which
fire constantly, which oscillate. Offline they do NOT go quiet and they do NOT
guess. They answer the structural half of the same question — which monitors
CANNOT fire here, which are BUILT to be noisy, which are BUILT to flap — and
label the answer `evidence: structural`. A report that silently degrades into a
weaker claim is worse than one that says which claim it is making.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import build_inventory
import coverage_report as cr
import monitor_scorecard as ms
import obs_common as oc
import profile_engine
import publish_runbooks as pr

# The registry. A report is a function of one Context that returns one dict.
REPORTS: dict[str, callable] = {}


def report(rid: str):
    def deco(fn):
        REPORTS[rid] = fn
        return fn
    return deco


# =============================================================================
# CONTEXT — every source, loaded once
# =============================================================================
class Context:
    """Everything the reports read, resolved once.

    Loading each source once and passing it down is not just cheaper: it is what
    makes two reports in the same run incapable of disagreeing about how many
    monitors exist.
    """

    def __init__(self, policy, monitors, slos, inventory, assignments,
                 live=False, runtime=None):
        self.policy = policy
        self.monitors = monitors
        self.slos = slos
        self.inventory = inventory
        self.assignments = assignments
        self.live = live
        self.runtime = runtime or {}
        self.cat = policy["reports_doc"]
        self.thresholds = self.cat["thresholds"]

        self.instances = oc.expand_instances(policy)
        self.tags = {m["id"]: oc.tags_to_map(m.get("tags")) for m in monitors}
        self.managed = {mid for mid, t in self.tags.items()
                        if t.get("managed_by") == "terraform"}
        self.services = oc.load_services()
        self.durability_ok = oc.durability_covered_types(policy)

    # -- small shared accessors ------------------------------------------------
    def monitor_rows(self):
        """(monitor, tagmap) for the TERRAFORM-MANAGED estate only.

        Click-ops monitors are reported by name in the platform family; they are
        excluded everywhere else because grading a monitor this platform did not
        write against this platform's contract produces findings nobody can fix.
        """
        for m in self.monitors:
            if m["id"] in self.managed:
                yield m, self.tags[m["id"]]

    def arch(self, aid):
        return self.policy["archetypes"].get(aid)

    def kind_of(self, aid):
        a = self.arch(aid)
        return oc.entity_kind(self.policy, a["resource_type"]) if a else None


# =============================================================================
# STRUCTURAL HEURISTICS — used when the runtime answer is unavailable
# =============================================================================
_WINDOW = re.compile(r"^(last|next)_(\d+)([mhdw])$")
_UNIT_MINUTES = {"m": 1, "h": 60, "d": 1440, "w": 10080}


def window_minutes(window: str | None) -> int | None:
    """`last_15m` -> 15. Returns None for check-count and forecast windows.

    A `next_*` window is a forecast: it cannot flap, because it is not asserting
    anything about right now. A `last_N_checks` window is counted in checks, not
    minutes, and comparing it to a duration would be a category error.
    """
    m = _WINDOW.match(window or "")
    if not m or m.group(1) == "next":
        return None
    return int(m.group(2)) * _UNIT_MINUTES[m.group(3)]


def noise_risk(policy: dict, arch: dict, inst: dict) -> tuple[int, list[str]]:
    """How noisy is this monitor BUILT to be, before it has ever fired?

    Not a prediction of alert volume — nothing static can predict that. It is
    the list of design choices that produce noise, which is the actionable half
    anyway: you cannot retune a threshold you have not identified.
    """
    reasons: list[str] = []
    score = 0
    behavioral = arch["signal"] in policy["global"]["detection_policy"]["behavioral_signals"]
    predictive = any(fn in arch["query"] for fn in oc.PREDICTIVE_FUNCS)

    if behavioral and not predictive:
        score += 2
        reasons.append("fixed threshold on a behavioural signal — it will fire on every "
                       "seasonal peak the baseline would have absorbed")
    gb = arch.get("group_by") or []
    if len(gb) >= 2 and not arch.get("notify_by"):
        score += 2
        reasons.append(f"grouped by {gb} with no collapse key — one shared-cause event "
                       "notifies once per group")
    w = window_minutes(arch.get("evaluation_window"))
    if w is not None and w <= 5:
        score += 1
        reasons.append(f"{w}m evaluation window — short enough to alert on a single "
                       "scrape gap")
    if inst["pages"] and arch["impact_class"] != "customer_impact":
        score += 2
        reasons.append(f"pages on a {arch['impact_class']} signal — waking somebody for "
                       "something that is not customer impact")
    return score, reasons


def flap_risk(policy: dict, arch: dict) -> list[str]:
    """The design choices that make a monitor oscillate rather than alert."""
    reasons: list[str] = []
    behavioral = arch["signal"] in policy["global"]["detection_policy"]["behavioral_signals"]
    w = window_minutes(arch.get("evaluation_window"))
    floor = policy["reports_doc"]["thresholds"]["flap_prone_window_minutes"]
    if behavioral and w is not None and w < floor:
        reasons.append(f"behavioural signal `{arch['signal']}` evaluated over {w}m "
                       f"(below the {floor}m floor) — the metric crosses the line in "
                       "both directions faster than a human can respond")
    # `critical_recovery` is the hysteresis band; modules/monitor_factory reads it
    # straight out of `thresholds`, so its absence is a real gap and not a
    # modelling artefact. Without it the monitor resolves the instant the metric
    # dips back over the line, and re-alerts on the next sample.
    if behavioral and arch["detection"] == "threshold" \
            and "critical_recovery" not in (arch.get("thresholds") or {}):
        reasons.append("threshold on a behavioural signal with no `critical_recovery` "
                       "band — it resolves the instant the metric dips back, then "
                       "re-alerts on the next sample")
    return reasons


# =============================================================================
# EXECUTIVE
# =============================================================================
@report("exec-service-health")
def _exec_service_health(ctx: Context) -> dict:
    live_status = {}
    for s in ctx.slos:
        st = oc.tags_to_map(s.get("tags") if isinstance(s.get("tags"), list) else [])
        overall = s.get("overall_status") or [{}]
        overall = overall[0] if isinstance(overall, list) and overall else {}
        if st.get("slo_id"):
            live_status[st["slo_id"]] = overall

    rows, attention = [], 0
    for sid, s in sorted(ctx.policy["slos"].items()):
        status = live_status.get(sid, {})
        dep = s.get("telemetry_dependency")
        problem = None
        if dep:
            problem = f"declared telemetry dependency: {dep}"
        elif status.get("error"):
            problem = f"live status error: {status['error']}"
        elif ctx.live and status.get("sli") is not None and status["sli"] < s["target"]:
            problem = f"SLI {status['sli']} is below the {s['target']} objective"
        if problem:
            attention += 1
        rows.append({
            "slo": sid, "name": s["name"], "domain": s["domain"], "team": s["team"],
            "scope": s["scope"], "target": s["target"],
            "sli": status.get("sli"), "problem": problem,
        })

    # Per-service objectives are GENERATED from the tier0 service registry rather
    # than written into slos.yaml (see the two scopes at the top of that file),
    # so counting catalog entries alone would report zero and read as a gap.
    tier0 = [n for n, svc in ctx.services.items() if svc.get("tier") == "tier0"]
    return {
        "summary": {
            "objectives": len(rows) + len(tier0),
            "domain_objectives": len(rows),
            "per_service_objectives": len(tier0),
            "tier0_services": len(tier0),
            "needing_attention": attention,
        },
        "rows": [r for r in rows if r["problem"]] or rows[:10],
        "note": "Objectives with a problem are listed; when there are none, the first "
                "ten are shown so the report is never an empty page that looks broken.",
    }


@report("exec-risk-posture")
def _exec_risk_posture(ctx: Context) -> dict:
    # Reuse the coverage report rather than reimplementing its checks. Two
    # implementations of "is this covered?" would eventually disagree, and the
    # executive number is the one people would quote.
    checks = cr.run_checks(ctx.inventory, ctx.assignments, ctx.monitors,
                           ctx.slos, ctx.policy)
    s = checks["summary"]

    by_team = defaultdict(lambda: {"resources": 0, "unowned": 0, "violations": 0,
                                   "observe_only": 0})
    for a in ctx.assignments["assignments"]:
        t = by_team[a["team"]]
        t["resources"] += 1
        if a["owner_source"] == "unowned_pool":
            t["unowned"] += 1
        if a["violations"]:
            t["violations"] += 1
        if a["alert_band"] == "none":
            t["observe_only"] += 1

    return {
        "summary": {
            "resources": s["resources_total"],
            "coverage_pct": s["coverage_pct"],
            "unmonitored": s["check_counts"]["C1"],
            "unowned": s["check_counts"]["C2"],
            "unactionable": s["check_counts"]["C15"] + s["check_counts"]["C16"],
            "click_ops_monitors": s["check_counts"]["C9"],
            "needing_attention": s["check_counts"]["C1"] + s["check_counts"]["C2"],
        },
        "rows": [dict(team=t, **v) for t, v in sorted(by_team.items())],
    }


@report("exec-alert-load")
def _exec_alert_load(ctx: Context) -> dict:
    """Paging load per team.

    Live, this is pages per week. Offline it is the number of distinct patterns
    that CAN page a team, which is the ceiling on that number and the thing a
    pull request actually changes.
    """
    pages_per_team = ctx.runtime.get("pages_per_team_week", {})
    budget = ctx.thresholds["pages_per_team_per_week"]

    owned = defaultdict(lambda: {"paging_patterns": 0, "p1": 0, "monitors": 0})
    for _, t in ctx.monitor_rows():
        team = t.get("team", "unowned")
        owned[team]["monitors"] += 1
        if t.get("pages") == "true":
            owned[team]["paging_patterns"] += 1
        if (t.get("priority") or "").upper() == "P1":
            owned[team]["p1"] += 1

    rows, over = [], 0
    for team, v in sorted(owned.items()):
        actual = pages_per_team.get(team)
        if actual is not None and actual > budget:
            over += 1
        rows.append({
            "team": team, **v,
            "pages_last_week": actual,
            "budget": budget,
            "over_budget": actual is not None and actual > budget,
            "oncall": ctx.policy["teams"].get(team, {}).get("oncall"),
        })
    return {
        "summary": {
            "teams": len(rows),
            "paging_monitors": sum(r["paging_patterns"] for r in rows),
            "teams_over_budget": over,
            "needing_attention": over,
        },
        "rows": rows,
    }


# =============================================================================
# OPERATIONS — the family that was missing
# =============================================================================
@report("ops-silent-monitors")
def _ops_silent(ctx: Context) -> dict:
    """Monitors that never fire.

    A monitor that has never fired is either correct and lucky, or watching
    something that no longer exists. The second is the dangerous case: it looks
    like coverage on every report in this repository while providing none.
    """
    rows = []
    if ctx.live:
        cutoff = oc.utcnow() - dt.timedelta(days=ctx.thresholds["silent_monitor_days"])
        for m, t in ctx.monitor_rows():
            state = (m.get("overall_state") or "").lower()
            modified = ctx.runtime.get("state_modified", {}).get(m["id"])
            if state == "no data":
                rows.append({"monitor": m.get("name"), "team": t.get("team"),
                             "archetype": t.get("archetype"), "evidence": "live",
                             "why": "reporting No Data — the query matches nothing in "
                                    "this org right now"})
            elif state == "ok" and modified and modified < cutoff:
                rows.append({"monitor": m.get("name"), "team": t.get("team"),
                             "archetype": t.get("archetype"), "evidence": "live",
                             "why": f"OK and untransitioned since {modified.date()} "
                                    f"(> {ctx.thresholds['silent_monitor_days']}d)"})

    # Structural half — available with or without credentials.
    #
    # (a) A monitor deployed into an (env, band) the estate does not populate
    #     cannot fire here at all. This is the cheap, certain case.
    #     Reported per (env, band), NOT per monitor: eighty rows repeating the same
    #     sentence about the same empty band is a wall of text, and the fix is one
    #     decision about that band rather than eighty about monitors.
    populated = {(a["env"], a["alert_band"]) for a in ctx.assignments["assignments"]}
    empty = Counter((i["env"], i["band"]) for i in ctx.instances
                    if (i["env"], i["band"]) not in populated)
    for (env, band), n in sorted(empty.items()):
        rows.append({"monitor": f"{n} patterns on {env}/{band}", "team": None,
                     "archetype": None, "evidence": "structural",
                     "why": f"no resource in the estate is assigned to {env}/{band}, so "
                            f"these {n} monitor patterns have nothing to evaluate "
                            "against — either the band is unused and the patterns should "
                            "be retired, or the estate is mis-tagged"})
    # (b) An objective that declares its telemetry may be absent makes every
    #     monitor hanging off it structurally silent, however healthy it looks.
    dependent = {sid for sid, s in ctx.policy["slos"].items()
                 if s.get("telemetry_dependency")}
    seen: set[str] = set()
    for i in ctx.instances:
        if i["slo_id"] in dependent and i["archetype"] not in seen:
            seen.add(i["archetype"])
            rows.append({"monitor": i["archetype"], "team": None,
                         "archetype": i["archetype"], "evidence": "structural",
                         "why": f"its objective {i['slo_id']} declares a telemetry "
                                "dependency — the signal may never arrive"})
    return {
        "summary": {
            "silent": len(rows),
            "live_evidence": sum(1 for r in rows if r["evidence"] == "live"),
            "structural_evidence": sum(1 for r in rows if r["evidence"] == "structural"),
            "needing_attention": len(rows),
        },
        "rows": rows[:100],
    }


@report("ops-noisy-monitors")
def _ops_noisy(ctx: Context) -> dict:
    limit = ctx.thresholds["noisy_monitor_alerts_30d"]
    alerts = ctx.runtime.get("alerts_30d", {})
    rows = []

    if ctx.live:
        for mid, n in sorted(alerts.items(), key=lambda kv: -kv[1]):
            if n >= limit:
                rows.append({"monitor": mid, "alerts_30d": n, "evidence": "live",
                             "why": f"{n} alerts in 30 days against a budget of {limit}"})

    seen: set[str] = set()
    for i in ctx.instances:
        if i["archetype"] in seen:
            continue
        a = ctx.arch(i["archetype"])
        score, reasons = noise_risk(ctx.policy, a, i)
        if score >= 3:
            seen.add(i["archetype"])
            rows.append({"monitor": i["archetype"], "alerts_30d": None,
                         "evidence": "structural", "noise_risk": score,
                         "why": "; ".join(reasons)})
    return {
        "summary": {
            "noisy": len(rows),
            "threshold_30d": limit,
            "live_evidence": sum(1 for r in rows if r["evidence"] == "live"),
            "needing_attention": len(rows),
        },
        "rows": rows[:100],
    }


@report("ops-flapping-monitors")
def _ops_flapping(ctx: Context) -> dict:
    limit = ctx.thresholds["flapping_transitions_per_hour"]
    hourly = ctx.runtime.get("max_hourly_24h", {})
    rows = []
    if ctx.live:
        for mid, n in sorted(hourly.items(), key=lambda kv: -kv[1]):
            if n >= limit:
                rows.append({"monitor": mid, "transitions_per_hour": n,
                             "evidence": "live",
                             "why": f"{n} transitions in a single hour (limit {limit}) — "
                                    "every page is stale before it is read"})
    seen: set[str] = set()
    for i in ctx.instances:
        if i["archetype"] in seen:
            continue
        reasons = flap_risk(ctx.policy, ctx.arch(i["archetype"]))
        if reasons:
            seen.add(i["archetype"])
            rows.append({"monitor": i["archetype"], "transitions_per_hour": None,
                         "evidence": "structural", "why": "; ".join(reasons)})
    return {
        "summary": {
            "flapping": len(rows),
            "transitions_per_hour_limit": limit,
            "live_evidence": sum(1 for r in rows if r["evidence"] == "live"),
            "needing_attention": len(rows),
        },
        "rows": rows[:100],
    }


@report("ops-services-without-telemetry")
def _ops_no_telemetry(ctx: Context) -> dict:
    """Two different failures that look identical on a coverage report.

    A service with no monitor was never onboarded. A service with monitors that
    all report No Data was onboarded and never instrumented. Both read as
    "covered" if you only count monitors, and only the second one is silently
    lying — which is why they are separated here rather than summed.
    """
    # Coverage is judged the SAME way coverage_report.py judges it — through the
    # service archetype's mandatory packs — not by looking for the service's own
    # name in a monitor tag. Platform monitors are generated per (archetype, env,
    # band) and tagged with the DOMAIN's service identity, so a name search would
    # report every correctly covered service as uncovered.
    deployed = defaultdict(set)
    for _, t in ctx.monitor_rows():
        if t.get("archetype"):
            deployed[t["archetype"]].add((t.get("env"), t.get("alert_band")))

    slo_services = {s["service"] for s in ctx.policy["slos"].values()}
    domains_with_slo = {s["domain"] for s in ctx.policy["slos"].values()}
    for s in ctx.slos:
        for svc in s.get("service_tags") or []:
            slo_services.add(svc)

    nodata_services = ctx.runtime.get("nodata_services", set())
    tiers = ctx.policy["tiers"]

    rows = []
    for name, svc in sorted(ctx.services.items()):
        problems = []
        sa = svc.get("service_archetype", "")
        band = tiers[svc["tier"]]["alert_band"]
        expected = cr._covering_archetypes(ctx.policy, sa)
        missing = sorted(
            a for a in expected
            if band in ctx.policy["archetypes"][a]["bands"]
            and "prod" in ctx.policy["archetypes"][a]["envs"]
            and ("prod", band) not in deployed.get(a, set()))
        if missing:
            problems.append("mandatory archetypes not deployed for prod/"
                            f"{band}: {', '.join(missing[:4])}")
        domain = ctx.policy["service_archetypes"].get(sa, {}).get("domain")
        if name not in slo_services and domain not in domains_with_slo:
            problems.append("no objective covers it, and its domain has none either")
        if name in nodata_services:
            problems.append("every monitor on it is reporting No Data — instrumented on "
                            "paper only")
        if problems:
            rows.append({"service": name, "team": svc.get("team"),
                         "tier": svc.get("tier"),
                         "service_archetype": svc.get("service_archetype"),
                         "entity_kind": oc.entity_kind_of_service_archetype(
                             ctx.policy, svc.get("service_archetype", "")),
                         "problems": problems,
                         "evidence": "live" if name in nodata_services else "structural"})
    return {
        "summary": {
            "registered_services": len(ctx.services),
            "without_telemetry": len(rows),
            "needing_attention": len(rows),
        },
        "rows": rows,
    }


@report("ops-missing-ownership")
def _ops_ownership(ctx: Context) -> dict:
    """An inferred owner is not an owner.

    The profile engine never leaves a resource ownerless — it falls back to the
    domain's default team and records the inference. That fallback is what keeps
    the estate monitored; it is NOT evidence that anybody agreed to carry the
    pager, which is what this report exists to separate.
    """
    resource_rows = defaultdict(lambda: {"unowned_pool": 0, "domain_default": 0})
    for a in ctx.assignments["assignments"]:
        if a["owner_source"] in ("unowned_pool", "domain_default"):
            resource_rows[(a["domain"], a["team"])][a["owner_source"]] += 1

    monitor_rows = []
    for m, t in ctx.monitor_rows():
        missing = [k for k in ("team", "owner", "service") if not t.get(k)]
        if missing:
            monitor_rows.append({"monitor": m.get("name"), "missing_tags": missing})
        elif t["team"] not in ctx.policy["teams"]:
            monitor_rows.append({"monitor": m.get("name"),
                                 "missing_tags": [f"unregistered team {t['team']}"]})

    pool = ctx.policy["teams_doc"]["unowned_pool"]
    rows = [{"domain": d, "holding_team": team, **v}
            for (d, team), v in sorted(resource_rows.items())]
    return {
        "summary": {
            "resources_with_inferred_owner": sum(
                r["unowned_pool"] + r["domain_default"] for r in rows),
            "resources_in_unowned_pool": sum(r["unowned_pool"] for r in rows),
            "unowned_pool_sla_days": pool["max_age_days"],
            "monitors_missing_ownership_tags": len(monitor_rows),
            "needing_attention": sum(r["unowned_pool"] for r in rows) + len(monitor_rows),
        },
        "rows": rows,
        "monitors": monitor_rows[:50],
    }


@report("ops-runbook-coverage")
def _ops_runbooks(ctx: Context) -> dict:
    """Is the runbook ATTACHED, and does it say anything?

    Three distinct failures, in increasing order of how convincing they look
    while being useless: the runbook is not registered; it is registered but has
    no notebook id, so nothing can be attached; it is attached and still full of
    TODO markers. The third is the one that gets discovered at 3am.
    """
    reg = ctx.policy["runbooks"]
    runbook_dir = oc.PLATFORM_DIR / "runbooks"

    unfinished: dict[str, int] = {}
    for rid, r in reg.items():
        path = runbook_dir / r["source"]
        if path.exists():
            n = pr.unfinished_sections(path.read_text())
            if n:
                unfinished[rid] = n

    per_domain = defaultdict(lambda: {"archetypes": 0, "unregistered": 0,
                                      "no_notebook_id": 0, "unfinished": 0})
    for aid, a in sorted(ctx.policy["archetypes"].items()):
        d = per_domain[a["domain"]]
        d["archetypes"] += 1
        rb = reg.get(a["runbook"])
        if not rb:
            d["unregistered"] += 1
            continue
        if not rb.get("id"):
            d["no_notebook_id"] += 1
        if a["runbook"] in unfinished:
            d["unfinished"] += 1

    unattached = [m.get("name") for m, t in ctx.monitor_rows()
                  if not t.get("runbook_notebook")]
    tolerance = ctx.thresholds["runbook_unfinished_sections"]
    return {
        "summary": {
            "runbooks": len(reg),
            "runbooks_with_unfinished_sections": len(unfinished),
            "unfinished_tolerance": tolerance,
            "monitors_without_an_attached_notebook": len(unattached),
            "needing_attention": len(unfinished) + len(unattached),
        },
        "rows": [dict(domain=d, **v) for d, v in sorted(per_domain.items())],
        "monitors_without_attachment": unattached[:50],
    }


@report("ops-oncall-coverage")
def _ops_oncall(ctx: Context) -> dict:
    """Does every paging monitor end at a human who agreed to be woken?

    Three links have to hold, and each fails silently on its own: the team runs
    a rotation, the escalation target exists, and the notification profile
    defines a route for that priority that actually pages. A monitor tagged
    `pages:true` routed through a profile with no page route for its priority is
    the worst of the three — it reports as covered and notifies nobody.
    """
    profiles = ctx.policy["notification_profiles"]["notification_profiles"]
    teams = ctx.policy["teams"]

    per_team = defaultdict(lambda: {"paging_monitors": 0, "p1": 0,
                                    "routes_that_do_not_page": 0})
    for _, t in ctx.monitor_rows():
        if t.get("pages") != "true":
            continue
        team = t.get("team", "unowned")
        v = per_team[team]
        v["paging_monitors"] += 1
        if (t.get("priority") or "").upper() == "P1":
            v["p1"] += 1
        prof = profiles.get(t.get("notification_profile", ""))
        route = (prof or {}).get("routes", {}).get((t.get("priority") or "").upper())
        if not route or not route.get("page"):
            v["routes_that_do_not_page"] += 1

    rows, attention = [], 0
    for team, v in sorted(per_team.items()):
        spec = teams.get(team, {})
        problems = []
        if not spec:
            problems.append("owning team is not registered in teams.yaml")
        else:
            if not spec.get("oncall"):
                problems.append("team runs no rotation, but owns monitors that page")
            esc = spec.get("escalation_to")
            # `*-leadership` targets are deliberately outside the team registry:
            # escalation past the platform ends at a person with a budget, not
            # at another rota. Anything else must resolve to a real team.
            if esc and esc not in teams and not str(esc).endswith("-leadership"):
                problems.append(f"escalation target {esc!r} is neither a team nor a "
                                "leadership group")
            if not spec.get("business_hours_timezone"):
                problems.append("no timezone declared — 'business hours' is undefined")
        if v["routes_that_do_not_page"]:
            problems.append(f"{v['routes_that_do_not_page']} paging monitors route "
                            "through a profile with no page route for their priority")
        if problems:
            attention += 1
        rows.append({"team": team, **v, "oncall": spec.get("oncall"),
                     "escalation_to": spec.get("escalation_to"),
                     "servicenow_group": spec.get("servicenow_assignment_group"),
                     "problems": problems})
    return {
        "summary": {
            "teams_owning_paging_monitors": len(rows),
            "paging_monitors": sum(r["paging_monitors"] for r in rows),
            "teams_with_a_gap": attention,
            "needing_attention": attention,
        },
        "rows": rows,
    }


# =============================================================================
# PLATFORM
# =============================================================================
@report("plat-monitor-quality")
def _plat_quality(ctx: Context) -> dict:
    sc = ms.build(ctx.policy)
    rows = [{"entity_kind": k, **v} for k, v in sc["by_entity_kind"].items()]
    return {
        "summary": {
            "monitors_scored": sc["summary"]["monitors_scored"],
            "fleet_average": sc["summary"]["fleet_average"],
            "fleet_grade": sc["summary"]["fleet_grade"],
            "below_c": sc["summary"]["below_c"],
            "failing": sc["summary"]["failing"],
            "entity_kinds_below_minimum": sum(1 for r in rows if not r["meets_minimum"]),
            "needing_attention": sc["summary"]["below_c"] + sum(
                1 for r in rows if not r["meets_minimum"]),
        },
        "rows": rows,
        "entity_findings": sc["entity_findings"],
        "by_team": sc["by_team"],
    }


@report("plat-detection-mix")
def _plat_detection(ctx: Context) -> dict:
    per_domain = defaultdict(lambda: Counter())
    for a in ctx.policy["archetypes"].values():
        per_domain[a["domain"]][a["detection"]] += 1

    predictive = {"anomaly", "seasonal_anomaly", "forecast", "outlier", "rate_of_change"}
    rows = []
    for d, c in sorted(per_domain.items()):
        total = sum(c.values())
        pred = sum(n for k, n in c.items() if k in predictive)
        rows.append({"domain": d, "archetypes": total, "predictive": pred,
                     "fixed_threshold": c.get("threshold", 0),
                     "predictive_pct": round(100.0 * pred / total, 1) if total else 0.0,
                     "mix": dict(sorted(c.items()))})
    overall = Counter(a["detection"] for a in ctx.policy["archetypes"].values())
    total = sum(overall.values())
    pred = sum(n for k, n in overall.items() if k in predictive)
    # The defect is not "a low predictive percentage" — a filesystem is full at
    # 100% and needs no baseline. It is a FIXED threshold on a BEHAVIOURAL
    # signal, which is the thing somebody has to retune per service forever.
    behavioural = set(ctx.policy["global"]["detection_policy"]["behavioral_signals"])
    wrong = [aid for aid, a in sorted(ctx.policy["archetypes"].items())
             if a["detection"] == "threshold" and a["signal"] in behavioural
             and not a.get("rationale_fixed_threshold")]
    return {
        "summary": {
            "archetypes": total,
            "predictive": pred,
            "predictive_pct": round(100.0 * pred / total, 1) if total else 0.0,
            "domains_below_40pct_predictive": sum(
                1 for r in rows if r["predictive_pct"] < 40.0),
            "unjustified_fixed_thresholds_on_behavioural_signals": len(wrong),
            "needing_attention": len(wrong),
        },
        "unjustified_fixed_thresholds": wrong,
        "rows": sorted(rows, key=lambda r: r["predictive_pct"]),
        "note": "A domain drifting below ~40% predictive is drifting towards per-service "
                "threshold tuning, which does not survive scale. Absolute thresholds are "
                "correct for the signals in global.yaml -> absolute_threshold_allowed_"
                "signals, so a low percentage is a question, not automatically a defect.",
    }


@report("plat-estate-budget")
def _plat_budget(ctx: Context) -> dict:
    card = ctx.policy["global"]["cardinality"]
    paging = [i for i in ctx.instances if i["pages"]]
    p1 = [i for i in ctx.instances if i["priority"] == "P1"]

    def line(name, used, budget):
        return {"budget": name, "used": used, "limit": budget,
                "pct": round(100.0 * used / budget, 1) if budget else 0.0,
                "over": used > budget}

    rows = [
        line("managed monitor patterns", len(ctx.instances),
             card["max_total_managed_monitors"]),
        line("paging patterns", len(paging), card["max_paging_monitors"]),
        line("P1 patterns", len(p1), card["max_p1_monitors"]),
    ]
    per_arch = Counter(i["archetype"] for i in ctx.instances)
    worst = per_arch.most_common(5)
    return {
        "summary": {
            "planned_patterns": len(ctx.instances),
            "deployed_monitors": len(ctx.managed),
            "paging": len(paging),
            "needing_attention": sum(1 for r in rows if r["over"]),
        },
        "rows": rows,
        "largest_archetypes": [{"archetype": a, "instances": n,
                                "limit": card["max_instances_per_archetype"]}
                               for a, n in worst],
        "note": "Budget pressure is answered by deleting monitors. Raising the budget "
                "first is how an estate gets to 4,000 monitors nobody reads.",
    }


@report("plat-governance-debt")
def _plat_debt(ctx: Context) -> dict:
    today = dt.date.today()
    rows = []
    for e in ctx.policy["exceptions"]:
        exp = e["expires"]
        if not isinstance(exp, dt.date):
            exp = dt.date.fromisoformat(str(exp))
        days = (exp - today).days
        rows.append({"exception": e["id"], "control": e.get("control"),
                     "owner": e["owner"], "expires": str(exp), "days_left": days,
                     "expired": days < 0, "scope": e.get("scope")})
    rows.sort(key=lambda r: r["days_left"])
    expiring = [r for r in rows if 0 <= r["days_left"] <= 30]
    expired = [r for r in rows if r["expired"]]
    return {
        "summary": {
            "exceptions": len(rows),
            "expired": len(expired),
            "expiring_within_30d": len(expiring),
            "needing_attention": len(expired) + len(expiring),
        },
        "rows": rows,
        "note": "An expired exception stops suppressing its finding the moment it "
                "expires, so this is the last warning before a governance gate goes red "
                "for a reason nobody remembers agreeing to.",
    }


# =============================================================================
# DATABASE
# =============================================================================
def _datastore_types(ctx: Context) -> dict[str, list]:
    out = defaultdict(list)
    for aid, a in sorted(ctx.policy["archetypes"].items()):
        if oc.entity_kind(ctx.policy, a["resource_type"]) == "datastore":
            out[a["resource_type"]].append(a)
    return out


@report("db-datastore-coverage")
def _db_coverage(ctx: Context) -> dict:
    deployed = Counter(t.get("resource_type") for _, t in ctx.monitor_rows())
    estate = Counter(a["service_archetype"] for a in ctx.assignments["assignments"])

    rows = []
    for rt, arches in sorted(_datastore_types(ctx).items()):
        signals = sorted({a["signal"] for a in arches})
        rows.append({"resource_type": rt, "archetypes": len(arches),
                     "signals": signals, "deployed_monitors": deployed.get(rt, 0),
                     "has_availability": "availability" in signals,
                     "has_latency": "latency" in signals,
                     "has_capacity": bool({"capacity", "saturation"} & set(signals))})
    # Attention is "declared but not deployed", not "missing an availability
    # signal": several datastore technologies are correctly watched for freshness
    # or growth and have no availability metric to watch at all (a container
    # registry, a persistent volume claim). Counting those would keep the report
    # permanently red for a design decision.
    undeployed = [r for r in rows if r["deployed_monitors"] == 0]
    return {
        "summary": {
            "datastore_technologies": len(rows),
            "datastore_resources_in_estate": estate.get("datastore", 0),
            "technologies_without_an_availability_signal": sum(
                1 for r in rows if not r["has_availability"]),
            "technologies_with_no_deployed_monitor": len(undeployed),
            "needing_attention": len(undeployed),
        },
        "rows": rows,
    }


@report("db-durability")
def _db_durability(ctx: Context) -> dict:
    """The report an availability percentage hides.

    A datastore can be 100% available and one silent backup failure away from
    data loss. Availability answers "is it up"; nothing on any dashboard in this
    repository answered "would we see loss coming" until this report.
    """
    signals = set(ctx.policy["scorecards"]["durability_signals"])
    rows, gaps = [], 0
    for rt, arches in sorted(_datastore_types(ctx).items()):
        present = {a["signal"] for a in arches}
        detections = {a["detection"] for a in arches}
        has_forecast = "forecast" in detections
        covered = bool(present & signals) or has_forecast
        missing = sorted(signals - present)
        if not covered:
            gaps += 1
        rows.append({
            "resource_type": rt,
            "archetypes": len(arches),
            "capacity_forecast": has_forecast,
            "backup_check": "backup_age" in present,
            "replication_check": "replication_lag" in present,
            "freshness_check": "freshness" in present,
            "durability_covered": covered,
            "missing": [] if covered else missing,
        })
    return {
        "summary": {
            "datastore_technologies": len(rows),
            "without_a_durability_horizon": gaps,
            "needing_attention": gaps,
        },
        "rows": rows,
        "note": "Coverage is judged per TECHNOLOGY, not per monitor: a capacity forecast "
                "for `azure_sql` covers every Azure SQL database, and no single monitor "
                "can be blamed for a missing sibling.",
    }


@report("db-slo-attachment")
def _db_slo(ctx: Context) -> dict:
    live_status = {}
    for s in ctx.slos:
        st = oc.tags_to_map(s.get("tags") if isinstance(s.get("tags"), list) else [])
        overall = s.get("overall_status") or [{}]
        if st.get("slo_id"):
            live_status[st["slo_id"]] = overall[0] if isinstance(overall, list) and overall else {}

    rows, attention = [], 0
    for sid, s in sorted(ctx.policy["slos"].items()):
        if s["domain"] not in ("database", "data"):
            continue
        dep = s.get("telemetry_dependency")
        err = live_status.get(sid, {}).get("error")
        if dep or err:
            attention += 1
        rows.append({"slo": sid, "name": s["name"], "domain": s["domain"],
                     "team": s["team"], "target": s["target"],
                     "telemetry_dependency": dep, "live_error": err})
    return {
        "summary": {
            "database_objectives": len(rows),
            "with_a_telemetry_problem": attention,
            "needing_attention": attention,
        },
        "rows": rows,
    }


# =============================================================================
# AZURE / INFRASTRUCTURE
# =============================================================================
@report("azure-resource-coverage")
def _azure_coverage(ctx: Context) -> dict:
    deployed = Counter(t.get("resource_type") for _, t in ctx.monitor_rows())
    per_rt = defaultdict(list)
    for aid, a in sorted(ctx.policy["archetypes"].items()):
        if a["resource_type"].startswith("azure_") or a["domain"] == "cloud":
            per_rt[a["resource_type"]].append(a)

    rows = []
    for rt, arches in sorted(per_rt.items()):
        signals = sorted({a["signal"] for a in arches})
        rows.append({
            "resource_type": rt,
            "entity_kind": oc.entity_kind(ctx.policy, rt),
            "archetypes": len(arches),
            "signals": signals,
            "deployed_monitors": deployed.get(rt, 0),
            "availability": "availability" in signals,
            "saturation_or_capacity": bool({"saturation", "capacity"} & set(signals)),
        })
    thin = [r for r in rows if r["archetypes"] == 1]
    return {
        "summary": {
            "azure_resource_types": len(rows),
            "single_archetype_types": len(thin),
            "needing_attention": len(thin),
        },
        "rows": rows,
        "note": "A resource type covered by exactly one archetype is watched for one "
                "failure mode. That is a deliberate choice for some (a CDN's cache hit "
                "ratio) and an oversight for others; the list is the review queue, not "
                "a defect list.",
    }


@report("azure-cost-and-quota")
def _azure_cost(ctx: Context) -> dict:
    """What will run out, and how long do we have?

    Every row is a forecast, so every row has a lead time. That is the whole
    point: a saturation alert tells you the wall is here, a forecast tells you
    when you will hit it, and only the second one can be scheduled.
    """
    rows = []
    for aid, a in sorted(ctx.policy["archetypes"].items()):
        exhaustion = a["signal"] in ("cost", "capacity", "saturation", "throughput")
        if not exhaustion or a["domain"] not in ("cloud", "infrastructure", "network",
                                                 "kubernetes", "vmware"):
            continue
        window = a.get("evaluation_window", "")
        rows.append({
            "archetype": aid, "domain": a["domain"], "signal": a["signal"],
            "resource_type": a["resource_type"], "detection": a["detection"],
            "forecast": a["detection"] == "forecast",
            "lead_time": window if window.startswith("next_") else None,
            "evaluation_window": window,
        })
    forecasts = [r for r in rows if r["forecast"]]
    reactive = [r for r in rows if not r["forecast"]]
    # Attention is per RESOURCE TYPE, not per archetype. A throttling alert with
    # no forecast is fine as long as SOMETHING forecasts that resource running
    # down; counting every reactive archetype would flag two thirds of a
    # correctly-designed catalog, and a report that flags everything is ignored.
    forecast_types = {r["resource_type"] for r in forecasts}
    blind = sorted({r["resource_type"] for r in rows} - forecast_types)
    return {
        "summary": {
            "exhaustion_signals": len(rows),
            "with_a_forecast": len(forecasts),
            "reactive_only": len(reactive),
            "resource_types_with_no_forecast_at_all": len(blind),
            "needing_attention": len(blind),
        },
        "resource_types_with_no_forecast_at_all": blind,
        "rows": sorted(rows, key=lambda r: (r["forecast"], r["domain"], r["archetype"])),
        "note": "A reactive-only row is not automatically wrong — a throttling event has "
                "no useful forecast. It is a question: for this resource, is there a "
                "quantity that runs down, and are we watching it run down?",
    }


@report("infra-fleet-health")
def _infra_fleet(ctx: Context) -> dict:
    card = ctx.policy["global"]["cardinality"]
    rows, attention = [], 0
    for aid, a in sorted(ctx.policy["archetypes"].items()):
        if oc.entity_kind(ctx.policy, a["resource_type"]) != "infrastructure":
            continue
        gb = a.get("group_by") or []
        nb = a.get("notify_by") or []
        problems = []
        if len(gb) >= 2 and not nb:
            problems.append("no collapse key on a multi-key fleet monitor")
        if len(gb) > card["max_group_by_keys"]:
            problems.append(f"{len(gb)} group keys (max {card['max_group_by_keys']})")
        if set(gb) & set(card["forbidden_group_keys"]):
            problems.append("identity key in group_by — unbounded cardinality")
        if problems:
            attention += 1
        rows.append({"archetype": aid, "domain": a["domain"],
                     "resource_type": a["resource_type"],
                     "group_by": gb, "notify_by": nb, "problems": problems})
    estate = sum(1 for a in ctx.assignments["assignments"]
                 if oc.entity_kind_of_service_archetype(
                     ctx.policy, a["service_archetype"]) == "infrastructure")
    return {
        "summary": {
            "infrastructure_archetypes": len(rows),
            "infrastructure_resources_in_estate": estate,
            "with_a_grouping_problem": attention,
            "needing_attention": attention,
        },
        "rows": [r for r in rows if r["problems"]] or rows[:15],
        "note": "One infrastructure monitor covers thousands of hosts. Without a collapse "
                "key it produces thousands of notifications, which is operationally the "
                "same as producing none.",
    }


# =============================================================================
# LIVE DATA
# =============================================================================
def fetch_live():
    """Monitors, SLOs, and the runtime facts no static analysis can produce.

    The alert-volume and transition queries aggregate `by {monitor_id}`, which is
    this platform's OWN stable monitor identifier (stamped by the monitor
    factory), not Datadog's numeric id. That is deliberate: the numeric id is
    recreated whenever a monitor is replaced, so a history keyed on it silently
    resets every time the estate is re-applied.
    """
    headers = oc.dd_headers()
    site = oc.dd_site()
    monitors, slos = cr.fetch_live()

    state_modified = {}
    nodata_by_service = defaultdict(lambda: [0, 0])
    for m in monitors:
        ts = m.get("overall_state_modified")
        if ts:
            try:
                state_modified[m["id"]] = dt.datetime.fromisoformat(
                    str(ts).replace("Z", "+00:00"))
            except ValueError:
                pass
        t = oc.tags_to_map(m.get("tags"))
        if t.get("service"):
            counts = nodata_by_service[t["service"]]
            counts[0] += 1
            if (m.get("overall_state") or "").lower() == "no data":
                counts[1] += 1

    now = int(oc.utcnow().timestamp())

    def _series(query: str, frm: int):
        r = oc.dd_request("GET", f"{site}/api/v1/query", headers=headers,
                          params={"from": frm, "to": now, "query": query})
        r.raise_for_status()
        return r.json().get("series") or []

    def _by_monitor(series, reduce_fn):
        out: dict[str, float] = {}
        for s in series:
            mid = oc.tags_to_map(s.get("tag_set") or []).get("monitor_id")
            if not mid:
                continue
            points = [p[1] for p in (s.get("pointlist") or []) if p[1] is not None]
            if points:
                out[mid] = reduce_fn(points)
        return out

    q = "sum:datadog.monitor.alert_count{managed_by:terraform} by {monitor_id}.as_count()"
    alerts_30d = _by_monitor(_series(q, now - 30 * 86400), sum)
    # One point per hour over 24h: the maximum is the worst hour, which is what
    # "flapping" means to the person being paged.
    max_hourly = _by_monitor(_series(q, now - 86400), max)

    return monitors, slos, {
        "state_modified": state_modified,
        "alerts_30d": {k: int(v) for k, v in alerts_30d.items()},
        "max_hourly_24h": {k: int(v) for k, v in max_hourly.items()},
        "nodata_services": {svc for svc, (total, nodata) in nodata_by_service.items()
                            if total and total == nodata},
        "pages_per_team_week": {},
    }


# =============================================================================
# RUN & RENDER
# =============================================================================
def run(ctx: Context, ids: list[str] | None = None) -> dict:
    catalog = ctx.policy["reports"]
    ids = ids or sorted(catalog)
    out = []
    for rid in ids:
        spec = catalog[rid]
        body = REPORTS[rid](ctx)
        evidence = "live" if ctx.live else "structural"
        out.append({
            "id": rid,
            "family": spec["family"],
            "audience": spec["audience"],
            "question": spec["question"].strip(),
            "cadence": spec["cadence"],
            "action": " ".join(spec["action"].split()),
            "requires_live": spec["requires_live"],
            # A report that needed the running estate and did not get it says so
            # in its own output. Nobody should have to remember which mode the
            # run used to know how much to trust the number.
            "evidence": evidence,
            "degraded": bool(spec["requires_live"]) and not ctx.live,
            **body,
        })
    return {
        "generated_at": oc.utcnow().isoformat(),
        "mode": "live" if ctx.live else "offline",
        "summary": {
            "reports": len(out),
            "families": len({r["family"] for r in out}),
            "needing_attention": sum(r["summary"].get("needing_attention", 0) for r in out),
            "degraded": sum(1 for r in out if r["degraded"]),
        },
        "reports": out,
    }


def to_markdown(result: dict, policy: dict) -> str:
    fam_doc = policy["reports_doc"]["families"]
    by_family = defaultdict(list)
    for r in result["reports"]:
        by_family[r["family"]].append(r)

    lines = [
        "# Observability Report Catalog",
        "",
        f"Mode: **{result['mode']}** · {result['summary']['reports']} reports across "
        f"{result['summary']['families']} families · "
        f"{result['summary']['needing_attention']} items needing attention",
        "",
    ]
    if result["summary"]["degraded"]:
        lines += [
            f"> {result['summary']['degraded']} report(s) needed the live estate and ran "
            "offline. Those answer the structural half of their question and are marked "
            "`structural` below — they are not the full answer and do not claim to be.",
            "",
        ]

    for fam in ("executive", "operations", "platform", "database", "azure"):
        reports = by_family.get(fam)
        if not reports:
            continue
        doc = fam_doc[fam]
        lines += [f"## {doc['display']}", "",
                  f"*{doc['audience']} · {doc['cadence']}*", "",
                  " ".join(doc["framing"].split()), ""]
        for r in reports:
            mark = " ⚠️" if r["summary"].get("needing_attention") else ""
            lines += [f"### {r['id']}{mark}", "",
                      f"**{r['question']}**", "",
                      f"- evidence: `{r['evidence']}`"
                      + ("  ← degraded: this report wants the live estate"
                         if r["degraded"] else ""),
                      "- " + " · ".join(f"{k}: **{v}**" for k, v in r["summary"].items()),
                      f"- action: {r['action']}",
                      ""]
            rows = r.get("rows") or []
            if rows:
                cols = [c for c in rows[0] if c != "mix"]
                lines += ["| " + " | ".join(cols) + " |",
                          "|" + "---|" * len(cols)]
                for row in rows[:15]:
                    lines.append("| " + " | ".join(
                        _cell(row.get(c)) for c in cols) + " |")
                if len(rows) > 15:
                    lines.append(f"")
                    lines.append(f"_{len(rows) - 15} more rows in the JSON artifact._")
                lines.append("")
            if r.get("note"):
                lines += ["> " + " ".join(r["note"].split()), ""]
    return "\n".join(lines) + "\n"


def _cell(v) -> str:
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, (list, tuple)):
        return ", ".join(str(x) for x in v) if v else "—"
    if isinstance(v, dict):
        return json.dumps(v)
    return str(v).replace("|", "\\|")


def _estate(policy, inventory_path: Path, assignments_path: Path, synthetic: int):
    """The resource denominator, from generated/ when it exists.

    Falling back to the deterministic synthetic estate is what lets the whole
    catalog run on a pull request with no credentials and no prior inventory
    build. It is labelled in the output so nobody mistakes a synthetic
    denominator for a measured one.
    """
    if inventory_path.exists() and assignments_path.exists():
        return (json.loads(inventory_path.read_text()),
                json.loads(assignments_path.read_text()), "generated")
    resources = build_inventory.synthesize(synthetic)
    inv = {"resources": resources, "resource_count": len(resources)}
    return inv, profile_engine.assign(inv, policy, oc.load_services()), "synthetic"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--live", action="store_true")
    mode.add_argument("--fixtures", type=Path)
    ap.add_argument("--family", choices=["executive", "operations", "platform",
                                         "database", "azure"],
                    help="Produce one family only.")
    ap.add_argument("--report", action="append",
                    help="Produce specific report ids (repeatable).")
    ap.add_argument("--inventory", type=Path, default=oc.GENERATED_DIR / "inventory.json")
    ap.add_argument("--assignments", type=Path, default=oc.GENERATED_DIR / "assignments.json")
    ap.add_argument("--synthetic", type=int, default=2000,
                    help="Resource count for the fallback estate when generated/ is empty.")
    ap.add_argument("--out-json", type=Path, default=oc.GENERATED_DIR / "reports.json")
    ap.add_argument("--out-md", type=Path, default=oc.GENERATED_DIR / "reports.md")
    ap.add_argument("--fail-on-attention", action="store_true",
                    help="Exit non-zero when anything needs attention. OFF by default: "
                         "these reports are a review queue for humans, not a gate. The "
                         "gates are coverage_report.py and monitor_scorecard.py, and "
                         "adding a third one that fires on a backlog would only teach "
                         "people to ignore all three.")
    args = ap.parse_args()

    policy = oc.load_policy()
    if args.live:
        monitors, slos, runtime = fetch_live()
    else:
        monitors = json.loads((args.fixtures / "monitors_planned.json").read_text())
        slos = json.loads((args.fixtures / "slos.json").read_text())
        runtime = {}

    inventory, assignments, denominator = _estate(
        policy, args.inventory, args.assignments, args.synthetic)
    ctx = Context(policy, monitors, slos, inventory, assignments,
                  live=args.live, runtime=runtime)

    ids = args.report
    if not ids and args.family:
        ids = sorted(r for r, s in policy["reports"].items()
                     if s["family"] == args.family)
    unknown = sorted(set(ids or []) - set(policy["reports"]))
    if unknown:
        raise SystemExit(f"not in the report catalog: {', '.join(unknown)}")

    result = run(ctx, ids)
    result["denominator"] = denominator
    oc.write_json(args.out_json, result)
    args.out_md.parent.mkdir(parents=True, exist_ok=True)
    args.out_md.write_text(to_markdown(result, policy))

    print(json.dumps(result["summary"], indent=2))
    for r in result["reports"]:
        n = r["summary"].get("needing_attention", 0)
        print(f"  {'!' if n else ' '} {r['id']:32s} {r['evidence']:10s} attention={n}")
    if args.fail_on_attention and result["summary"]["needing_attention"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
