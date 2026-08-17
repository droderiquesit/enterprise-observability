#!/usr/bin/env python3
"""SELF-SERVICE MANIFEST VALIDATION.

Runs on every pull request that touches platform/monitors/. It is the reason a
team can write ONE small YAML file and still end up with a monitor that meets
every enterprise standard: anything the platform cannot derive safely is
rejected here, with an explanation, before Terraform ever runs.

The rejections are the interesting part. Each one exists because the
corresponding mistake is common, expensive, and invisible until an incident.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml

import obs_common as oc

SCHEMA_PATH = oc.PLATFORM_DIR / "schemas" / "monitor.schema.json"
REQUIRED = ["name", "archetype", "service", "team", "env", "slo", "runbook", "workflow"]
CUSTOM_REQUIRED = ["query", "monitor_type", "detection", "impact_class", "domain", "justification"]
PREDICTIVE_FUNCS = ("anomalies(", "forecast(", "outliers(", "pct_change(")


def validate(path: Path, policy: dict, services: dict) -> list[str]:
    errors: list[str] = []
    try:
        doc = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        return [f"unparseable YAML: {exc}"]
    if not isinstance(doc, dict) or "monitor" not in doc:
        return ["file must contain a top-level `monitor:` mapping"]
    m = doc["monitor"]

    # ---- required fields ----------------------------------------------------
    for f in REQUIRED:
        if f not in m:
            errors.append(f"missing required field `{f}`")
    if errors:
        return errors

    g = policy["global"]
    vocab = g["tag_vocabulary"]

    # ---- naming -------------------------------------------------------------
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{4,60}", m["name"]):
        errors.append(
            f"name {m['name']!r} must be kebab-case, 5–61 chars. The name becomes the "
            "monitor_id and request_id tags, so it has to be stable and greppable")
    if m["name"] != path.stem:
        errors.append(f"name {m['name']!r} must match the filename ({path.stem}) so that "
                      "deleting the file deletes the right monitor")

    # ---- references ---------------------------------------------------------
    if m["team"] not in policy["teams"]:
        errors.append(f"team {m['team']!r} is not registered in platform/policy/teams.yaml")
    if m["slo"] not in policy["slos"]:
        errors.append(f"slo {m['slo']!r} is not in the SLO catalog. Every alerting monitor "
                      "must attach to an objective; if none fits, propose one in slos.yaml")
    if m["runbook"] not in policy["runbooks"]:
        errors.append(f"runbook {m['runbook']!r} is not in the runbook registry")
    if m["workflow"] not in policy["workflows"]:
        errors.append(f"workflow {m['workflow']!r} is not in the workflow registry")
    if m["archetype"] != "custom" and m["archetype"] not in policy["archetypes"]:
        errors.append(f"archetype {m['archetype']!r} does not exist. Use an id from "
                      "platform/policy/archetypes/, or `custom` with a full definition")

    # ---- environments -------------------------------------------------------
    for e in m["env"]:
        if e not in vocab["env"]:
            errors.append(f"env {e!r} is not in the controlled vocabulary")
        elif not policy["environments"][e]["alerting"]:
            errors.append(f"env {e!r} does not alert by policy — remove it, the monitor "
                          "would never be created")

    # ---- service registration ----------------------------------------------
    if m["service"] not in services:
        errors.append(
            f"service {m['service']!r} is not registered in platform/services/. Register it "
            "first: without a registration the platform cannot resolve its tier, which "
            "means it cannot resolve this monitor's priority or paging behavior")
    elif services[m["service"]]["team"] != m["team"]:
        errors.append(
            f"team {m['team']!r} does not own service {m['service']!r} "
            f"(registered owner: {services[m['service']]['team']})")

    # ---- custom archetype ---------------------------------------------------
    if m["archetype"] == "custom":
        for f in CUSTOM_REQUIRED:
            if f not in m:
                errors.append(f"`archetype: custom` requires `{f}` — the catalog cannot "
                              "supply it for you")
        if "impact_class" in m and m["impact_class"] not in vocab["impact_class"]:
            errors.append(f"impact_class {m['impact_class']!r} is not in the vocabulary")
        if "detection" in m and m["detection"] not in vocab["detection"]:
            errors.append(f"detection {m['detection']!r} is not in the vocabulary")

    base = policy["archetypes"].get(m["archetype"]) if m["archetype"] != "custom" else None

    # ---- query hygiene ------------------------------------------------------
    query = m.get("query") or (base or {}).get("query", "")
    if m["archetype"] == "custom" and query:
        for env in m["env"]:
            if f"env:{env}" not in query and "__SCOPE__" not in query:
                errors.append(
                    f"query must be scoped to env:{env}. An unscoped query silently monitors "
                    "every environment, which is how a staging deploy pages production on-call")
        if m["service"] not in query and "__SCOPE__" not in query:
            errors.append(f"query must be scoped to service:{m['service']}, otherwise this "
                          "'service-specific' monitor overlaps the platform packs")
        for pattern in g["cardinality"]["forbidden_query_patterns"]:
            if pattern in query:
                errors.append(f"query contains the org-wide wildcard {pattern!r}")

    # ---- cardinality --------------------------------------------------------
    group_by = m.get("group_by", (base or {}).get("group_by", []))
    card = g["cardinality"]
    if len(group_by) > card["max_group_by_keys"]:
        errors.append(f"group_by has {len(group_by)} keys; the maximum is "
                      f"{card['max_group_by_keys']}")
    banned = sorted(set(group_by) & set(card["forbidden_group_keys"]))
    if banned:
        errors.append(
            f"group_by uses banned identity keys {banned}. Grouping by an identity key "
            "creates one alert per request/container/user and will page thousands of times")

    # ---- thresholds ---------------------------------------------------------
    th = m.get("thresholds", {})
    if th:
        if "critical" not in th:
            errors.append("thresholds.critical is required")
        for k, v in th.items():
            if str(v) == "auto" and base is None:
                errors.append(f"thresholds.{k}: `auto` needs a catalog archetype to inherit "
                              "from; `archetype: custom` must give explicit numbers")
            elif str(v) == "auto" and k not in base.get("thresholds", {}):
                errors.append(f"thresholds.{k}: `auto` requested but archetype "
                              f"{m['archetype']!r} defines no {k} threshold to inherit")
        num = {k: float(v) for k, v in th.items() if str(v) != "auto"}
        if base is not None and num:
            # Datadog requires monitor thresholds to match the numeric literal
            # inside the query. An inherited catalog query carries the
            # catalog's number, so overriding the threshold here would produce
            # a monitor the API rejects.
            for k, v in num.items():
                if v != base.get("thresholds", {}).get(k):
                    errors.append(
                        f"thresholds.{k}={v} overrides the value baked into archetype "
                        f"{m['archetype']!r}'s query. Datadog requires the two to match. "
                        "Use `archetype: custom` with your own explicit query, or propose "
                        "a change to the archetype so every service benefits")
        if "warning" in num and "critical" in num and query:
            if ">" in query and num["warning"] > num["critical"]:
                errors.append("warning must be BELOW critical for a `>` comparison — as "
                              "written the warning fires after the critical, which means "
                              "nobody ever sees it")
            if "<" in query and ">" not in query and num["warning"] < num["critical"]:
                errors.append("warning must be ABOVE critical for a `<` comparison")

    # ---- predictive-first ---------------------------------------------------
    predictive = m.get("predictive", {})
    detection = m.get("detection") or (base or {}).get("detection", "")
    if predictive.get("anomaly") and base is not None:
        variant = base.get("predictive_variant", m["archetype"])
        vdet = policy["archetypes"][variant]["detection"]
        if vdet not in ("anomaly", "seasonal_anomaly"):
            errors.append(
                f"predictive.anomaly: true but archetype {m['archetype']!r} resolves to "
                f"detection={vdet!r} and declares no anomaly variant. Ask for a variant in "
                "the catalog rather than mislabelling this monitor")
    if predictive.get("forecast") and detection != "forecast":
        errors.append(f"predictive.forecast: true but the resolved detection is {detection!r}")

    behavioral = any(s in str(query) for s in ("duration", "latency", "hits", "errors", "count"))
    uses_predictive = any(fn in str(query) for fn in PREDICTIVE_FUNCS)
    if behavioral and not uses_predictive and not m.get("justification"):
        errors.append(
            "fixed threshold on a behavioral signal requires a `justification`. This platform "
            "is predictive-first: a hard number on latency or error volume is only correct "
            "when the number itself is a contract (an SLA, a quota, a partner agreement)")

    # ---- priority discipline -------------------------------------------------
    if "priority" in m:
        if m["priority"] not in vocab["priority"]:
            errors.append(f"priority {m['priority']!r} must be one of P1..P4")
        elif m["priority"] in ("P1", "P2"):
            tier = services.get(m["service"], {}).get("tier", "tier2")
            band = policy["tiers"][tier]["alert_band"]
            if band != "critical":
                errors.append(
                    f"priority {m['priority']} requires a tier0/tier1 service; "
                    f"{m['service']!r} is {tier}. Raise the service tier through the "
                    "registry (a reviewed business decision) rather than raising one alert")

    # ---- notification profile ------------------------------------------------
    if "notification_profile" in m:
        if m["notification_profile"] not in policy["notification_profiles"]["notification_profiles"]:
            errors.append(f"notification_profile {m['notification_profile']!r} does not exist")

    # ---- duplicate detection -------------------------------------------------
    if base is not None and not m.get("justification"):
        errors.append(
            f"this manifest re-uses archetype {m['archetype']!r}, which ALREADY covers "
            f"{m['service']!r} through the platform packs. Add a `justification` explaining "
            "what the pack does not catch, or delete the file and rely on the baseline")

    return errors


def main() -> int:
    policy = oc.load_policy()
    services = oc.load_services()
    paths = sorted((oc.PLATFORM_DIR / "monitors").glob("*.yaml"))
    failed = False
    for p in paths:
        errs = validate(p, policy, services)
        print(f"[{'OK ' if not errs else 'FAIL'}] {p.relative_to(oc.REPO_ROOT)}")
        for e in errs:
            print(f"        - {e}")
        failed |= bool(errs)
    if not paths:
        print("no self-service manifests found")
    print(f"\nmanifest validation: {'FAIL' if failed else 'OK'} ({len(paths)} manifests)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
