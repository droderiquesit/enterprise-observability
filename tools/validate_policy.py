#!/usr/bin/env python3
"""Policy lint: internal consistency of platform/policy/*.yaml.

Run in CI before terraform plan. Checks:
  - archetype references (slo_id, runbook, workflow) resolve to registries
  - cardinality guardrails on every archetype
  - controlled vocabularies (domains, severities)
  - exception hygiene: required fields + expiry (expired = hard failure)
  - fixed-threshold archetypes on behavioral signals carry a rationale
"""
from __future__ import annotations

import datetime as dt
import sys

import obs_common as oc

PREDICTIVE = ("anomalies(", "forecast(", "outliers(", "pct_change(")
ABSOLUTE_OK_CLASSES = {"compliance_absolute", "audit_continuity", "availability",
                       "errors", "telemetry_health", "security_control",
                       "security_telemetry_gap", "saturation"}


def lint() -> list[str]:
    policy = oc.load_policy()
    g = policy["global"]
    errors: list[str] = []

    for aid, a in policy["archetypes"].items():
        where = f"archetype {aid}"
        if a["slo_id"] not in policy["slos"]:
            errors.append(f"{where}: slo_id {a['slo_id']!r} not in slos.yaml")
        if a["runbook"] not in policy["runbooks"]["notebooks"]:
            errors.append(f"{where}: runbook {a['runbook']!r} not in runbooks.yaml")
        if a["workflow"] not in policy["workflows"]:
            errors.append(f"{where}: workflow {a['workflow']!r} not in workflows.yaml")
        if a["domain"] not in g["tag_vocabulary"]["domain"]:
            errors.append(f"{where}: domain {a['domain']!r} invalid")

        group_by = a.get("group_by", [])
        if len(group_by) > g["cardinality"]["max_group_by_keys"]:
            errors.append(f"{where}: group_by exceeds {g['cardinality']['max_group_by_keys']} keys")
        banned = set(group_by) & set(g["cardinality"]["forbidden_group_keys"])
        if banned:
            errors.append(f"{where}: forbidden group keys {sorted(banned)}")

        if a["detection"] == "threshold" and a["class"] not in ABSOLUTE_OK_CLASSES:
            if not a.get("rationale_fixed_threshold"):
                errors.append(
                    f"{where}: fixed threshold on class {a['class']!r} requires "
                    "rationale_fixed_threshold (predictive-first policy)"
                )
        if a["detection"] != "threshold" and not any(p in a["query"] for p in PREDICTIVE) \
                and a["monitor_type"] not in ("service check", "event-v2 alert"):
            errors.append(f"{where}: detection={a['detection']} but query has no predictive function")

    today = dt.date.today()
    for e in policy["exceptions"]:
        eid = e.get("id", "<missing id>")
        for f in ("id", "scope", "control", "value", "justification", "owner",
                  "approved_by", "approved_on", "expires"):
            if f not in e:
                errors.append(f"exception {eid}: missing field {f}")
        expires = e.get("expires")
        if isinstance(expires, str):
            expires = dt.date.fromisoformat(expires)
        if expires and expires < today:
            errors.append(f"exception {eid}: EXPIRED on {expires} — renew or remove")

    for slo_id, s in policy["slos"].items():
        if s["team"] not in policy["teams"]["teams"]:
            errors.append(f"slo {slo_id}: team {s['team']!r} not registered")
        for arch in s.get("member_archetypes", []):
            if arch not in policy["archetypes"]:
                errors.append(f"slo {slo_id}: member_archetype {arch!r} unknown")

    return errors


def main() -> int:
    errors = lint()
    for e in errors:
        print(f"POLICY VIOLATION: {e}")
    print(f"policy lint: {'FAIL' if errors else 'OK'} ({len(errors)} violations)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
