#!/usr/bin/env python3
"""Regenerate tests/fixtures/monitors_planned.json from an offline plan.

The coverage-report tests grade the monitors this repository would REALLY
deploy, not a hand-written approximation — that promise only holds while the
fixture tracks the plan. This records the transformation so the fixture can
never again go stale without a documented refresh path:

    terraform -chdir=stacks/coverage plan -out=plan.out -var datadog_validate=false
    terraform -chdir=stacks/coverage show -json plan.out > plan.json
    python tools/refresh_fixtures.py plan.json

The fixture keeps only the fields the checks read (id, name, type, query,
message, tags), with stable sequential ids in address order.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import obs_common as oc

FIXTURE = oc.REPO_ROOT / "tests" / "fixtures" / "monitors_planned.json"


def monitors_from_plan(plan: dict) -> list[dict]:
    rows = []
    for rc in sorted(plan.get("resource_changes", []), key=lambda rc: rc["address"]):
        if rc["type"] != "datadog_monitor":
            continue
        a = rc["change"]["after"] or {}
        rows.append({
            "name": a.get("name"),
            "type": a.get("type"),
            "query": a.get("query"),          # null for burn monitors pre-apply
            "message": a.get("message") or "",
            "tags": a.get("tags") or [],
        })
    return [{"id": i + 1, **row} for i, row in enumerate(rows)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("plan_json", type=Path, help="terraform show -json output")
    args = ap.parse_args()

    monitors = monitors_from_plan(json.loads(args.plan_json.read_text()))
    if not monitors:
        print("refresh_fixtures: plan contains no datadog_monitor resources — "
              "refusing to write an empty fixture")
        return 1
    FIXTURE.write_text(json.dumps(monitors, indent=1, sort_keys=True) + "\n")
    print(f"fixtures: wrote {len(monitors)} planned monitors -> {FIXTURE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
