#!/usr/bin/env python3
"""ONE-TIME ORG RECONCILIATION — clear the way for a clean foundation apply.

Two generations of platform objects exist in the org with NO Terraform state
tracking them:

  1. The 2026-08-07 experiment: ~25 workflows tagged managed_by:terraform
     (they consume the org's entire workflow quota) and one orphaned SLO
     whose backing monitor was deleted.
  2. The 2026-08-17 partial foundation apply: teams, dashboards,
     notification rules, roles, service accounts, downtimes and 2 workflows
     created before the apply died on the workflow quota — and the runner
     was lost before state could be persisted (fixed in deploy.yml since).

Both sets are machine-generated from this repository and carry no history
worth importing; a clean apply recreates every current object. This script
retires them, and ONLY them, by exact identity:

  workflows            tag managed_by:terraform (both generations)
  teams                handle ∈ platform/policy/teams.yaml
  dashboards           title ∈ the foundation stack's generated titles
                       (the five hand-built legacy dashboards have different
                       titles and are NOT touched)
  notification rules   name starts with "route-" (module naming scheme)
  roles                name ∈ the five names in stacks/foundation/main.tf
  service accounts     the two svc-observability-* emails
  downtime schedules   scope ∈ the two catalog window scopes
  orphaned SLO         id eb41f0e7654d51278b49c811eb7771db (JSON exported
                       to the report before deletion — migration step M0)

NEVER touched: monitors (qa/stage are state-tracked and live), notebooks
(the publisher adopts/reports those), the five legacy dashboards, and
anything not matching the identities above.

Default is --dry-run. Pass --execute to delete. Requires DD_API_KEY/DD_APP_KEY.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

import requests
import yaml

import obs_common as oc

REPO = pathlib.Path(__file__).resolve().parent.parent
ORPHANED_SLO_ID = "eb41f0e7654d51278b49c811eb7771db"

ROLE_NAMES = {
    "Datadog Platform Admin", "Observability Engineer", "Engineering User",
    "Observability Read Only", "Security Engineer (scoped)",
}
SERVICE_ACCOUNT_EMAILS = {
    "svc-observability-terraform@acme.example",
    "svc-observability-coverage@acme.example",
}
DOWNTIME_SCOPES = {
    "env:prod AND team:data-engineering",
    "env:qa",
}
STATIC_DASHBOARD_TITLES = {
    "Alert Quality Scorecard",
    "Enterprise Overview — SLO Health & Platform Risk",
    "On-Call — Active Pages & Correlation",
    "Operations Overview — Infrastructure, Cloud, Data, Security, SRE",
}


def expected_identities():
    teams = yaml.safe_load((REPO / "platform/policy/teams.yaml").read_text())
    handles = set((teams.get("teams") or teams).keys())
    domains = yaml.safe_load((REPO / "platform/policy/domains.yaml").read_text())
    doms = domains.get("domains") or domains
    dash_titles = STATIC_DASHBOARD_TITLES | {
        f"Domain — {v['display']}" for v in doms.values()
    }
    return handles, dash_titles


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true",
                    help="actually delete; default is a dry-run report")
    args = ap.parse_args()
    verb = "DELETE" if args.execute else "would delete"

    headers = oc.dd_headers()
    site = oc.dd_site()
    handles, dash_titles = expected_identities()
    failures = 0

    def rm(url: str, label: str):
        nonlocal failures
        print(f"{verb}: {label}")
        if not args.execute:
            return
        r = requests.delete(url, headers=headers, timeout=60)
        if r.status_code not in (200, 202, 204):
            print(f"  ERROR {r.status_code}: {r.text[:200]}")
            failures += 1

    def fetch(path: str, params: dict | None = None):
        """GET that degrades to None on any non-200 so one unavailable API
        (plan differences, path changes) never aborts the whole pass."""
        try:
            r = requests.get(f"{site}{path}", headers=headers, timeout=60,
                             params=params)
        except requests.RequestException as exc:
            print(f"-- {path}: request failed ({exc}) — skipping section")
            return None
        if r.status_code != 200:
            print(f"-- {path}: HTTP {r.status_code} — skipping section")
            return None
        return r.json()

    # --- workflows (both generations; quota is the blocking constraint) -----
    body = fetch("/api/v2/workflows")
    if body is not None:
        n = 0
        for wf in body.get("data", []):
            attrs = wf.get("attributes", {})
            if "managed_by:terraform" in (attrs.get("tags") or []):
                n += 1
                rm(f"{site}/api/v2/workflows/{wf['id']}",
                   f"workflow {wf['id']} ({attrs.get('name')})")
        print(f"-- workflows matched: {n}")

    # --- teams ---------------------------------------------------------------
    body = fetch("/api/v2/team", {"page[size]": 100})
    if body is not None:
        n = 0
        for t in body.get("data", []):
            h = t.get("attributes", {}).get("handle")
            if h in handles:
                n += 1
                rm(f"{site}/api/v2/team/{t['id']}", f"team {h}")
        print(f"-- teams matched: {n}")

    # --- dashboards (generated titles only; legacy five differ) -------------
    body = fetch("/api/v1/dashboard")
    if body is not None:
        n = 0
        for d in body.get("dashboards", []):
            if d.get("title") in dash_titles:
                n += 1
                rm(f"{site}/api/v1/dashboard/{d['id']}",
                   f"dashboard {d['id']} ({d['title']})")
        print(f"-- dashboards matched: {n}")

    # --- monitor notification rules (module names them route-*) -------------
    rules_path = "/api/v2/monitor-notification-rules"
    body = fetch(rules_path)
    if body is None:
        rules_path = "/api/v2/monitor/notification-rules"   # alternate spelling
        body = fetch(rules_path)
    if body is not None:
        n = 0
        for rule in body.get("data", []):
            name = rule.get("attributes", {}).get("name", "")
            if name.startswith("route-"):
                n += 1
                rm(f"{site}{rules_path}/{rule['id']}", f"notification rule {name}")
        print(f"-- notification rules matched: {n}")

    # --- roles (exact catalog names; Datadog's default roles never match) ---
    body = fetch("/api/v2/roles", {"page[size]": 100})
    if body is not None:
        n = 0
        for role in body.get("data", []):
            name = role.get("attributes", {}).get("name")
            if name in ROLE_NAMES:
                n += 1
                rm(f"{site}/api/v2/roles/{role['id']}", f"role {name}")
        print(f"-- roles matched: {n}")

    # --- service accounts ----------------------------------------------------
    body = fetch("/api/v2/users", {"page[size]": 100, "filter[status]": "Active"})
    if body is not None:
        n = 0
        for u in body.get("data", []):
            attrs = u.get("attributes", {})
            if attrs.get("service_account") and attrs.get("email") in SERVICE_ACCOUNT_EMAILS:
                n += 1
                rm(f"{site}/api/v2/users/{u['id']}",
                   f"service account {attrs.get('email')}")
        print(f"-- service accounts matched: {n}")

    # --- downtime schedules --------------------------------------------------
    body = fetch("/api/v2/downtime", {"page[limit]": 100})
    if body is not None:
        n = 0
        for dt in body.get("data", []):
            scope = (dt.get("attributes", {}).get("scope") or "")
            if scope in DOWNTIME_SCOPES:
                n += 1
                rm(f"{site}/api/v2/downtime/{dt['id']}", f"downtime scope={scope!r}")
        print(f"-- downtimes matched: {n}")

    # --- the orphaned legacy SLO (M0: export, then delete) ------------------
    resp = requests.get(f"{site}/api/v1/slo/{ORPHANED_SLO_ID}", headers=headers,
                        timeout=60)
    if resp.status_code == 200:
        print("M0 export of orphaned SLO follows (archive this run's log):")
        print(json.dumps(resp.json(), indent=2)[:4000])
        rm(f"{site}/api/v1/slo/{ORPHANED_SLO_ID}",
           f"orphaned SLO {ORPHANED_SLO_ID} (backing monitor deleted 2026-08)")
    else:
        print(f"-- orphaned SLO: not found ({resp.status_code}) — already gone")

    print(f"\nreconcile: {'EXECUTED' if args.execute else 'dry-run'}, "
          f"{failures} delete failures")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
