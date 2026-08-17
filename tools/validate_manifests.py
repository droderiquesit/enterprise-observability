#!/usr/bin/env python3
"""CI validation for self-service monitor requests (platform/requests/*.yaml).

Rejects any manifest violating naming, tagging, ownership, SLO, routing,
runbook, workflow, or cardinality standards — BEFORE Terraform ever runs.
Exit code 1 on any violation; prints a per-manifest verdict.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

import obs_common as oc

REQUIRED_FIELDS = [
    "kind", "title", "service", "env", "domain", "team", "criticality",
    "severity_class", "monitor_type", "query", "thresholds", "slo_id",
    "runbook", "workflow", "summary",
]
MONITOR_TYPES = {"query alert", "metric alert", "service check", "event-v2 alert", "log alert"}
SEVERITY_CLASSES = {"page_fast", "page", "ticket"}


def validate_manifest(path: Path, policy: dict) -> list[str]:
    errors: list[str] = []
    try:
        doc = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        return [f"unparseable YAML: {exc}"]
    if not isinstance(doc, dict):
        return ["manifest must be a YAML mapping"]

    for f in REQUIRED_FIELDS:
        if f not in doc:
            errors.append(f"missing required field: {f}")
    if errors:
        return errors

    g = policy["global"]
    if doc["kind"] != "monitor-request":
        errors.append("kind must be monitor-request")
    if doc["env"] not in g["tag_vocabulary"]["env"]:
        errors.append(f"env {doc['env']!r} not in controlled vocabulary")
    if doc["criticality"] not in g["tag_vocabulary"]["criticality"]:
        errors.append(f"criticality {doc['criticality']!r} not in controlled vocabulary")
    if doc["domain"] not in g["tag_vocabulary"]["domain"]:
        errors.append(f"domain {doc['domain']!r} not in controlled vocabulary")
    if doc["team"] not in policy["teams"]["teams"]:
        errors.append(f"team {doc['team']!r} is not a registered team (teams.yaml)")
    if doc["severity_class"] not in SEVERITY_CLASSES:
        errors.append(f"severity_class must be one of {sorted(SEVERITY_CLASSES)}")
    if doc["monitor_type"] not in MONITOR_TYPES:
        errors.append(f"monitor_type {doc['monitor_type']!r} unsupported for self-service")

    # SLO association must reference the platform catalog — no orphan SLOs.
    if doc["slo_id"] not in policy["slos"]:
        errors.append(f"slo_id {doc['slo_id']!r} not in platform SLO catalog (slos.yaml)")

    # Runbook and workflow must exist in the registries.
    if doc["runbook"] not in policy["runbooks"]["notebooks"]:
        errors.append(f"runbook {doc['runbook']!r} not in runbook registry (runbooks.yaml)")
    if doc["workflow"] not in policy["workflows"]:
        errors.append(f"workflow {doc['workflow']!r} not in workflow registry (workflows.yaml)")

    # Cardinality guardrails.
    group_by = doc.get("group_by", [])
    card = g["cardinality"]
    if len(group_by) > card["max_group_by_keys"]:
        errors.append(f"group_by exceeds max {card['max_group_by_keys']} keys")
    banned = set(group_by) & set(card["forbidden_group_keys"])
    if banned:
        errors.append(f"group_by uses forbidden high-cardinality keys: {sorted(banned)}")

    # Query hygiene: must scope to the declared env and service (prevents
    # org-wide accidental scope + duplicate/overlap of platform baselines).
    if f"env:{doc['env']}" not in doc["query"]:
        errors.append("query must be scoped to the declared env (env:<env> filter missing)")
    if doc["monitor_type"] != "service check" and doc["service"] not in doc["query"]:
        errors.append("query must be scoped to the declared service")

    # Thresholds sanity.
    th = doc["thresholds"]
    if not isinstance(th, dict) or "critical" not in th:
        errors.append("thresholds.critical is required")
    if isinstance(th, dict) and "warning" in th and "critical" in th:
        # direction-aware check: warning must be on the safe side of critical
        if ">" in doc["query"] and float(th["warning"]) > float(th["critical"]):
            errors.append("warning threshold must be below critical for '>' comparisons")
        if "<" in doc["query"] and ">" not in doc["query"] and float(th["warning"]) < float(th["critical"]):
            errors.append("warning threshold must be above critical for '<' comparisons")

    # Fixed-threshold monitors on behavioral signals need a justification —
    # the platform is predictive-first.
    behavioral = any(s in doc["query"] for s in ("duration", "latency", "hits", "errors"))
    predictive = any(s in doc["query"] for s in ("anomalies(", "forecast(", "outliers(", "pct_change("))
    if behavioral and not predictive and not doc.get("justification"):
        errors.append("fixed threshold on a behavioral signal requires a `justification` field")

    # Naming: title must be a sentence, not an ID.
    if not re.match(r"^[A-Z0-9].{10,120}$", doc["title"]):
        errors.append("title must be a descriptive sentence (10–120 chars, capitalized)")

    return errors


def main() -> int:
    policy = oc.load_policy()
    req_dir = oc.REPO_ROOT / "platform" / "requests"
    paths = sorted(req_dir.glob("*.yaml"))
    failed = False
    for p in paths:
        errs = validate_manifest(p, policy)
        status = "OK " if not errs else "FAIL"
        print(f"[{status}] {p.relative_to(oc.REPO_ROOT)}")
        for e in errs:
            print(f"       - {e}")
        failed |= bool(errs)
    if not paths:
        print("no self-service manifests found")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
