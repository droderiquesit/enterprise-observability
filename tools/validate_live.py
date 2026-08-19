#!/usr/bin/env python3
"""LIVE MONITOR VALIDATION against the Datadog monitor-validation API.

The Terraform provider validates monitors during plan, but it stops early and
reports them one at a time, which makes fixing a catalog-wide problem a slow
loop. This submits EVERY planned monitor to `/api/v1/monitor/validate`
concurrently and reports the complete list of defects grouped by cause.

It is read-only: the validation endpoint never creates anything.

    terraform -chdir=stacks/coverage plan -out=plan.out -var datadog_validate=false
    terraform -chdir=stacks/coverage show -json plan.out > plan.json
    python tools/validate_live.py plan.json

Exit code 1 if any monitor is rejected, so it can gate CI on its own.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import obs_common as oc


def monitors_from_plan(plan: dict) -> list[dict]:
    out = []
    for rc in plan.get("resource_changes", []):
        if rc["type"] != "datadog_monitor":
            continue
        a = rc["change"]["after"] or {}
        th = (a.get("monitor_thresholds") or [{}])[0]
        body = {
            "name": a.get("name"),
            "type": a.get("type"),
            "query": a.get("query"),
            "message": a.get("message") or "",
            "tags": a.get("tags") or [],
            "priority": a.get("priority"),
            "options": {
                k: v for k, v in {
                    "thresholds": {k2: v2 for k2, v2 in th.items() if v2 is not None} or None,
                    "notify_no_data": a.get("notify_no_data"),
                    "no_data_timeframe": a.get("no_data_timeframe"),
                    "evaluation_delay": a.get("evaluation_delay"),
                    "new_group_delay": a.get("new_group_delay"),
                    "renotify_interval": a.get("renotify_interval"),
                    "require_full_window": a.get("require_full_window"),
                    # Datadog bounds timeout_h to 0-24 and enforces it HERE, at
                    # validate. Leaving it out of the payload is what let an
                    # out-of-range auto-resolve window pass a green pull request
                    # and fail the deploy's plan instead.
                    "timeout_h": a.get("timeout_h"),
                    "include_tags": a.get("include_tags"),
                    "notify_audit": a.get("notify_audit"),
                }.items() if v is not None
            },
        }
        # Burn-rate queries embed an SLO id that is unknown until the SLO is
        # created, so they are genuinely unvalidatable before apply. Report them
        # as skipped rather than as failures — the provider validates them at
        # apply time, and the post-deploy idempotency plan catches anything that
        # slipped through.
        if not body["query"]:
            out.append({"address": rc["address"], "body": body, "skip": True})
        else:
            out.append({"address": rc["address"], "body": body})
    return out


def validate_one(session, site, headers, item):
    r = session.post(f"{site}/api/v1/monitor/validate", headers=headers,
                     data=json.dumps(item["body"]), timeout=60)
    if r.status_code in (200, 204):
        return None
    try:
        errs = r.json().get("errors", [r.text])
    except Exception:
        errs = [r.text[:300]]
    return {"address": item["address"], "name": item["body"]["name"],
            "status": r.status_code, "errors": errs}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("plan_json", type=Path, help="terraform show -json output")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    import requests

    plan = json.loads(args.plan_json.read_text())
    all_items = monitors_from_plan(plan)
    skipped = [i for i in all_items if i.get("skip")]
    items = [i for i in all_items if not i.get("skip")]
    headers = oc.dd_headers()
    site = oc.dd_site()

    session = requests.Session()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(lambda i: validate_one(session, site, headers, i), items))

    failures = [r for r in results if r]
    print(f"live validation: {len(items) - len(failures)}/{len(items)} monitors valid"
          + (f" ({len(skipped)} skipped — query known only after apply)" if skipped else ""))

    if failures:
        grouped = defaultdict(list)
        for f in failures:
            grouped["; ".join(f["errors"])].append(f["address"])
        print(f"\n{len(failures)} rejected, {len(grouped)} distinct causes:\n")
        for cause, addrs in sorted(grouped.items(), key=lambda kv: -len(kv[1])):
            print(f"[{len(addrs)}] {cause}")
            for a in sorted(addrs)[:6]:
                print(f"      {a}")
            if len(addrs) > 6:
                print(f"      … and {len(addrs) - 6} more")
            print()
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
