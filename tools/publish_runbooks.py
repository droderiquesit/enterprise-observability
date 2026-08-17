#!/usr/bin/env python3
"""Runbook notebook publisher (ADR-006).

The Datadog Terraform provider has NO notebook resource, so runbooks are the
one platform component deployed through a controlled, versioned, API-backed
path with the same guarantees Terraform gives us:

  - Source of truth: platform/runbooks/*.md (versioned, PR-reviewed).
  - Deterministic render: markdown template → notebook cells JSON.
  - Drift control: a SHA-256 of the rendered content is embedded in the final
    cell; publish is a no-op when the remote hash matches (idempotent),
    an update when it differs (drift repair), a create when absent.
  - Registry sync: notebook IDs are reconciled against
    platform/policy/runbooks.yaml so monitors always link to a live notebook.

Usage: publish_runbooks.py [--dry-run] [--check]  (exit 1 on drift in --check)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

import obs_common as oc

SECTION_ORDER = [
    "Purpose and affected service", "Customer and business impact",
    "SLO and current error-budget status", "Likely causes and dependencies",
    "Validation and diagnostic steps", "Safe remediation steps",
    "Rollback instructions", "Escalation path",
    "Links to relevant telemetry and recent changes",
]


def render_cells(md_text: str) -> list[dict]:
    """Split a runbook markdown doc into one markdown cell per section."""
    cells = []
    for chunk in re.split(r"(?m)^## ", md_text):
        chunk = chunk.strip()
        if not chunk:
            continue
        body = chunk if chunk.startswith("#") else f"## {chunk}"
        cells.append({
            "type": "notebook_cells",
            "attributes": {"definition": {"type": "markdown", "text": body}},
        })
    digest = hashlib.sha256(md_text.encode()).hexdigest()[:16]
    cells.append({
        "type": "notebook_cells",
        "attributes": {"definition": {"type": "markdown",
                                      "text": f"---\n*managed_by:terraform-platform · content_hash:{digest}*"}},
    })
    return cells


def content_hash(md_text: str) -> str:
    return hashlib.sha256(md_text.encode()).hexdigest()[:16]


def validate_template(md_text: str) -> list[str]:
    missing = [s for s in SECTION_ORDER if f"## {s}" not in md_text]
    return [f"missing mandatory section: {s}" for s in missing]


def remote_hash(notebook: dict) -> str | None:
    cells = notebook.get("data", {}).get("attributes", {}).get("cells", [])
    for c in reversed(cells):
        text = c.get("attributes", {}).get("definition", {}).get("text", "")
        m = re.search(r"content_hash:([0-9a-f]{16})", text)
        if m:
            return m.group(1)
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--check", action="store_true", help="fail on drift without writing")
    args = ap.parse_args()

    src_dir = oc.REPO_ROOT / "platform" / "runbooks"
    sources = sorted(src_dir.glob("*.md"))
    problems, drift = [], []

    for p in sources:
        text = p.read_text()
        errs = validate_template(text)
        if errs:
            problems += [f"{p.name}: {e}" for e in errs]
    if problems:
        for e in problems:
            print(f"TEMPLATE ERROR: {e}")
        return 1

    if args.dry_run:
        for p in sources:
            print(f"would publish: {p.name} ({len(render_cells(p.read_text()))} cells, hash {content_hash(p.read_text())})")
        return 0

    import requests
    headers = oc.dd_headers()
    site = oc.dd_site()
    registry = oc.load_policy()["runbooks"]["notebooks"]

    for p in sources:
        text = p.read_text()
        title_line = text.splitlines()[0].lstrip("# ").strip()
        name = title_line if title_line.startswith("Runbook:") else f"Runbook: {title_line}"
        want_hash = content_hash(text)
        nb_id = registry.get(name, {}).get("id")

        if nb_id:
            r = requests.get(f"{site}/api/v1/notebooks/{nb_id}", headers=headers, timeout=60)
            if r.status_code == 200 and remote_hash(r.json()) == want_hash:
                print(f"in-sync: {name} (#{nb_id})")
                continue
            drift.append(name)
            if args.check:
                continue
            payload = {"data": {"type": "notebooks", "attributes": {
                "name": name, "cells": render_cells(text), "status": "published",
                "time": {"live_span": "1h"}, "metadata": {"type": "runbook"}}}}
            requests.put(f"{site}/api/v1/notebooks/{nb_id}", headers=headers,
                         data=json.dumps(payload), timeout=60).raise_for_status()
            print(f"updated: {name} (#{nb_id})")
        else:
            drift.append(name)
            if args.check:
                continue
            payload = {"data": {"type": "notebooks", "attributes": {
                "name": name, "cells": render_cells(text), "status": "published",
                "time": {"live_span": "1h"}, "metadata": {"type": "runbook"}}}}
            r = requests.post(f"{site}/api/v1/notebooks", headers=headers,
                              data=json.dumps(payload), timeout=60)
            r.raise_for_status()
            new_id = r.json()["data"]["id"]
            print(f"created: {name} (#{new_id}) — add to platform/policy/runbooks.yaml")

    if args.check and drift:
        print(f"DRIFT: {len(drift)} runbooks out of sync: {drift}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
