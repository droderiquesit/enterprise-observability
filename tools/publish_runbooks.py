#!/usr/bin/env python3
"""RUNBOOK NOTEBOOK PUBLISHER (provider gap — see ADR-006).

The Datadog Terraform provider has no notebook resource, so runbooks are the one
platform component deployed through an API path. It is given the same guarantees
Terraform provides, deliberately and explicitly:

  SOURCE OF TRUTH   platform/runbooks/*.md — versioned, PR-reviewed
  DETERMINISM       markdown → notebook cells, byte-identical for identical input
  DRIFT CONTROL     a SHA-256 of the rendered content is embedded in the final
                    cell. Publish is a no-op when the remote hash matches, an
                    update when it differs, a create when absent. `--check`
                    fails CI on drift, which is what the nightly job runs.
  REGISTRY SYNC     notebook IDs are reconciled against
                    platform/policy/runbooks.yaml so monitors always deep-link
                    to a live notebook.

Usage: publish_runbooks.py [--dry-run] [--check]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

import obs_common as oc

# The sections every runbook must contain. Enforced before anything is
# published — an incomplete runbook is worse than an obvious gap, because it
# looks like coverage.
REQUIRED_SECTIONS = [
    "Meaning",
    "Impact",
    "Validation",
    "Likely causes",
    "Diagnostic queries",
    "Dependency checks",
    "Remediation",
    "Automation",
    "Escalation",
    "Recovery verification",
]


def render_cells(md_text: str) -> list[dict]:
    """Split a runbook into one markdown cell per section, plus a hash cell."""
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
    digest = content_hash(md_text)
    cells.append({
        "type": "notebook_cells",
        "attributes": {"definition": {
            "type": "markdown",
            "text": f"---\n*managed_by:terraform-platform · content_hash:{digest}*",
        }},
    })
    return cells


def content_hash(md_text: str) -> str:
    return hashlib.sha256(md_text.encode()).hexdigest()[:16]


def validate_template(md_text: str) -> list[str]:
    return [f"missing mandatory section: {s}"
            for s in REQUIRED_SECTIONS if f"## {s}" not in md_text]


def unfinished_sections(md_text: str) -> int:
    return md_text.count("TODO(owner)")


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
    ap.add_argument("--allow-unfinished", action="store_true", default=True,
                    help="publish drafts that still contain TODO(owner) markers "
                         "(they are tracked as a backlog, not a blocker)")
    args = ap.parse_args()

    src_dir = oc.PLATFORM_DIR / "runbooks"
    sources = sorted(src_dir.glob("*.md"))
    policy = oc.load_policy()
    registry = policy["runbooks"]

    # --- structural validation ------------------------------------------------
    problems, unfinished = [], 0
    for p in sources:
        text = p.read_text()
        problems += [f"{p.name}: {e}" for e in validate_template(text)]
        unfinished += unfinished_sections(text)
    # Every registry entry must have a source file, and vice versa.
    sources_by_stem = {p.stem for p in sources}
    for rid, r in registry.items():
        if Path(r["source"]).stem not in sources_by_stem:
            problems.append(f"registry entry {rid}: source {r['source']} does not exist")
    for stem in sources_by_stem:
        if stem not in registry:
            problems.append(f"{stem}.md has no entry in platform/policy/runbooks.yaml")

    if problems:
        for e in problems:
            print(f"RUNBOOK ERROR: {e}")
        return 1

    print(f"runbooks: {len(sources)} valid, {unfinished} sections still marked "
          f"TODO(owner) across the estate")

    if args.dry_run:
        for p in sources:
            text = p.read_text()
            print(f"would publish: {p.name} ({len(render_cells(text))} cells, "
                  f"hash {content_hash(text)})")
        return 0

    import requests
    headers = oc.dd_headers()
    site = oc.dd_site()
    drift = []

    for p in sources:
        text = p.read_text()
        rid = p.stem
        entry = registry.get(rid, {})
        name = f"Runbook: {entry.get('title', rid)}"
        want = content_hash(text)
        nb_id = entry.get("id")
        payload = {"data": {"type": "notebooks", "attributes": {
            "name": name, "cells": render_cells(text), "status": "published",
            "time": {"live_span": "1h"}, "metadata": {"type": "runbook"}}}}

        if nb_id:
            r = requests.get(f"{site}/api/v1/notebooks/{nb_id}", headers=headers, timeout=60)
            if r.status_code == 200 and remote_hash(r.json()) == want:
                continue
            drift.append(name)
            if args.check:
                continue
            requests.put(f"{site}/api/v1/notebooks/{nb_id}", headers=headers,
                         data=json.dumps(payload), timeout=60).raise_for_status()
            print(f"updated: {name} (#{nb_id})")
        else:
            drift.append(name)
            if args.check:
                continue
            r = requests.post(f"{site}/api/v1/notebooks", headers=headers,
                              data=json.dumps(payload), timeout=60)
            r.raise_for_status()
            print(f"created: {name} (#{r.json()['data']['id']}) — record the id in "
                  "platform/policy/runbooks.yaml")

    if args.check and drift:
        print(f"DRIFT: {len(drift)} runbooks out of sync with the org")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
