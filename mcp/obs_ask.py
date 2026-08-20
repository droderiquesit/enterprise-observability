"""ASK MODE (§43) — grounded answers, or an honest refusal.

Thirty questions. Every one returns an `Answer` that cites the object ids,
counts and source it was computed from (see mcp/obs_evidence.py), and the
envelope refuses to serialize an answerable result with no citation.

THE RULE THAT SHAPED THIS FILE: where the data to answer a question does not
exist in this org, the answer says so and names the gap, with a pointer into
docs/requirement-traceability.md. It never estimates. The three that are wholly
or partly unanswerable today are marked `availability` below and listed in
mcp/README.md; the reasons are real findings from the traceability audit, not
placeholders:

  who_is_on_call        §28 — every on-call schedule position is UNASSIGNED, so
                        no schedule resolves to a person. The escalation
                        STRUCTURE is returned; a name is not invented.
  what_changed          §8  — no pipeline sets DD_VERSION / DD_GIT_COMMIT_SHA,
                        so deployment metadata does not reach Datadog. Change
                        correlation works; its input is largely empty.
  missing_integrations  §38 — archetypes declare no `telemetry:` requirement,
                        so "required integrations" has to be INFERRED from the
                        metric namespaces the queries reference. Disclosed as
                        an inference on every answer.
  broken_agents         §36/§39 — agent health is observable; fleet COMPLIANCE
                        percentage is not, because nothing declares which hosts
                        are required to run an agent.

Answers are computed from the platform's own engines (see mcp/obs_state.py), so
an Ask answer and a `make validate` run cannot disagree.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import re
from typing import Callable

import obs_state                             # puts tools/ on sys.path — import first
import obs_common as oc                      # noqa: E402  (the platform's own resolvers)
from obs_evidence import Answer

TRACEABILITY = "docs/requirement-traceability.md"
POLICY = "platform/policy"

# availability vocabulary, reported by obs.list_questions:
#   state    answerable from the repository alone (policy + plan-derived estate)
#   runtime  needs the runtime snapshot (fixtures) or the Datadog API (live)
#   partial  answerable, but a named part of it is not — see the caveats
#   blocked  cannot be answered in this org today; the answer says why
AVAILABILITY = ("state", "runtime", "partial", "blocked")


@dataclasses.dataclass
class QuestionSpec:
    id: str
    title: str
    availability: str
    handler: Callable
    params: dict = dataclasses.field(default_factory=dict)
    patterns: tuple = ()
    note: str = ""

    def to_dict(self) -> dict:
        return {"id": self.id, "title": self.title, "availability": self.availability,
                "params": self.params, "note": self.note,
                "example_phrasings": list(self.patterns)}


QUESTIONS: dict[str, QuestionSpec] = {}


def question(qid, title, availability, params=None, patterns=(), note=""):
    def deco(fn):
        QUESTIONS[qid] = QuestionSpec(qid, title, availability, fn,
                                      params or {}, tuple(patterns), note)
        return fn
    return deco


def _new(state: obs_state.PlatformState, qid: str) -> Answer:
    a = Answer(question=qid, mode=state.mode)
    a.as_of = (state.runtime.get("captured_at") if state.mode == "fixtures"
               else state.loaded_at)
    return a


# ---------------------------------------------------------------------------
# shared derivations
# ---------------------------------------------------------------------------
METRIC_RE = re.compile(r"\b([a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+)\s*\{")


def _states(state) -> dict:
    return state.runtime.get("monitor_states") or {}


def _firing(state, statuses=("Alert",)) -> list[tuple[dict, dict, dict]]:
    """(monitor, tags, runtime-state) for everything in one of `statuses`."""
    out = []
    for m in state.managed_monitors:
        st = _states(state).get(str(m["id"]))
        if st and st.get("overall_state") in statuses:
            out.append((m, state.monitor_tags(m), st))
    return sorted(out, key=lambda r: (r[1].get("priority", "p9"), r[0].get("name", "")))


def _groups(state) -> list[dict]:
    events = state.runtime.get("events") or []
    return state.correlate([dict(e) for e in events]) if events else []


def _metrics_in(query: str | None) -> list[str]:
    return sorted(set(METRIC_RE.findall(query or "")))


def _service_record(state, service: str) -> dict | None:
    return state.services.get(service)


# ===========================================================================
# 1–9 · what is happening
# ===========================================================================
@question("unhealthy_now", "What is unhealthy right now?", "runtime",
          params={"include_warn": "bool, default true",
                  "env": "optional environment filter"},
          patterns=["what is unhealthy", "what is broken", "what is firing",
                    "what is alerting now", "current alerts"])
def q_unhealthy_now(state, p):
    a = _new(state, "unhealthy_now")
    statuses = ("Alert", "No Data") if p.get("include_warn") is False else \
        ("Alert", "Warn", "No Data")
    rows = [(m, t, st) for m, t, st in _firing(state, statuses)
            if not p.get("env") or t.get("env") == p["env"]]
    by_state: dict[str, list] = {}
    for m, t, st in rows:
        by_state.setdefault(st["overall_state"], []).append(str(m["id"]))
    a.data = {
        "counts": {k: len(v) for k, v in sorted(by_state.items())},
        "monitors": [{
            "id": m["id"], "name": m.get("name"), "state": st["overall_state"],
            "priority": (t.get("priority") or "").upper(), "env": t.get("env"),
            "team": t.get("team"), "service": t.get("service"),
            "archetype": t.get("archetype"), "pages": t.get("pages") == "true",
            "groups": sorted(st.get("groups") or {}),
            "runbook": t.get("runbook"), "runbook_notebook": t.get("runbook_notebook"),
        } for m, t, st in rows],
    }
    a.summary = (f"{len(rows)} monitors are not OK "
                 f"({', '.join(f'{len(v)} {k}' for k, v in sorted(by_state.items())) or 'none'})"
                 f", out of {len(state.managed_monitors)} Terraform-managed monitors.")
    a.cite(state.runtime_source, "monitor_state", [m["id"] for m, _, _ in rows],
           note="monitor overall_state at the snapshot instant")
    a.cite(state.monitor_source, "monitor", count=len(state.managed_monitors),
           note="the managed estate this is measured against")
    return a


@question("why_unhealthy", "Why is this monitor / service unhealthy?", "partial",
          params={"monitor_id": "monitor id", "service": "service tag value"},
          patterns=["why is", "why did this fire", "why unhealthy", "what does this alert mean"],
          note="Reports WHAT the monitor detects and what else fired with it. A causal "
               "claim beyond the correlation ranking is not made.")
def q_why_unhealthy(state, p):
    a = _new(state, "why_unhealthy")
    mid, svc = p.get("monitor_id"), p.get("service")
    if not mid and not svc:
        return a.unanswerable("pass monitor_id or service")

    targets = []
    for m, t, st in _firing(state, ("Alert", "Warn", "No Data")):
        if (mid and str(m["id"]) == str(mid)) or (svc and t.get("service") == svc):
            targets.append((m, t, st))
    if mid and not targets and str(mid) in state.monitors_by_id:
        m = state.monitors_by_id[str(mid)]
        t = state.monitor_tags(m)
        st = _states(state).get(str(mid), {"overall_state": "OK"})
        a.data = {"monitor": m.get("name"), "state": st.get("overall_state")}
        a.summary = f"monitor {mid} is {st.get('overall_state')} — it is not unhealthy."
        a.cite(state.runtime_source, "monitor_state", [mid])
        return a
    if not targets:
        return a.unanswerable(
            f"no unhealthy monitor matches {'monitor_id=' + str(mid) if mid else 'service=' + str(svc)}")

    groups = _groups(state)
    explanations = []
    for m, t, st in targets:
        arch = state.policy["archetypes"].get(t.get("archetype", ""), {})
        group = next((g for g in groups
                      if g["parent"].get("correlation_key") == t.get("correlation_key")), None)
        explanations.append({
            "monitor_id": m["id"], "name": m.get("name"),
            "state": st["overall_state"],
            "detects": arch.get("title") or t.get("archetype"),
            "signal": t.get("signal"), "detection": t.get("detection"),
            "impact_class": t.get("impact_class"),
            "query": m.get("query"),
            "evaluation_window": arch.get("evaluation_window"),
            "threshold_rationale": (arch.get("rationale_fixed_threshold") or "").strip() or None,
            "affected_groups": sorted(st.get("groups") or {}),
            "priority": (t.get("priority") or "").upper(),
            "pages": t.get("pages") == "true",
            "route": state.route_for(t.get("notification_profile", ""),
                                     t.get("priority", "p3"), t.get("pages") == "true"),
            "runbook": t.get("runbook"),
            "runbook_notebook": t.get("runbook_notebook"),
            "correlation_key": t.get("correlation_key"),
            "correlated_with": [c.get("title") for c in (group or {}).get("children", [])],
            "change_context": [c.get("title") for c in (group or {}).get("context", [])],
        })
    a.data = {"explanations": explanations}
    a.summary = (f"{len(explanations)} unhealthy monitor(s); each is explained by the "
                 "archetype it was generated from, its correlation group, and its route.")
    a.cite(state.runtime_source, "monitor_state", [e["monitor_id"] for e in explanations])
    a.cite(f"{POLICY}/archetypes/", "archetype",
           sorted({t.get("archetype") for _, t, _ in targets if t.get("archetype")}),
           note="the definition that decided what this monitor detects")
    a.cite("platform/events/correlation-rules.yaml", "correlation_rule",
           count=len(groups), note="correlation groups evaluated by tools/correlate_events.py")
    a.caveat("`correlated_with` is a RANKING from the correlation rules, not a proven cause.")
    return a


@question("what_changed", "What changed recently?", "partial",
          params={"window_hours": "int, default 6"},
          patterns=["what changed", "recent deploys", "any deployments", "what was deployed"],
          note="§8 of the traceability audit: no pipeline sets DD_VERSION / "
               "DD_GIT_COMMIT_SHA, so deployment metadata largely does not reach Datadog.")
def q_what_changed(state, p):
    a = _new(state, "what_changed")
    window = int(p.get("window_hours") or 6) * 3600
    now = state.runtime.get("captured_ts") or int(dt.datetime.now(dt.timezone.utc).timestamp())
    changes = [e for e in (state.runtime.get("events") or [])
               if e.get("kind") == "change" and (now - (e.get("ts") or 0)) <= window]
    a.data = {"window_hours": window // 3600,
              "changes": [{"id": e.get("id"), "title": e.get("title"),
                           "service": e.get("service"), "env": e.get("env"),
                           "ts": e.get("ts"), "source": e.get("source", "datadog_event")}
                          for e in changes]}
    a.cite(state.runtime_source, "event", [e.get("id") for e in changes],
           note=f"change-class events in the last {window // 3600}h")
    a.caveat(
        f"{TRACEABILITY} §8 records DEPLOYMENT METADATA AS MISSING in this org: no "
        "pipeline sets DD_VERSION or DD_GIT_COMMIT_SHA. Absence of a change event here "
        "is NOT evidence that nothing was deployed.")
    if not changes:
        a.summary = ("No change events in the window. Given the §8 gap this is weak "
                     "evidence — treat it as 'not visible', not as 'nothing changed'.")
    else:
        a.summary = f"{len(changes)} change event(s) in the last {window // 3600}h."
    return a


@question("affected_entities", "Which services and systems are affected?", "runtime",
          patterns=["who is affected", "which services are affected", "blast radius",
                    "what is impacted"])
def q_affected(state, p):
    a = _new(state, "affected_entities")
    rows = _firing(state, ("Alert", "Warn", "No Data"))
    services, teams, domains, groups_hit = {}, set(), set(), []
    for m, t, st in rows:
        svc = t.get("service") or "(unattributed)"
        entry = services.setdefault(svc, {"service": svc, "team": t.get("team"),
                                          "domain": t.get("domain"), "monitors": [],
                                          "groups": []})
        entry["monitors"].append(m["id"])
        entry["groups"].extend(sorted(st.get("groups") or {}))
        teams.add(t.get("team"))
        domains.add(t.get("domain"))
        groups_hit.extend(sorted(st.get("groups") or {}))
    a.data = {"services": sorted(services.values(), key=lambda s: -len(s["monitors"])),
              "teams": sorted(t for t in teams if t),
              "domains": sorted(d for d in domains if d),
              "distinct_alerting_groups": len(set(groups_hit))}
    a.summary = (f"{len(services)} service tag(s) across {len(a.data['teams'])} team(s) and "
                 f"{len(a.data['domains'])} domain(s); {a.data['distinct_alerting_groups']} "
                 "distinct monitor groups are in a non-OK state.")
    a.cite(state.runtime_source, "monitor_state", [m["id"] for m, _, _ in rows])
    a.cite(state.monitor_source, "monitor_tag", sorted(services),
           note="`service` tag on each firing monitor; a grouped monitor's GROUPS name "
                "the individual resources")
    a.caveat("Monitors are grouped by tag, so `service` here is the monitor's scope tag "
             "(often a platform-level service such as `api-services`); the group keys are "
             "the individual resources.")
    return a


@question("probable_root_cause", "What is the probable root cause?", "partial",
          patterns=["root cause", "what caused", "probable cause", "why did this happen"],
          note="Ranking from platform/events/correlation-rules.yaml, not a causal proof.")
def q_root_cause(state, p):
    a = _new(state, "probable_root_cause")
    groups = _groups(state)
    if not groups:
        return a.unanswerable("no alert events in the snapshot, so nothing to correlate")
    ranked = sorted(groups, key=lambda g: (g["priority"], -g["suppressed"]))
    a.data = {"candidates": [{
        "correlation_key": g["correlation_key"],
        "parent": g["parent"].get("title"),
        "parent_monitor_id": g["parent"].get("monitor_id"),
        "parent_signal": g["parent"].get("signal"),
        "priority": g["priority"],
        "symptoms_absorbed": g["suppressed"],
        "children": [c.get("title") for c in g["children"]],
        "change_context": [c.get("title") for c in g["context"]],
        "creates_incident": g["creates_incident"], "pages": g["pages"],
    } for g in ranked]}
    top = ranked[0]
    a.summary = (f"{len(groups)} correlation group(s). Highest-ranked cause: "
                 f"{top['parent'].get('title')} ({top['priority']}), absorbing "
                 f"{top['suppressed']} symptom(s).")
    a.cite("platform/events/correlation-rules.yaml", "correlation_rule",
           [g["correlation_key"] for g in ranked],
           note="root_cause_ranking + topology rules, executed by tools/correlate_events.py")
    a.cite(state.runtime_source, "event",
           [g["parent"].get("id") for g in ranked if g["parent"].get("id")])
    a.caveat("The parent is chosen by SIGNAL RANK then priority then time. That is a "
             "prioritized hypothesis; confirm it against the runbook before acting.")
    return a


@question("correlated_signals", "What signals are correlated with this one?", "runtime",
          params={"correlation_key": "optional; defaults to every group"},
          patterns=["correlated", "related alerts", "what else is firing",
                    "grouped alerts"])
def q_correlated(state, p):
    a = _new(state, "correlated_signals")
    groups = _groups(state)
    key = p.get("correlation_key")
    if key:
        groups = [g for g in groups if g["correlation_key"] == key]
        if not groups:
            return a.unanswerable(f"no correlation group for key {key!r} in the snapshot")
    a.data = {"groups": [{
        "correlation_key": g["correlation_key"], "priority": g["priority"],
        "parent": g["parent"].get("title"),
        "members": [g["parent"].get("title")] + [c.get("title") for c in g["children"]],
        "context": [c.get("title") for c in g["context"]],
        "suppressed": g["suppressed"], "pages": g["pages"],
    } for g in groups]}
    a.summary = (f"{len(groups)} group(s); "
                 f"{sum(g['suppressed'] for g in groups)} alerts suppressed into a parent "
                 "instead of paging separately.")
    a.cite("platform/events/correlation-rules.yaml", "correlation_rule",
           [g["correlation_key"] for g in groups])
    a.cite(state.runtime_source, "event",
           count=len(state.runtime.get("events") or []))
    return a


@question("active_incidents", "What incidents are active?", "runtime",
          patterns=["active incidents", "open incidents", "any incidents", "current incidents"])
def q_incidents(state, p):
    a = _new(state, "active_incidents")
    incidents = state.runtime.get("incidents")
    if incidents is None:
        return a.unanswerable("the incidents surface was not readable in this mode")
    active = [i for i in incidents if not i.get("resolved")]
    a.data = {"active": active, "total_in_window": len(incidents)}
    a.summary = (f"{len(active)} active incident(s) of {len(incidents)} in the snapshot "
                 "window.")
    a.cite(state.runtime_source if state.mode == "fixtures" else "datadog:/api/v2/incidents",
           "incident", [i["id"] for i in incidents])
    a.caveat(f"{TRACEABILITY} §27: incident MANAGEMENT is only partly implemented — "
             "severity→incident intent is declared in notification_profiles.yaml but no "
             "incident-command role model or PIR automation exists, so incident records "
             "may be thinner than the alerting picture.")
    return a


@question("who_is_on_call", "Who is on call?", "blocked",
          params={"team": "optional team handle"},
          patterns=["who is on call", "on-call", "who do I page", "who gets paged"],
          note="BLOCKED: every on-call schedule position in this org is unassigned (§28).")
def q_oncall(state, p):
    a = _new(state, "who_is_on_call")
    teams = state.policy["teams"]
    handle = p.get("team")
    if handle and handle not in teams:
        return a.unanswerable(f"team {handle!r} is not registered in {POLICY}/teams.yaml")
    selected = {handle: teams[handle]} if handle else teams
    roster = state.runtime.get("oncall") or {}

    structure = []
    for h, t in sorted(selected.items()):
        structure.append({
            "team": h, "name": t.get("name"), "email": t.get("email"),
            "escalates_to": t.get("escalation_to"),
            "teams_channel": t.get("teams_channel"),
            "servicenow_assignment_group": t.get("servicenow_assignment_group"),
            "oncall_configured": bool(t.get("oncall")),
            "primary_schedule": f"{h} — primary", "secondary_schedule": f"{h} — secondary",
            "escalation_chain": ["primary_oncall", "secondary_oncall", "team_lead",
                                 "incident_commander"],
            "current_responder": roster.get(h) or None,
        })
    a.data = {"escalation_structure": structure,
              "rosters_populated": bool(roster)}
    a.cite(f"{POLICY}/teams.yaml", "team", sorted(selected))
    a.cite("modules/team_oncall/main.tf", "escalation_policy", count=len(selected),
           note="schedules and the four-step policy are created; positions are unassigned")
    if roster:
        a.summary = "Rosters are populated; current responders are listed."
        return a
    return a.unanswerable(
        f"No person can be named. {TRACEABILITY} §28 records that the on-call ROSTERS "
        "are empty — every schedule position in the org is unassigned, so a page reaches "
        "nobody. The escalation structure returned above is real and deployed; the people "
        "in it are not. Remediation: populate `oncall_members` / "
        "`oncall_secondary_members` from the IdP/SCIM sync.")


@question("mttr", "What is our MTTR?", "partial",
          patterns=["mttr", "mean time to restore", "how long do incidents take",
                    "time to recover"],
          note="Computed from Datadog incident records only.")
def q_mttr(state, p):
    a = _new(state, "mttr")
    incidents = state.runtime.get("incidents") or []
    resolved = [i for i in incidents if i.get("resolved") and i.get("created")]
    if not resolved:
        a.cite(state.runtime_source, "incident", [i["id"] for i in incidents])
        return a.unanswerable(
            "no incident in the window has both a created and a resolved timestamp")
    durations = [(i["resolved"] - i["created"]) for i in resolved]
    by_sev: dict[str, list] = {}
    for i in resolved:
        by_sev.setdefault(i.get("severity", "unknown"), []).append(i["resolved"] - i["created"])
    a.data = {
        "sample_size": len(resolved),
        "open_excluded": len(incidents) - len(resolved),
        "mttr_minutes": round(sum(durations) / len(durations) / 60, 1),
        "p50_minutes": round(sorted(durations)[len(durations) // 2] / 60, 1),
        "by_severity": {k: round(sum(v) / len(v) / 60, 1) for k, v in sorted(by_sev.items())},
        "incidents": [{"id": i["id"], "severity": i.get("severity"),
                       "minutes": round((i["resolved"] - i["created"]) / 60, 1)}
                      for i in resolved],
    }
    a.summary = (f"MTTR {a.data['mttr_minutes']} minutes across {len(resolved)} resolved "
                 f"incident(s); {a.data['open_excluded']} still open and excluded.")
    a.cite(state.runtime_source if state.mode == "fixtures" else "datadog:/api/v2/incidents",
           "incident", [i["id"] for i in resolved])
    a.caveat("Datadog incidents only. Per notification_profiles.yaml a P3 raises a "
             "ServiceNow TASK and no Datadog incident, so lower-severity restore times "
             "are in ServiceNow and are not counted here.")
    a.caveat("Small sample: this is a measured mean, not a stable trend.")
    return a


# ===========================================================================
# 10–14 · SLOs
# ===========================================================================
def _budget_pct(status: dict) -> float | None:
    """Percent of error budget remaining, normalized across two shapes.

    The offline snapshot writes `error_budget_remaining_pct` directly. Datadog's
    own `/api/v1/slo` returns `error_budget_remaining` as a MAP keyed by
    timeframe (`{"30d": 42.1}`), and `raw_error_budget_remaining` as an object.
    Reading only the first shape would silently report every live SLO as
    healthy, which is the worst possible failure for this particular question —
    so an unreadable status returns None and is counted separately rather than
    defaulting to "fine".
    """
    if status.get("error_budget_remaining_pct") is not None:
        return float(status["error_budget_remaining_pct"])
    rem = status.get("error_budget_remaining")
    if isinstance(rem, dict) and rem:
        return float(sorted(rem.items())[0][1])
    if isinstance(rem, (int, float)):
        return float(rem)
    return None


def _slo_rows(state) -> list[dict]:
    rows = []
    catalog = state.policy["slos"]
    for s in state.slos:
        tags = {}
        for t in s.get("tags") or []:
            if ":" in t:
                k, v = t.split(":", 1)
                tags.setdefault(k, v)
        status = (s.get("overall_status") or [{}])[0] or {}
        sid = tags.get("slo_id")
        rows.append({
            "datadog_id": s.get("id"), "slo_id": sid, "name": s.get("name"),
            "team": tags.get("team"), "service": tags.get("service"),
            "domain": tags.get("domain"), "scope": tags.get("scope"),
            "target": (catalog.get(sid) or {}).get("target"),
            "status": status,
            "budget_pct": _budget_pct(status),
            "burn_rate_1h": status.get("burn_rate_1h"),
        })
    return rows


@question("slos_burning", "Which SLOs are burning error budget?", "runtime",
          patterns=["slos burning", "error budget", "which slos are at risk",
                    "budget burn"])
def q_slos_burning(state, p):
    a = _new(state, "slos_burning")
    rows = _slo_rows(state)
    readable = [r for r in rows if r["budget_pct"] is not None]
    if not readable:
        a.cite(state.slo_source, "slo", [r["datadog_id"] for r in rows])
        return a.unanswerable(
            "no SLO in this mode carries a readable error budget; a Terraform plan has no "
            "runtime status. Run in live mode, or regenerate the runtime snapshot.")
    burning = sorted((r for r in readable if r["budget_pct"] < 25),
                     key=lambda r: r["budget_pct"])
    a.data = {"burning": [{
        "slo_id": r["slo_id"], "name": r["name"], "team": r["team"],
        "budget_remaining_pct": r["budget_pct"],
        "burn_rate_1h": r["burn_rate_1h"],
        "sli": r["status"].get("sli_value"), "target": r["target"],
        "state": r["status"].get("state"),
    } for r in burning], "evaluated": len(readable),
        "status_unreadable": len(rows) - len(readable)}
    a.summary = (f"{len(burning)} of {len(readable)} SLOs have less than 25% of their "
                 "error budget left.")
    if len(rows) != len(readable):
        a.caveat(f"{len(rows) - len(readable)} SLO(s) returned no readable error budget "
                 "and are EXCLUDED, not counted as healthy.")
    a.cite(state.slo_source, "slo", [r["datadog_id"] for r in burning],
           count=len(burning))
    a.cite(f"{POLICY}/slos.yaml", "slo_definition",
           [r["slo_id"] for r in burning if r["slo_id"]],
           note="targets and burn windows come from the catalog, not from Datadog")
    a.cite(f"{POLICY}/global.yaml", "policy_rule", ["burn_rate_windows"],
           note="fast 14.4× / medium 6× / slow 3× — the factors the burn monitors use")
    return a


@question("slo_breach_first", "Which SLO will breach first?", "partial",
          patterns=["breach first", "which slo will breach", "time to exhaustion",
                    "budget runway"],
          note="Linear extrapolation of the current burn rate; not a Datadog forecast.")
def q_slo_breach_first(state, p):
    a = _new(state, "slo_breach_first")
    rows = [r for r in _slo_rows(state) if r["budget_pct"] is not None]
    if not rows:
        a.cite(state.slo_source, "slo", count=len(state.slos))
        return a.unanswerable("no SLO carries a readable error budget in this mode")
    projected = []
    for r in rows:
        remaining = r["budget_pct"]
        burn = r["burn_rate_1h"] or 0
        if remaining <= 0:
            hours = 0.0
        elif burn <= 1.0:
            hours = None                        # not burning: no projected breach
        else:
            # 30d window = 720h of budget consumed at 1×; at burn×, the remaining
            # fraction lasts remaining% × 720h / burn.
            hours = round((remaining / 100.0) * 720.0 / burn, 1)
        projected.append({"slo_id": r["slo_id"], "name": r["name"], "team": r["team"],
                          "budget_remaining_pct": remaining, "burn_rate_1h": burn,
                          "hours_to_exhaustion": hours})
    at_risk = sorted([q for q in projected if q["hours_to_exhaustion"] is not None],
                     key=lambda q: q["hours_to_exhaustion"])
    a.data = {"ranked": at_risk, "not_burning": len(projected) - len(at_risk)}
    a.summary = (f"{at_risk[0]['name']} exhausts first (~{at_risk[0]['hours_to_exhaustion']}h "
                 f"at the current burn rate)." if at_risk else
                 "Nothing is burning faster than 1×; no projected exhaustion.")
    a.cite(state.slo_source, "slo", [r["datadog_id"] for r in rows])
    a.cite(f"{POLICY}/global.yaml", "policy_rule", ["burn_rate_windows"],
           note="30d timeframe = 720h of budget; the projection divides by the observed rate")
    a.caveat("LINEAR EXTRAPOLATION of the instantaneous burn rate over a 30-day window. "
             "It is a triage ordering, not a forecast — Datadog's own SLO history is the "
             "authority on trajectory.")
    return a


@question("services_without_slos", "Which services have no SLO?", "state",
          patterns=["services without slos", "no slo", "missing slo", "unmeasured services"])
def q_services_without_slos(state, p):
    a = _new(state, "services_without_slos")
    findings = state.coverage["checks"]["C4"]
    a.data = {"services": findings,
              "count": state.coverage["summary"]["check_counts"]["C4"]}
    a.summary = (f"{a.data['count']} service(s) map to no SLO, directly or through their "
                 "domain.")
    a.cite("tools/coverage_report.py", "check", ["C4"],
           count=a.data["count"], note="C4 — services without an SLO")
    a.cite(f"{POLICY}/slos.yaml", "slo_definition", sorted(state.policy["slos"]),
           note="a service is covered by a per-service SLO or by its domain's SLO")
    a.cite(state.estate_source, "resource", count=state.assignments["summary"]["total"],
           note="the denominator the check ran against")
    return a


@question("telemetry_feeding_slo", "Which telemetry feeds this SLO?", "state",
          params={"slo_id": "e.g. slo-api-availability"},
          patterns=["telemetry feeds", "what data feeds", "which metrics feed",
                    "sli source"])
def q_telemetry_for_slo(state, p):
    a = _new(state, "telemetry_feeding_slo")
    sid = p.get("slo_id")
    catalog = state.policy["slos"]
    if not sid:
        return a.unanswerable("pass slo_id (see obs.list_slos)")
    slo = catalog.get(sid)
    if not slo:
        return a.unanswerable(f"{sid!r} is not in {POLICY}/slos.yaml")

    metrics, members = [], []
    if slo.get("type") == "metric":
        q = slo.get("query") or {}
        metrics = sorted(set(_metrics_in(q.get("numerator")) + _metrics_in(q.get("denominator"))))
        a.cite(f"{POLICY}/slos.yaml", "slo_definition", [sid],
               note="metric SLO — numerator/denominator are the SLI")
    else:
        for aid in slo.get("member_archetypes", []):
            arch = state.policy["archetypes"].get(aid, {})
            members.append({"archetype": aid, "title": arch.get("title"),
                            "query": arch.get("query"),
                            "metrics": _metrics_in(arch.get("query"))})
            metrics.extend(_metrics_in(arch.get("query")))
        metrics = sorted(set(metrics))
        a.cite(f"{POLICY}/archetypes/", "archetype",
               [m["archetype"] for m in members],
               note="monitor SLO — the member monitors' queries are the SLI")

    burn_monitors = [m["id"] for m in state.managed_monitors
                     if state.monitor_tags(m).get("slo_id") == sid
                     and str(state.monitor_tags(m).get("archetype", "")).startswith("slo-burn")]
    a.data = {"slo_id": sid, "name": slo.get("name"), "type": slo.get("type"),
              "scope": slo.get("scope"), "target": slo.get("target"),
              "timeframe": slo.get("timeframe"), "metrics": metrics,
              "member_archetypes": members,
              "burn_alert_monitor_ids": burn_monitors,
              "telemetry_dependency": slo.get("telemetry_dependency")}
    a.summary = (f"{sid} is a {slo.get('type')} SLO fed by "
                 f"{len(metrics)} metric name(s): {', '.join(metrics) or '(none extracted)'}.")
    a.cite(state.monitor_source, "monitor", burn_monitors,
           note="burn-rate monitors generated from this objective")
    if slo.get("telemetry_dependency"):
        a.caveat(f"Declared telemetry dependency: {slo['telemetry_dependency']} "
                 "(coverage check C13 reports it every run).")
    a.caveat(
        f"{TRACEABILITY} §8: NOTHING EMITS THE `alert_band` TAG onto telemetry today. "
        "Every query above filters on it, so these SLIs currently select an empty set. "
        "The SLO is correctly defined; the telemetry contract is not yet met "
        "(see docs/telemetry-gaps.md).")
    return a


@question("why_service_received_slo", "Why did this service receive this SLO?", "state",
          params={"service": "registered service name", "slo_id": "optional"},
          patterns=["why does this service have an slo", "why this slo",
                    "where did this slo come from", "slo inheritance"])
def q_why_slo(state, p):
    a = _new(state, "why_service_received_slo")
    svc_name = p.get("service")
    svc = _service_record(state, svc_name) if svc_name else None
    if not svc:
        return a.unanswerable(
            f"service {svc_name!r} is not registered in platform/entities/ "
            f"(registered: {', '.join(sorted(state.services)) or 'none'})")

    import obs_act

    tier = svc["tier"]
    tier_policy = state.policy["tiers"][tier]
    sa = state.policy["service_archetypes"][svc["service_archetype"]]
    domain = sa["domain"]

    # The whole answer comes from the resolver Terraform uses, so "why" cannot
    # drift from "what was built". The four-step narration that used to live
    # here ended at a `tier0_slo_template` that no longer exists.
    r = obs_act.resolve_slo_profile(state, service=svc_name, tier=tier,
                                    service_archetype=svc["service_archetype"])
    scope = r["scope"]
    domain_slos = {sid: s for sid, s in state.policy["slos"].items()
                   if s.get("scope") == "domain" and s.get("domain") == domain}

    chain = [
        {"step": 1, "layer": "entity registration",
         "source": f"platform/entities/{svc_name}.yaml",
         "fact": (f"criticality={tier}, service_archetype={svc['service_archetype']}, "
                  f"slo.scope={scope} (declared by {r['scope_declared_by']})")},
        {"step": 2, "layer": "service archetype -> domain",
         "source": f"{POLICY}/service_archetypes.yaml",
         "fact": f"{svc['service_archetype']} -> domain={domain}"},
        {"step": 3, "layer": "tier SLO policy", "source": f"{POLICY}/tiers.yaml",
         "fact": (f"tiers.{tier}.slo.scope={tier_policy['slo']['scope']}, required="
                  f"{tier_policy['slo']['required']}")},
    ]
    if r["per_service"]:
        # One step per LAYER THAT ACTUALLY SET SOMETHING, read off the resolver's
        # provenance rather than assumed — a layer that changed nothing for this
        # service does not get to appear in its explanation.
        layers_used = []
        for obj in r["objectives"].values():
            for _field, layer in (obj.get("provenance") or {}).items():
                if layer not in layers_used:
                    layers_used.append(layer)
        chain.append(
            {"step": 4, "layer": "SLO resolution chain (12)",
             "source": f"{POLICY}/slo_profiles.yaml",
             "fact": (f"scope=per_service -> objectives "
                      f"{', '.join(sorted(r['objectives'])) or '(none)'} resolved through "
                      f"layers: {', '.join(layers_used) or '(defaults only)'}"
                      + (f"; profile={r['slo_profile']}" if r["slo_profile"] else
                         "; no slo.profile declared, so the entity type, platform and "
                         "criticality layers decide alone"))})
        for name, obj in sorted(r["objectives"].items()):
            fact = (f"enabled, target={obj['target']} "
                    f"(from {obj['provenance'].get('target')}), "
                    f"timeframe={obj['timeframe']}, burn_alerts={obj['burn_alerts']} "
                    f"-> {obj['slo_id']}") if obj["enabled"] else (
                    f"available but NOT enabled -- target would be {obj['target']} "
                    f"(from {obj['provenance'].get('target')})")
            chain.append({"step": 5, "layer": f"objective: {name}",
                          "source": f"{POLICY}/slo_profiles.yaml", "fact": fact})
    else:
        chain.append(
            {"step": 4, "layer": "SLO catalog", "source": f"{POLICY}/slos.yaml",
             "fact": (f"scope={scope} -> no per-service SLO is built; covered by the "
                      f"{domain} domain SLOs: {', '.join(sorted(domain_slos)) or '(none)'}")})

    a.data = {"service": svc_name, "tier": tier, "domain": domain,
              "slo_scope": scope, "scope_declared_by": r["scope_declared_by"],
              "per_service": r["per_service"], "slo_profile": r["slo_profile"],
              "objectives": r["objectives"],
              "enabled_objectives": r["enabled_objectives"],
              "resolution_chain": chain,
              "domain_slos": sorted(domain_slos),
              "burn_windows": tier_policy["slo"]["burn_windows"],
              "error_budget_policy": (tier_policy["slo"].get("error_budget_policy") or "").strip()}
    if r["per_service"]:
        a.summary = (f"{svc_name} is {tier} with slo.scope={scope} (declared by "
                     f"{r['scope_declared_by']}), so it gets its own SLO(s): "
                     f"{', '.join(r['enabled_objectives']) or 'none enabled'}. Targets "
                     f"resolve through the layered chain, not a single template.")
    else:
        a.summary = (f"{svc_name} is {tier} with slo.scope={scope}, so it builds no "
                     f"per-service SLO and is covered by the {domain} domain SLO(s): "
                     f"{', '.join(sorted(domain_slos)) or 'none'}.")
    a.cite(f"platform/entities/{svc_name}.yaml", "service_registration", [svc_name])
    a.cite(f"{POLICY}/tiers.yaml", "policy_rule", [f"tiers.{tier}.slo"])
    if r["per_service"]:
        a.cite(f"{POLICY}/slo_profiles.yaml", "policy_rule", r["cited_rules"])
    a.cite(f"{POLICY}/slos.yaml", "slo_definition", sorted(domain_slos))
    a.caveat(f"{TRACEABILITY} §11/§12: a service cannot yet declare MULTIPLE named "
             "objectives or override the domain target — there is no slo_profile layer.")
    return a


# ===========================================================================
# 15–24 · coverage, ownership, governance
# ===========================================================================
@question("entities_without_owners", "Which entities have no owner?", "state",
          patterns=["without owners", "no owner", "unowned", "who owns nothing",
                    "orphaned resources"])
def q_unowned(state, p):
    a = _new(state, "entities_without_owners")
    ids = state.coverage["checks"]["C2"]
    total = state.coverage["summary"]["check_counts"]["C2"]
    pool = state.policy["teams_doc"]["unowned_pool"]
    a.data = {"count": total, "sample": ids[:50], "unowned_pool": pool}
    a.summary = (f"{total} resource(s) resolve to no owner and are parked in the "
                 f"`{pool['team']}` unowned pool (SLA {pool['max_age_days']} days).")
    a.cite("tools/coverage_report.py", "check", ["C2"], count=total)
    a.cite(state.estate_source, "resource", ids, count=total)
    a.cite(f"{POLICY}/teams.yaml", "policy_rule", ["unowned_pool"],
           note="parking is time-boxed; C2 is a governance finding, not a resting state")
    return a


@question("services_lacking_monitoring", "Which services lack monitoring?", "state",
          patterns=["lacking monitoring", "not monitored", "no monitors", "uncovered"])
def q_uncovered(state, p):
    a = _new(state, "services_lacking_monitoring")
    findings = state.coverage["checks"]["C1"]
    total = state.coverage["summary"]["check_counts"]["C1"]
    a.data = {"count": total, "sample": findings[:50],
              "observe_only_by_policy": state.coverage["summary"]["resources_observe_only"],
              "alertable": state.coverage["summary"]["resources_alertable"]}
    a.summary = (f"{total} alertable resource(s) have no covering monitor pack. "
                 f"A further {a.data['observe_only_by_policy']} are observe-only BY POLICY "
                 "(tier3 or dev), each with a recorded reason — those are decisions, "
                 "not gaps.")
    a.cite("tools/coverage_report.py", "check", ["C1"], count=total,
           note="C1 — a resource is covered only when every MANDATORY archetype in its "
                "packs is instantiated for its env and band")
    a.cite(state.estate_source, "resource", count=state.assignments["summary"]["total"])
    return a


@question("coverage_percentage", "What is our monitoring coverage?", "state",
          patterns=["coverage", "coverage percentage", "how much is monitored",
                    "percent covered"])
def q_coverage(state, p):
    a = _new(state, "coverage_percentage")
    s = state.coverage["summary"]
    a.data = {
        "coverage_pct": s["coverage_pct"],
        "covered": s["resources_covered"], "alertable": s["resources_alertable"],
        "observe_only": s["resources_observe_only"], "total": s["resources_total"],
        "monitors_total": s["monitors_total"], "monitors_managed": s["monitors_managed"],
        "monitors_paging": s["monitors_paging"],
        "check_counts": s["check_counts"],
        "governance_gate": "PASS" if s["pass"] else "FAIL",
        "deploy_gate": "PASS" if s["deploy_pass"] else "FAIL",
    }
    a.summary = (f"{s['coverage_pct']}% of the alertable estate is covered "
                 f"({s['resources_covered']}/{s['resources_alertable']}); "
                 f"{s['resources_observe_only']} resources are observe-only by policy. "
                 f"{s['monitors_managed']} managed monitors, {s['monitors_paging']} able "
                 "to page.")
    a.cite("tools/coverage_report.py", "check", [f"C{i}" for i in range(1, 18)],
           note="the same seventeen runtime checks the nightly governance loop runs")
    a.cite(state.monitor_source, "monitor", count=s["monitors_total"])
    a.cite(state.estate_source, "resource", count=s["resources_total"])
    return a


@question("top_reliability_risks", "What are the top reliability risks?", "partial",
          params={"limit": "int, default 10"},
          patterns=["top risks", "reliability risks", "biggest risks", "what should we fix"],
          note="Ranked by a server-side weighting over policy findings; the WEIGHTS are "
               "not policy.")
def q_risks(state, p):
    a = _new(state, "top_reliability_risks")
    limit = int(p.get("limit") or 10)
    s = state.coverage["summary"]
    checks = state.coverage["checks"]
    risks = []

    def add(title, severity, count, why, source, ids=()):
        if count:
            risks.append({"risk": title, "severity": severity, "count": count,
                          "why_it_matters": why, "source": source, "sample": list(ids)[:5]})

    add("Unowned resources", "high", s["check_counts"]["C2"],
        "an unowned resource has nobody to route its alert to; the page is a dead letter",
        "coverage C2", checks["C2"])
    add("Alertable resources with no covering monitor", "high", s["check_counts"]["C1"],
        "silent by accident rather than by decision — the failure this platform exists to "
        "prevent", "coverage C1", [f.get("id") for f in checks["C1"]])
    add("Services with no SLO", "medium", s["check_counts"]["C4"],
        "no error budget means no defensible answer to 'is this good enough'",
        "coverage C4", checks["C4"])
    add("Expired exceptions", "high", s["check_counts"]["C12"],
        "an expired exception is an un-reviewed permanent deviation",
        "coverage C12", [f.get("id") for f in checks["C12"]])
    add("Click-ops monitors", "medium", s["check_counts"]["C9"],
        "unmanaged monitors drift, have no runbook and disappear on the next apply",
        "coverage C9", [f.get("id") for f in checks["C9"]])
    add("Paging-discipline violations", "high", s["check_counts"]["C14"],
        "anything paging outside policy trains responders to ignore pages",
        "coverage C14", [f.get("name") for f in checks["C14"]])
    add("SLO integrity / silent telemetry", "high", s["check_counts"]["C13"],
        "an objective computed from telemetry nobody emits reports success forever",
        "coverage C13", [f.get("slo_id") or f.get("slo") for f in checks["C13"]])

    # Runtime risks, if a runtime surface is available.
    try:
        burning = [r for r in _slo_rows(state)
                   if r["budget_pct"] is not None and r["budget_pct"] < 25]
        add("SLOs with under 25% error budget", "high", len(burning),
            "budget exhaustion triggers the tier's error-budget policy (freeze or review)",
            state.slo_source, [r["slo_id"] for r in burning])
        stale = [h for h in (state.runtime.get("hosts") or []) if not h.get("up")]
        add("Hosts not reporting", "medium", len(stale),
            "a host that stopped reporting looks healthy to every metric monitor",
            state.runtime_source, [h["name"] for h in stale])
    except obs_state.DatadogUnavailable:
        a.caveat("Runtime surfaces were unavailable; only repository-derived risks ranked.")

    order = {"high": 0, "medium": 1, "low": 2}
    risks.sort(key=lambda r: (order[r["severity"]], -r["count"]))
    a.data = {"risks": risks[:limit], "considered": len(risks)}
    a.summary = (f"{len(risks)} risk categories with findings; top: "
                 + ", ".join(f"{r['risk']} ({r['count']})" for r in risks[:3]) if risks
                 else "No risk category has any finding.")
    a.cite("tools/coverage_report.py", "check",
           [f"C{i}" for i in range(1, 18)], note="every governance check, ranked")
    a.cite(state.monitor_source, "monitor", count=len(state.managed_monitors))
    a.caveat("Severity here is a SERVER-SIDE weighting of policy findings. "
             f"{POLICY}/ ranks nothing; if this ordering matters operationally it belongs "
             "in policy, not in this server.")
    return a


@question("why_service_inherited_monitor", "Why did this service inherit this monitor?",
          "state",
          params={"service": "registered service name", "archetype": "archetype id"},
          patterns=["why did this service get", "why this monitor", "monitor inheritance",
                    "where did this monitor come from"])
def q_why_monitor(state, p):
    a = _new(state, "why_service_inherited_monitor")
    svc_name, aid = p.get("service"), p.get("archetype")
    if not svc_name or not aid:
        return a.unanswerable("pass both service and archetype")
    svc = _service_record(state, svc_name)
    if not svc:
        return a.unanswerable(f"service {svc_name!r} is not registered in platform/entities/")
    arch = state.policy["archetypes"].get(aid)
    if not arch:
        return a.unanswerable(f"archetype {aid!r} does not exist in {POLICY}/archetypes/")

    sa_id = svc["service_archetype"]
    sa = state.policy["service_archetypes"][sa_id]
    packs = sa["packs"]
    via_packs = [pk for pk in packs if aid in state.policy["packs"][pk]["archetypes"]]
    tier = svc["tier"]
    profile = state.policy["tiers"][tier]["monitoring_profile"]
    band = state.policy["tiers_doc"]["profile_to_band"][profile]

    per_env = []
    for env in svc["envs"]:
        ep = state.policy["environments"][env]
        eff_profile, clamped = profile, None
        if not ep["alerting"]:
            eff_profile = "observe_only"
        elif env in ("qa", "dev") and profile in ("standard", "critical"):
            eff_profile, clamped = "baseline", "qa/dev clamp (profile_engine step 5)"
        eff_band = state.policy["tiers_doc"]["profile_to_band"][eff_profile]
        env_ok = env in arch["envs"]
        band_ok = eff_band in arch["bands"]
        instantiated = env_ok and band_ok and eff_band in ep["bands_instantiated"]
        entry = {"env": env, "effective_profile": eff_profile, "effective_band": eff_band,
                 "clamped_by": clamped,
                 "archetype_envs": arch["envs"], "archetype_bands": arch["bands"],
                 "env_matches": env_ok, "band_matches": band_ok,
                 "instantiated": instantiated}
        if instantiated:
            # The SAME three functions Terraform's inputs are derived from. If
            # this file computed priority itself, the explanation and the
            # deployed monitor could disagree — which is the one thing an
            # "explain your inheritance" tool must never do.
            priority = oc.resolve_priority(state.policy, arch["impact_class"], eff_band, env)
            entry["priority"] = priority
            entry["pages"] = oc.pages(state.policy, priority, eff_band, env)
            entry["notification_profile"] = oc.resolve_notification_profile(
                state.policy, arch["domain"], env, eff_band)
        per_env.append(entry)

    inherited = bool(via_packs) and any(e["instantiated"] for e in per_env)
    chain = [
        {"step": 1, "layer": "service registration",
         "source": f"platform/entities/{svc_name}.yaml",
         "fact": f"service_archetype={sa_id}, tier={tier}, envs={svc['envs']}"},
        {"step": 2, "layer": "service archetype → packs",
         "source": f"{POLICY}/service_archetypes.yaml",
         "fact": f"{sa_id} selects packs {packs}"},
        {"step": 3, "layer": "pack → archetype",
         "source": f"{POLICY}/service_archetypes.yaml",
         "fact": (f"{aid} is a member of {via_packs}" if via_packs
                  else f"{aid} is in NO pack selected by {sa_id} — not inherited")},
        {"step": 4, "layer": "tier → profile → band", "source": f"{POLICY}/tiers.yaml",
         "fact": f"{tier} → monitoring_profile={profile} → alert_band={band}"},
        {"step": 5, "layer": "environment instantiation",
         "source": f"{POLICY}/environments.yaml",
         "fact": "per-environment result in `per_environment`"},
        {"step": 6, "layer": "selection",
         "source": f"{POLICY}/archetypes/{arch['domain']}.yaml",
         "fact": (f"the monitor query is scoped `{arch.get('selector', '(no selector)')}` "
                  f"and grouped by {arch.get('group_by', [])}; the service joins as a GROUP, "
                  "it does not create a monitor")},
    ]
    a.data = {"service": svc_name, "archetype": aid, "inherited": inherited,
              "via_packs": via_packs, "resolution_chain": chain,
              "per_environment": per_env,
              "mandatory": bool(arch.get("mandatory")),
              "slo_id": arch.get("slo_id"), "runbook": arch.get("runbook"),
              "workflow": arch.get("workflow")}
    a.summary = (
        f"{svc_name} {'inherits' if inherited else 'does NOT inherit'} {aid}: "
        f"service_archetype={sa_id} → packs {packs} "
        f"{'→ ' + str(via_packs) if via_packs else '(archetype in none of them)'}; "
        f"tier {tier} → band {band}.")
    a.cite(f"platform/entities/{svc_name}.yaml", "service_registration", [svc_name])
    a.cite(f"{POLICY}/service_archetypes.yaml", "policy_rule", [sa_id] + packs)
    a.cite(f"{POLICY}/archetypes/{arch['domain']}.yaml", "archetype", [aid])
    a.cite(f"{POLICY}/tiers.yaml", "policy_rule", [tier])
    a.caveat("Inheritance is by TAG SELECTION, not by generation: the monitor already "
             "exists once per (env × band) and this service is one group inside it. "
             "That is why adding services creates zero Datadog objects.")
    return a


@question("what_if_merged", "What would happen if this YAML were merged?", "state",
          params={"yaml": "manifest text", "kind": "service|monitor (inferred if omitted)"},
          patterns=["what would happen if", "if I merge", "impact of this yaml",
                    "dry run this yaml"])
def q_what_if(state, p):
    import obs_act
    a = _new(state, "what_if_merged")
    text = p.get("yaml")
    if not text:
        return a.unanswerable("pass the manifest text as `yaml`")
    preview = obs_act.preview_manifest(state, text, kind=p.get("kind"))
    a.data = preview
    verdict = "would be REJECTED by CI" if preview["errors"] else "would pass validation"
    a.summary = (f"{preview['kind']} manifest for {preview.get('subject')} {verdict}. "
                 f"{preview['delta']['summary']}")
    a.cite("tools/validate_monitors.py" if preview["kind"] == "monitor"
           else "platform/schemas/service.schema.json", "validator",
           count=len(preview["errors"]), note="the same validation the CI gate runs")
    a.cite(f"{POLICY}/", "policy_rule", preview["resolution"].get("cited_rules", []),
           note="the hierarchy layers that decided the outcome")
    a.cite(state.monitor_source, "monitor", count=len(state.managed_monitors),
           note="the current estate the delta is measured against")
    return a


@question("expiring_exceptions", "Which exceptions have expired or expire soon?", "state",
          params={"within_days": "int, default 30"},
          patterns=["expired exceptions", "exceptions expiring", "waivers", "exemptions"])
def q_exceptions(state, p):
    a = _new(state, "expiring_exceptions")
    within = int(p.get("within_days") or 30)
    today = dt.date.today()
    rows = []
    for e in state.policy["exceptions"]:
        exp = e["expires"]
        if not isinstance(exp, dt.date):
            exp = dt.date.fromisoformat(str(exp))
        days = (exp - today).days
        if days <= within:
            rows.append({"id": e["id"], "control": e.get("control"), "owner": e.get("owner"),
                         "expires": str(exp), "days_remaining": days,
                         "expired": days < 0,
                         "reason": (e.get("reason") or "").strip().splitlines()[0]
                         if e.get("reason") else ""})
    rows.sort(key=lambda r: r["days_remaining"])
    a.data = {"within_days": within, "exceptions": rows,
              "expired": sum(1 for r in rows if r["expired"]),
              "total_exceptions": len(state.policy["exceptions"])}
    a.summary = (f"{len(rows)} of {len(state.policy['exceptions'])} exceptions expire within "
                 f"{within} days; {a.data['expired']} are already expired.")
    a.cite(f"{POLICY}/exceptions.yaml", "exception", [r["id"] for r in rows],
           count=len(rows))
    a.cite("tools/coverage_report.py", "check", ["C12"],
           count=state.coverage["summary"]["check_counts"]["C12"],
           note="C12 fails the governance gate on any expired exception")
    return a


@question("paging_estate", "What can wake a human, and why is it allowed to?", "state",
          patterns=["what pages", "what wakes someone", "paging monitors", "who gets woken"])
def q_paging(state, p):
    a = _new(state, "paging_estate")
    rows = []
    for m in state.managed_monitors:
        t = state.monitor_tags(m)
        if t.get("pages") != "true":
            continue
        arch = str(t.get("archetype", ""))
        source = ("slo_burn" if arch.startswith("slo-burn")
                  else "composite" if arch == "composite" else "archetype")
        rows.append({"id": m["id"], "name": m.get("name"),
                     "priority": (t.get("priority") or "").upper(),
                     "env": t.get("env"), "band": t.get("alert_band"),
                     "team": t.get("team"), "source": source,
                     "route": state.route_for(t.get("notification_profile", ""),
                                              t.get("priority", "p1"), True)})
    rule = state.policy["priorities"]["paging_rule"]
    a.data = {"paging": rows, "count": len(rows),
              "managed_total": len(state.managed_monitors),
              "paging_rule": rule,
              "pct_of_estate": round(100.0 * len(rows) / max(1, len(state.managed_monitors)), 2)}
    a.summary = (f"{len(rows)} of {len(state.managed_monitors)} managed monitors "
                 f"({a.data['pct_of_estate']}%) can page. Policy: P1 always; P2 only from "
                 f"{', '.join(rule['p2_pages_only_from'])}; production and the critical "
                 "band only.")
    a.cite(state.monitor_source, "monitor", [r["id"] for r in rows], count=len(rows))
    a.cite(f"{POLICY}/priorities.yaml", "policy_rule", ["paging_rule"])
    a.cite("tools/coverage_report.py", "check", ["C14"],
           count=state.coverage["summary"]["check_counts"]["C14"],
           note="C14 — anything paging outside this rule is a finding")
    return a


@question("unmanaged_monitors", "Which monitors were created outside Terraform?", "state",
          patterns=["click ops", "clickops", "unmanaged monitors", "manual monitors",
                    "not in terraform"])
def q_unmanaged(state, p):
    a = _new(state, "unmanaged_monitors")
    rows = state.coverage["checks"]["C9"]
    a.data = {"count": state.coverage["summary"]["check_counts"]["C9"], "monitors": rows[:100]}
    a.summary = (f"{a.data['count']} monitor(s) carry no `managed_by:terraform` tag — they "
                 "were created in the UI and have no runbook, route or owner contract.")
    a.cite("tools/coverage_report.py", "check", ["C9"], count=a.data["count"])
    a.cite(state.monitor_source, "monitor",
           [r.get("id") for r in rows], count=a.data["count"])
    return a


@question("estate_summary", "Summarize the platform.", "state",
          patterns=["summary", "overview", "describe the platform", "how big is the estate"])
def q_estate(state, p):
    a = _new(state, "estate_summary")
    pol = state.policy
    s = state.coverage["summary"]
    a.data = {
        "archetypes": len(pol["archetypes"]),
        "archetype_instances": len(state.instances),
        "monitors_managed": s["monitors_managed"],
        "monitors_paging": s["monitors_paging"],
        "slos": len(pol["slos"]),
        "composites": len(pol["composites"]),
        "teams": len(pol["teams"]),
        "domains": len(pol["domains"]),
        "environments": sorted(pol["environments"]),
        "tiers": sorted(pol["tiers"]),
        "runbooks": len(pol["runbooks"]),
        "workflows": len(pol["workflows"]),
        "registered_services": sorted(state.services),
        "self_service_monitors": sorted(state.custom_monitors),
        "exceptions": len(pol["exceptions"]),
        "coverage_pct": s["coverage_pct"],
    }
    a.summary = (f"{a.data['archetypes']} archetypes expand to {a.data['monitors_managed']} "
                 f"managed monitors ({a.data['monitors_paging']} able to page) covering "
                 f"{s['resources_alertable']} alertable resources at {s['coverage_pct']}%. "
                 f"{a.data['slos']} SLOs, {a.data['teams']} teams, "
                 f"{a.data['runbooks']} runbooks.")
    a.cite(f"{POLICY}/", "policy_rule", sorted(pol["archetypes"])[:25],
           count=len(pol["archetypes"]), note="the archetype catalog")
    a.cite(state.monitor_source, "monitor", count=s["monitors_total"])
    a.cite(state.estate_source, "resource", count=s["resources_total"])
    return a


# ===========================================================================
# 25–30 · fleet, telemetry, noise, ownership, routing
# ===========================================================================
@question("broken_agents", "Which agents are broken or stale?", "partial",
          params={"stale_hours": "int, default 2"},
          patterns=["broken agents", "agent health", "agents down", "stale hosts",
                    "hosts not reporting"],
          note="Agent HEALTH is observable; fleet COMPLIANCE percentage is not (§36/§39).")
def q_agents(state, p):
    a = _new(state, "broken_agents")
    hosts = state.runtime.get("hosts")
    if hosts is None:
        return a.unanswerable("no host surface available in this mode")
    stale_seconds = int(p.get("stale_hours") or 2) * 3600
    now = state.runtime.get("captured_ts") or int(dt.datetime.now(dt.timezone.utc).timestamp())
    versions = sorted({h.get("agent_version") for h in hosts if h.get("agent_version")})
    newest = versions[-1] if versions else None
    broken, drifted = [], []
    for h in hosts:
        age = now - (h.get("last_reported_ts") or 0)
        if not h.get("up") or age > stale_seconds:
            broken.append({"host": h["name"], "up": h.get("up"),
                           "last_reported_age_hours": round(age / 3600, 1),
                           "agent_version": h.get("agent_version"),
                           "team": (h.get("tags") or {}).get("team")})
        elif newest and h.get("agent_version") != newest:
            drifted.append({"host": h["name"], "agent_version": h.get("agent_version"),
                            "newest_seen": newest})
    a.data = {"hosts_seen": len(hosts), "broken": broken, "version_drift": drifted,
              "agent_versions": versions}
    a.summary = (f"{len(broken)} of {len(hosts)} hosts are down or have not reported in "
                 f"{p.get('stale_hours') or 2}h; {len(drifted)} run an older agent than "
                 f"the newest observed ({newest}).")
    a.cite(state.runtime_source if state.mode == "fixtures" else "datadog:/api/v1/hosts",
           "host", [h["name"] for h in hosts], count=len(hosts))
    a.cite(f"{POLICY}/archetypes/infrastructure.yaml", "archetype",
           [aid for aid in state.policy["archetypes"] if "agent" in aid],
           note="the archetypes that alert on this condition in production")
    a.caveat(
        f"{TRACEABILITY} §36/§39: FLEET COMPLIANCE PERCENTAGE CANNOT BE COMPUTED. Nothing "
        "declares which hosts are REQUIRED to run an agent, so there is no denominator — "
        "only hosts Datadog can already see appear above. A host with no agent at all is "
        "invisible to this answer by construction.")
    return a


@question("missing_integrations", "Which integrations are missing?", "partial",
          patterns=["missing integrations", "integrations not installed",
                    "which integrations do we need"],
          note="INFERRED from the metric namespaces archetype queries reference (§38: "
               "archetypes declare no telemetry requirement).")
def q_missing_integrations(state, p):
    a = _new(state, "missing_integrations")
    observed = set(state.runtime.get("integrations") or [])
    required: dict[str, list] = {}
    for aid, arch in state.policy["archetypes"].items():
        for metric in _metrics_in(arch.get("query")):
            ns = metric.split(".", 1)[0]
            required.setdefault(ns, []).append(aid)
    # `acme.*` are the platform's OWN custom metrics with an emission contract in
    # docs/telemetry-gaps.md — not an integration anybody installs.
    custom = {ns: aids for ns, aids in required.items() if ns == "acme"}
    integrations = {ns: aids for ns, aids in required.items() if ns != "acme"}
    missing = {ns: sorted(set(aids)) for ns, aids in sorted(integrations.items())
               if ns not in observed}
    a.data = {
        "observed_integrations": sorted(observed),
        "namespaces_required_by_archetypes": sorted(integrations),
        "not_observed": missing,
        "custom_metric_namespaces": {k: sorted(set(v)) for k, v in custom.items()},
        "inference": "metric namespace prefix of every archetype query",
    }
    a.summary = (f"{len(integrations)} metric namespaces are referenced by archetype "
                 f"queries; {len(missing)} have no matching integration in the observed "
                 f"set ({', '.join(sorted(observed)) or 'none observed'}).")
    a.cite(f"{POLICY}/archetypes/", "archetype", sorted(integrations),
           count=len(integrations), note="namespaces extracted from the catalog's queries")
    a.cite(state.runtime_source if state.mode == "fixtures"
           else "datadog:/api/v1/hosts (apps)", "integration", sorted(observed))
    a.caveat(
        f"{TRACEABILITY} §38: ARCHETYPES DECLARE NO `telemetry:` REQUIREMENT, so 'required "
        "integration' is INFERRED here from the metric namespace each query reads. That is "
        "a heuristic, not policy. The real fix is a telemetry requirement on every "
        "archetype and an applicability engine — until then treat this list as a lead, "
        "not an inventory.")
    a.caveat("The observed set comes from host `apps`, which only sees integrations on "
             "hosts that already run an agent. Account-level integrations (Azure, "
             "Snowflake) may be present and not appear here.")
    return a


@question("noisy_monitors", "Which monitors are noisy?", "partial",
          params={"min_triggers": f"int, default {obs_state.NOISE_DEFAULTS['noisy_triggers_30d']}"},
          patterns=["noisy monitors", "which monitors fire too much", "alert fatigue",
                    "flapping"],
          note="No policy defines a noise threshold — the default is a SERVER default.")
def q_noisy(state, p):
    a = _new(state, "noisy_monitors")
    activity = state.runtime.get("monitor_activity") or {}
    if not activity:
        return a.unanswerable("no monitor activity history available in this mode")
    threshold = int(p.get("min_triggers") or obs_state.NOISE_DEFAULTS["noisy_triggers_30d"])
    window = state.runtime.get("window_days", 30)
    rows = []
    for m in state.managed_monitors:
        act = activity.get(str(m["id"])) or {}
        if (act.get("triggers") or 0) >= threshold:
            t = state.monitor_tags(m)
            rows.append({"id": m["id"], "name": m.get("name"),
                         "triggers": act["triggers"], "flaps": act.get("flaps", 0),
                         "priority": (t.get("priority") or "").upper(),
                         "pages": t.get("pages") == "true",
                         "team": t.get("team"), "archetype": t.get("archetype"),
                         "detection": t.get("detection")})
    rows.sort(key=lambda r: -r["triggers"])
    a.data = {"threshold": threshold, "window_days": window, "noisy": rows,
              "monitors_with_history": len(activity)}
    a.summary = (f"{len(rows)} monitor(s) fired {threshold}+ times in {window} days; "
                 f"{sum(1 for r in rows if r['pages'])} of them can page.")
    a.cite(state.runtime_source, "monitor_activity",
           [r["id"] for r in rows], count=len(rows),
           note=f"trigger counts over {window} days")
    a.cite(state.monitor_source, "monitor", count=len(state.managed_monitors))
    a.caveat(
        f"THE THRESHOLD IS NOT POLICY. {POLICY}/ budgets the monitor COUNT "
        "(global.yaml → cardinality) and the PAGING rule (priorities.yaml) but says "
        f"nothing about firing RATE. {threshold} triggers per {window} days is this "
        "server's default and is overridable per call. If noise is to be governed it "
        "belongs in policy.")
    if state.mode == "live":
        a.caveat("Live counts are reconstructed from the Datadog event stream, which is "
                 "retention-bounded; a monitor older than the retention window may be "
                 "undercounted.")
    return a


@question("never_triggered_monitors", "Which monitors have never triggered?", "partial",
          params={"limit": "int, default 100"},
          patterns=["never triggered", "never fired", "monitors that never fire",
                    "dead monitors"],
          note="Bounded by the activity window; a monitor that CANNOT fire (§8) looks "
               "identical here to one that simply has not needed to.")
def q_never_triggered(state, p):
    a = _new(state, "never_triggered_monitors")
    activity = state.runtime.get("monitor_activity") or {}
    if not activity:
        return a.unanswerable("no monitor activity history available in this mode")
    window = state.runtime.get("window_days", 30)
    rows = []
    for m in state.managed_monitors:
        act = activity.get(str(m["id"]))
        if act is not None and not act.get("triggers") and not act.get("last_triggered_ts"):
            t = state.monitor_tags(m)
            rows.append({"id": m["id"], "name": m.get("name"), "env": t.get("env"),
                         "band": t.get("alert_band"), "archetype": t.get("archetype"),
                         "detection": t.get("detection"), "team": t.get("team")})
    a.data = {"window_days": window, "count": len(rows),
              "monitors": rows[:int(p.get("limit") or 100)],
              "by_detection": {}}
    for r in rows:
        a.data["by_detection"][r["detection"]] = a.data["by_detection"].get(r["detection"], 0) + 1
    a.summary = (f"{len(rows)} of {len(state.managed_monitors)} managed monitors have not "
                 f"fired in {window} days.")
    a.cite(state.runtime_source, "monitor_activity", [r["id"] for r in rows],
           count=len(rows), note=f"no trigger recorded in {window} days")
    a.cite(state.monitor_source, "monitor", count=len(state.managed_monitors))
    a.caveat("NOT FIRING IS USUALLY CORRECT. Most of this estate is predictive detection "
             "on conditions that should be rare; a never-fired monitor is a candidate for "
             "review, not a defect. The dangerous case is a monitor that CANNOT fire — "
             f"see {TRACEABILITY} §8, where the `alert_band` tag is not emitted onto "
             "telemetry, so many queries select an empty set.")
    a.caveat(f"Bounded by the {window}-day activity window: a recently deployed monitor "
             "appears here regardless.")
    return a


@question("owner_of", "Who owns this entity?", "state",
          params={"entity": "service name, resource id, or monitor id"},
          patterns=["who owns", "owner of", "which team owns", "responsible team"])
def q_owner(state, p):
    a = _new(state, "owner_of")
    ent = str(p.get("entity") or "")
    if not ent:
        return a.unanswerable("pass entity (a service name, resource id, or monitor id)")

    if ent in state.services:
        svc = state.services[ent]
        team = state.policy["teams"].get(svc["team"], {})
        a.data = {"kind": "registered_service", "entity": ent, "team": svc["team"],
                  "team_name": team.get("name"), "email": team.get("email"),
                  "escalates_to": team.get("escalation_to"),
                  "servicenow_assignment_group": team.get("servicenow_assignment_group"),
                  "source": "registry", "tier": svc["tier"]}
        a.summary = f"{ent} is owned by {svc['team']} ({team.get('name')}) by registration."
        a.cite(f"platform/entities/{ent}.yaml", "service_registration", [ent])
        a.cite(f"{POLICY}/teams.yaml", "team", [svc["team"]])
        return a

    if ent in state.monitors_by_id:
        t = state.monitor_tags(state.monitors_by_id[ent])
        a.data = {"kind": "monitor", "entity": ent, "team": t.get("team"),
                  "owner_tag": t.get("owner"), "service": t.get("service"),
                  "source": "monitor tags"}
        a.summary = f"monitor {ent} carries team:{t.get('team')}."
        a.cite(state.monitor_source, "monitor", [ent])
        a.cite(f"{POLICY}/teams.yaml", "team", [t.get("team")] if t.get("team") else [])
        return a

    match = next((x for x in state.assignments["assignments"]
                  if x["id"] == ent or x.get("service") == ent), None)
    if match:
        a.data = {"kind": "discovered_resource", "entity": ent, "team": match["team"],
                  "owner_source": match["owner_source"], "tier": match["tier"],
                  "env": match["env"], "domain": match["domain"],
                  "monitoring_profile": match["monitoring_profile"],
                  "alert_band": match["alert_band"], "violations": match["violations"]}
        a.summary = (f"{ent} resolves to {match['team']} via {match['owner_source']}.")
        a.cite(state.estate_source, "resource", [ent])
        a.cite("tools/profile_engine.py", "resolver", ["owner"],
               note="resolution order: tag → registry → domain default → unowned pool")
        return a
    return a.unanswerable(f"{ent!r} matches no registered service, monitor id, or "
                          "discovered resource in the current estate")


@question("route_for", "Where does this alert go?", "state",
          params={"monitor_id": "monitor id"},
          patterns=["where does this go", "who gets notified", "routing", "notification route"])
def q_route(state, p):
    a = _new(state, "route_for")
    mid = str(p.get("monitor_id") or "")
    m = state.monitors_by_id.get(mid)
    if not m:
        return a.unanswerable(f"no monitor with id {mid!r} in the current estate")
    t = state.monitor_tags(m)
    row = next((r for r in state.reconciliation if str(r["id"]) == mid), {})
    a.data = {"monitor_id": mid, "name": m.get("name"),
              "priority": (t.get("priority") or "").upper(),
              "pages": t.get("pages") == "true",
              "notification_profile": t.get("notification_profile"),
              "team": t.get("team"),
              "route": state.route_for(t.get("notification_profile", ""),
                                       t.get("priority", "p3"), t.get("pages") == "true"),
              "escalation_policy": row.get("escalation_policy"),
              "runbook": t.get("runbook"), "runbook_notebook": t.get("runbook_notebook"),
              "workflow": t.get("automation_ref"), "slo_id": t.get("slo_id"),
              "reconciliation_status": row.get("status")}
    a.summary = f"{m.get('name')} routes to: {a.data['route']}."
    a.cite(state.monitor_source, "monitor", [mid])
    a.cite(f"{POLICY}/notification_profiles.yaml", "policy_rule",
           [t.get("notification_profile")] if t.get("notification_profile") else [])
    a.cite("tools/reconciliation_report.py", "resolver", ["route_for"],
           note="the same resolver that produces docs/monitor-reconciliation.md")
    if a.data["pages"]:
        a.caveat(f"{TRACEABILITY} §28: this monitor pages, but the on-call rosters are "
                 "empty — the escalation policy exists and resolves to nobody.")
    return a


# ---------------------------------------------------------------------------
def answer(state, qid: str, params: dict | None = None) -> dict:
    spec = QUESTIONS.get(qid)
    if not spec:
        raise KeyError(qid)
    return spec.handler(state, params or {}).to_dict()


def catalog() -> list[dict]:
    return [QUESTIONS[q].to_dict() for q in sorted(QUESTIONS)]
