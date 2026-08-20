#!/usr/bin/env python3
"""EVENT CORRELATION — executable reference implementation.

Two jobs:

  1. EXECUTABLE SPECIFICATION. CI proves, on every pull request, that a storm of
     related alerts collapses into ONE actionable incident with the right parent
     and the right context attached. "We correlate alerts" is a claim; this is
     the test that makes it a fact.

  2. OPERATOR TOOL. Replay real alert events through the ruleset to debug
     grouping behaviour before changing the in-app configuration.

The deterministic keys (`correlation_key`, `dedup_key`) are stamped on every
monitor by the factory, so native Datadog Event Management aggregation works
with zero custom rules. The topology, vendor-outage, scope-uplift and
maintenance rules in platform/events/correlation-rules.yaml are the intended
policy; this module is their reference behaviour.
"""
from __future__ import annotations

import json

import obs_common as oc
from obs_common import PRIORITY_RANK, RANK_PRIORITY

RULES = None


def load_rules() -> dict:
    global RULES
    if RULES is None:
        import yaml
        RULES = yaml.safe_load(
            (oc.PLATFORM_DIR / "events" / "correlation-rules.yaml").read_text()
        )
    return RULES


def _rule(rules: dict, rid: str) -> dict:
    for r in rules["rules"]:
        if r["id"] == rid:
            return r
    raise KeyError(rid)


def correlate(events: list[dict], pack_service_counts: dict | None = None) -> list[dict]:
    """Correlate a list of alert/recovery/change events into incident groups.

    event = {ts, correlation_key, dedup_key, priority, signal, domain, env,
             region, service, kind: alert|recovery|change, title,
             maintenance: bool}
    """
    rules = load_rules()
    ranking = [r["signal"] for r in rules["root_cause_ranking"]]
    pack_service_counts = pack_service_counts or {}

    # --- 0. maintenance suppression -----------------------------------------
    events = [e for e in events if not e.get("maintenance")]

    # --- 1. deduplicate identical dedup_keys inside the window --------------
    seen: dict[str, float] = {}
    deduped = []
    for e in sorted(events, key=lambda x: x["ts"]):
        if e.get("kind") == "alert":
            last = seen.get(e["dedup_key"])
            if last is not None and e["ts"] - last < rules["dedup_window_seconds"]:
                continue
            seen[e["dedup_key"]] = e["ts"]
        deduped.append(e)

    # --- 2. group alerts by correlation_key; attach change events as context -
    groups: dict[str, dict] = {}
    recovered: set[str] = set()
    change_events = [e for e in deduped if e.get("kind") == "change"]

    for e in deduped:
        if e.get("kind") == "change":
            continue
        if e.get("kind") == "recovery":
            recovered.add(e["dedup_key"])
            continue
        key = e["correlation_key"]
        g = groups.get(key)
        if g is None or e["ts"] - g["first_ts"] > rules["window_seconds"]:
            gkey = key if g is None else f"{key}#{int(e['ts'])}"
            groups[gkey] = {
                "correlation_key": key, "env": e["env"], "region": e.get("region"),
                "first_ts": e["ts"], "members": [e], "context": [], "closed": False,
            }
        else:
            g["members"].append(e)

    # change events join every group in the same env inside the lookback window
    lookback = _rule(rules, "attach-change-context")["lookback_seconds"]
    for c in change_events:
        for g in groups.values():
            if g["env"] == c["env"] and abs(c["ts"] - g["first_ts"]) <= lookback:
                g["context"].append(c)

    # --- 3. parent selection: root-cause ranking, then priority, then time ---
    def rank(e):
        sig = e.get("signal", "telemetry_health")
        return (ranking.index(sig) if sig in ranking else len(ranking),
                PRIORITY_RANK.get(e.get("priority"), 9), e["ts"])

    result = []
    for g in groups.values():
        if not g["members"]:
            continue
        members = sorted(g["members"], key=rank)
        parent, children = members[0], members[1:]

        if (rules["recovery"]["close_group_on_parent_recovery"]
                and parent["dedup_key"] in recovered
                and (not rules["recovery"]["require_all_children_recovered"]
                     or all(c["dedup_key"] in recovered for c in children))):
            g["closed"] = True

        result.append({
            "correlation_key": g["correlation_key"],
            "parent": parent,
            "children": children,
            "context": g["context"],
            "closed": g["closed"],
            "priority": parent.get("priority", "P3"),
            "suppressed": len(children),
        })

    # --- 4. topology: platform cause adopts application symptoms ------------
    topo = _rule(rules, "platform-cause-suppresses-app-symptom")
    vendor = _rule(rules, "vendor-outage-suppresses-integration-symptoms")

    def _absorb(parents_pred, child_pred, join_region: bool,
                window: int | None = None, inherit_priority: bool = False):
        """Merge symptom groups into the group that caused them.

        `window` overrides the global correlation window for rules whose causal
        chain is genuinely slower than five minutes. `inherit_priority` keeps
        the group at the most severe priority among its members — used where the
        cause is a lower-priority signal than the symptom it suppressed, so that
        adopting a child cannot silently downgrade the incident.
        """
        nonlocal result
        window = window or rules["window_seconds"]
        causes = [g for g in result if parents_pred(g)]
        merged = []
        for g in result:
            if child_pred(g) and g not in causes:
                cause = next(
                    (c for c in causes
                     if c["parent"]["env"] == g["parent"]["env"]
                     and (not join_region or c["parent"].get("region") == g["parent"].get("region"))
                     and abs(c["parent"]["ts"] - g["parent"]["ts"]) <= window),
                    None)
                if cause:
                    cause["children"].extend([g["parent"], *g["children"]])
                    cause["context"].extend(g["context"])
                    cause["suppressed"] += 1 + len(g["children"])
                    if inherit_priority:
                        cause["priority"] = RANK_PRIORITY[min(
                            PRIORITY_RANK.get(cause["priority"], 9),
                            PRIORITY_RANK.get(g["priority"], 9))]
                    continue
            merged.append(g)
        result = merged

    # Scheduler topology runs FIRST. A Control-M job holds its whole downstream
    # chain open, and the symptoms it causes (a pipeline that never started,
    # a data product gone stale) outrank it in root_cause_ranking — so without
    # this pass the freshness alert would become the parent and the incident
    # would point at the wrong system. See platform/events/correlation-rules.yaml
    # → scheduler-job-suppresses-downstream-data-symptoms.
    sched = _rule(rules, "scheduler-job-suppresses-downstream-data-symptoms")
    _absorb(lambda g: g["parent"].get("archetype") in sched["parent_archetypes"],
            lambda g: g["parent"].get("domain") in sched["child_domains"],
            join_region=False,
            window=sched.get("lookback_seconds"),
            inherit_priority=sched.get("inherit_child_priority", False))

    _absorb(lambda g: g["parent"].get("domain") in vendor["parent_domains"]
            if "parent_domains" in vendor
            else g["parent"].get("archetype") in vendor["parent_archetypes"],
            lambda g: g["parent"].get("domain") in vendor["child_domains"],
            join_region=False)

    _absorb(lambda g: g["parent"].get("domain") in topo["parent_domains"],
            lambda g: g["parent"].get("domain") in topo["child_domains"],
            join_region=True)

    # --- 5. scope uplift: breadth is business impact -------------------------
    uplift = _rule(rules, "scope-uplift")
    max_rank = PRIORITY_RANK[uplift["max_priority"]]
    for g in result:
        pack = g["parent"].get("pack")
        total = pack_service_counts.get(pack)
        if total:
            distinct = len({c.get("service") for c in g["children"] if c.get("service")}
                           | {g["parent"].get("service")})
            if distinct / total > uplift["threshold"]:
                new_rank = max(max_rank, PRIORITY_RANK[g["priority"]] - 1)
                g["priority"] = RANK_PRIORITY[new_rank]
                g["uplifted"] = True

    # --- 6. final incident/paging decision -----------------------------------
    for g in result:
        inc = rules["incident_creation"].get(g["priority"], {"create_incident": False})
        g["creates_incident"] = bool(inc.get("create_incident")) and not g["closed"]
        # The correlation layer pages once per GROUP, never per member.
        g["pages"] = 0 if g["closed"] else (1 if g["priority"] in ("P1", "P2") else 0)

    return result


if __name__ == "__main__":
    import sys
    events = json.load(open(sys.argv[1]))
    for g in correlate(events):
        print(json.dumps({
            "correlation_key": g["correlation_key"],
            "priority": g["priority"],
            "parent": g["parent"]["title"],
            "children": [c["title"] for c in g["children"]],
            "context": [c["title"] for c in g["context"]],
            "pages": g["pages"],
            "creates_incident": g["creates_incident"],
            "closed": g["closed"],
        }, indent=2))
