#!/usr/bin/env python3
"""Reference implementation of platform/events/correlation-rules.yaml.

Purpose:
  1. Executable spec: CI proves that a storm of related monitor alerts
     collapses into ONE actionable incident (see tests/test_correlation.py).
  2. Operator tool: replay real alert events (JSON) through the ruleset to
     debug grouping behavior before changing the in-app configuration.
"""
from __future__ import annotations

import json
from collections import defaultdict

import obs_common as oc

RULES = None


def load_rules() -> dict:
    global RULES
    if RULES is None:
        import yaml
        RULES = yaml.safe_load(
            (oc.REPO_ROOT / "platform" / "events" / "correlation-rules.yaml").read_text()
        )
    return RULES


SEV_ORDER = {"sev1": 0, "sev2": 1, "sev3": 2, "informational": 3}


def correlate(events: list[dict]) -> list[dict]:
    """events: [{ts, correlation_key, dedup_key, severity, archetype_class,
    domain, env, region, service, kind('alert'|'recovery'|'change'), title}]
    Returns correlation groups with parent, children, context, pages count.
    """
    rules = load_rules()
    ranking = [r["archetype_class"] for r in rules["root_cause_ranking"]]

    # 1. Dedup identical dedup_keys inside the dedup window.
    seen: dict[str, float] = {}
    deduped = []
    for e in sorted(events, key=lambda x: x["ts"]):
        if e.get("kind") == "alert":
            last = seen.get(e["dedup_key"])
            if last is not None and e["ts"] - last < rules["dedup_window_seconds"]:
                continue
            seen[e["dedup_key"]] = e["ts"]
        deduped.append(e)

    # 2. Group alerts by correlation_key within the window; attach change
    #    events as context on (env, service).
    groups: dict[str, dict] = {}
    recovered: set[str] = set()
    for e in deduped:
        if e.get("kind") == "change":
            for g in groups.values():
                if g["env"] == e["env"] and abs(e["ts"] - g["first_ts"]) <= rules["window_seconds"]:
                    g["context"].append(e)
            continue
        if e.get("kind") == "recovery":
            recovered.add(e["dedup_key"])
            continue
        key = e["correlation_key"]
        g = groups.setdefault(key, {
            "correlation_key": key, "env": e["env"], "region": e.get("region"),
            "first_ts": e["ts"], "members": [], "context": [], "closed": False,
        })
        if e["ts"] - g["first_ts"] <= rules["window_seconds"]:
            g["members"].append(e)
        else:
            # outside window → its own group keyed by time bucket
            groups[f"{key}#{int(e['ts'])}"] = {
                "correlation_key": key, "env": e["env"], "region": e.get("region"),
                "first_ts": e["ts"], "members": [e], "context": [], "closed": False,
            }

    # 3. Parent selection by root-cause ranking then severity.
    def rank(e):
        cls = e.get("archetype_class", "telemetry_health")
        return (ranking.index(cls) if cls in ranking else len(ranking),
                SEV_ORDER.get(e.get("severity"), 9), e["ts"])

    result = []
    for g in groups.values():
        if not g["members"]:
            continue
        members = sorted(g["members"], key=rank)
        parent, children = members[0], members[1:]
        if rules["recovery"]["close_group_on_parent_recovery"] \
                and parent["dedup_key"] in recovered \
                and not any(c["dedup_key"] not in recovered for c in children):
            g["closed"] = True

        sev = parent.get("severity", "sev3")
        inc = load_rules()["incident_creation"].get(sev, {"create_incident": False})
        result.append({
            "correlation_key": g["correlation_key"],
            "parent": parent,
            "children": children,
            "context": g["context"],
            "closed": g["closed"],
            "creates_incident": bool(inc.get("create_incident")),
            "pages": 0 if g["closed"] else (1 if sev in ("sev1", "sev2") else 0),
            "suppressed": len(children),
        })

    # 4. Topology rule: platform cause suppresses application symptom groups
    #    in the same env+region → merge them as children of the cause group.
    topo = next(r for r in load_rules()["rules"] if r["id"] == "platform-cause-suppresses-app-symptom")
    causes = [g for g in result if g["parent"].get("domain") in topo["parent_domains"]]
    merged = []
    for g in result:
        if g["parent"].get("domain") in topo["child_domains"]:
            cause = next((c for c in causes
                          if c["parent"]["env"] == g["parent"]["env"]
                          and c["parent"].get("region") == g["parent"].get("region")
                          and abs(c["parent"]["ts"] - g["parent"]["ts"]) <= load_rules()["window_seconds"]), None)
            if cause:
                cause["children"].extend([g["parent"], *g["children"]])
                cause["suppressed"] += 1 + len(g["children"])
                continue
        merged.append(g)
    return merged


if __name__ == "__main__":
    import sys
    events = json.load(open(sys.argv[1]))
    for g in correlate(events):
        print(json.dumps({k: (v if k not in ("parent",) else v["title"])
                          for k, v in g.items() if k != "children"} |
                         {"children": [c["title"] for c in g["children"]]}, indent=2))
