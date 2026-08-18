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


def fetch_remote_runbooks(site: str, headers: dict) -> dict[str, list[dict]]:
    """All runbook-type notebooks in the org, keyed by exact name.

    The org can contain notebooks published before this registry existed
    (same "Runbook: <title>" convention, no id recorded here). Publishing
    without looking would create same-name duplicates; instead, an exact
    name match is adopted and updated in place.
    """
    by_name: dict[str, list[dict]] = {}
    start, count = 0, 100
    while True:
        r = oc.dd_request("GET", f"{site}/api/v1/notebooks", headers=headers,
                          params={"start": start, "count": count,
                                  "include_cells": "false", "type": "runbook"})
        r.raise_for_status()
        page = r.json().get("data", [])
        for nb in page:
            attrs = nb.get("attributes", {})
            if (attrs.get("metadata") or {}).get("type") != "runbook":
                continue
            by_name.setdefault(attrs.get("name", ""), []).append(
                {"id": nb["id"], "modified": attrs.get("modified", "")})
        if len(page) < count:
            return by_name
        start += count


def write_registry_ids(assigned: dict[str, int]) -> int:
    """Record published notebook ids in runbooks.yaml without disturbing
    comments or formatting: insert/replace the `id:` line of each entry."""
    path = oc.PLATFORM_DIR / "policy" / "runbooks.yaml"
    lines = path.read_text().splitlines(keepends=True)
    out, current, done = [], None, set()
    for line in lines:
        m = re.match(r"^  ([a-z0-9-]+):\s*$", line)
        if m:
            current = m.group(1)
        if current in assigned and re.match(r"^    id:", line):
            continue  # replaced by the line inserted after source:
        out.append(line)
        if current in assigned and current not in done \
                and re.match(r"^    source:", line):
            out.append(f"    id: {assigned[current]}\n")
            done.add(current)
    path.write_text("".join(out))
    return len(done)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--check", action="store_true", help="fail on drift without writing")
    ap.add_argument("--write-registry", action="store_true",
                    help="record created/adopted notebook ids back into "
                         "platform/policy/runbooks.yaml (comment-preserving)")
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

    headers = oc.dd_headers()
    site = oc.dd_site()
    remote = fetch_remote_runbooks(site, headers)
    drift, assigned = [], {}
    target_names = set()

    for p in sources:
        text = p.read_text()
        rid = p.stem
        entry = registry.get(rid, {})
        name = f"Runbook: {entry.get('title', rid)}"
        target_names.add(name)
        want = content_hash(text)
        nb_id = entry.get("id")
        payload = {"data": {"type": "notebooks", "attributes": {
            "name": name, "cells": render_cells(text), "status": "published",
            "time": {"live_span": "1h"}, "metadata": {"type": "runbook"}}}}

        # Adopt a pre-existing same-name notebook instead of creating a
        # duplicate: newest wins, the rest are reported as stale below.
        adopted = False
        if not nb_id and name in remote:
            nb_id = max(remote[name], key=lambda n: n["modified"])["id"]
            adopted = True

        if nb_id:
            r = oc.dd_request("GET", f"{site}/api/v1/notebooks/{nb_id}",
                              headers=headers)
            if r.status_code == 200 and remote_hash(r.json()) == want:
                if adopted:
                    assigned[rid] = int(nb_id)
                continue
            drift.append(name)
            if args.check:
                continue
            oc.dd_request("PUT", f"{site}/api/v1/notebooks/{nb_id}",
                          headers=headers, data=json.dumps(payload)).raise_for_status()
            assigned[rid] = int(nb_id)
            print(f"{'adopted' if adopted else 'updated'}: {name} (#{nb_id})")
        else:
            drift.append(name)
            if args.check:
                continue
            r = oc.dd_request("POST", f"{site}/api/v1/notebooks",
                              headers=headers, data=json.dumps(payload))
            r.raise_for_status()
            assigned[rid] = int(r.json()["data"]["id"])
            print(f"created: {name} (#{assigned[rid]})")

    # Stale = runbook-type notebooks the registry does not claim. Reported
    # for deliberate retirement (migration M4) — NEVER deleted from here.
    stale = sorted(n["id"] for name, nbs in remote.items()
                   for n in nbs if name not in target_names)
    extra_dupes = sorted(n["id"] for name, nbs in remote.items() if name in target_names
                         for n in sorted(nbs, key=lambda n: n["modified"])[:-1])
    if stale or extra_dupes:
        print(f"stale runbook notebooks (retire via migration checklist, not "
              f"deleted here): {len(stale)} unclaimed, {len(extra_dupes)} "
              f"superseded duplicates — ids {', '.join(map(str, stale + extra_dupes))}")

    if args.write_registry and assigned and not args.check:
        n = write_registry_ids(assigned)
        print(f"registry: recorded {n} notebook ids in platform/policy/runbooks.yaml")
    elif assigned and not args.check:
        missing = [r for r in assigned if not registry.get(r, {}).get("id")]
        if missing:
            print(f"note: {len(missing)} ids not yet in runbooks.yaml — re-run "
                  "with --write-registry to record them")

    if args.check and drift:
        print(f"DRIFT: {len(drift)} runbooks out of sync with the org")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
