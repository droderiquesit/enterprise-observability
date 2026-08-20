#!/usr/bin/env python3
"""CATALOG AND NOTEBOOK RECONCILIATION (§6) — what exists that nothing owns.

The gap this closes. Coverage checks ask "is everything we declared deployed?".
Nothing asked the mirror-image question: "is everything deployed something we
declared?". An org accumulates catalog entries and runbooks from pilots, from
superseded repositories and from vendor agents, and every one of them looks
exactly like a real one in the UI — same list, same shape, same authority. A
catalog you cannot trust to be the estate is not a catalog, it is a directory.

WHAT COUNTS AS MANAGED

  Catalog entity   its name is a file in platform/entities/ (or the superseded
                   platform/services/, still read while a branch might use it).

  Notebook         its id is recorded in platform/policy/runbooks.yaml, OR its
                   name matches the "Runbook: <title>" of a registered runbook.

The name fallback is not belt-and-braces, it is load-bearing. publish_runbooks
writes ids into runbooks.yaml IN THE CI CHECKOUT, which is then discarded, so
the committed registry runs behind production by however many runbooks were
added since the last time someone committed it back. Deleting "every notebook
whose id is not in the registry" would therefore delete the newest runbooks —
the ones published minutes earlier by the very deploy that created them. The
name match is what makes this tool safe to run at any point in that cycle, and
publish_runbooks already adopts by name for the same reason.

SAFETY

  * Dry run by default. `--delete` is required to remove anything, and it is
    refused unless the managed set is non-empty — an empty managed set means
    the registry failed to load, and "delete everything" is the last thing a
    reconciler should do when it cannot see what it is protecting.
  * `--max-delete` caps a single run. A reconciler that deletes 300 objects
    because a path changed is worse than the drift it was fixing.
  * Deletion is per-object with per-object errors collected, so one 409 does
    not abandon the rest.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import obs_common as oc                      # noqa: E402

# Auto-created by Datadog itself from CI Visibility / integration traffic. They
# are not catalog entries anyone authored and they come straight back, so
# reporting them as drift would train people to ignore this report.
AUTO_CREATED_SERVICES = {"github-actions"}


# -----------------------------------------------------------------------------
# what the platform declares
# -----------------------------------------------------------------------------
def managed_entities() -> set[str]:
    names = set(oc.load_entities())
    names |= {f.stem for f in (oc.PLATFORM_DIR / "services").glob("*.yaml")}
    return names


def managed_notebooks() -> tuple[set[str], set[str]]:
    """(ids, names) that this platform owns. See the module docstring on why
    both are needed rather than ids alone."""
    reg = oc.load_policy()["runbooks"]
    ids = {str(r["id"]) for r in reg.values() if r.get("id")}
    names = {f"Runbook: {r.get('title', rid)}" for rid, r in reg.items()}
    return ids, names


# -----------------------------------------------------------------------------
# what the org actually has
# -----------------------------------------------------------------------------
def live_services(site: str, headers: dict) -> list[dict]:
    out, page_number = [], 0
    while True:
        r = oc.dd_request("GET", f"{site}/api/v2/services/definitions",
                          headers=headers,
                          params={"page[size]": 100, "page[number]": page_number})
        r.raise_for_status()
        batch = r.json().get("data", [])
        for svc in batch:
            schema = svc.get("attributes", {}).get("schema", {})
            name = schema.get("dd-service") or svc.get("id")
            links = schema.get("links") or []
            out.append({
                "name": name,
                "team": schema.get("team"),
                "description": schema.get("description", ""),
                # The link set is the evidence of provenance: an entry written
                # by another repository points its "Service registry entry"
                # link at that repository, which is how a foreign entry is
                # identified without guessing from the name.
                "links": [l.get("url", "") for l in links],
            })
        if len(batch) < 100:
            return out
        page_number += 1


def live_notebooks(site: str, headers: dict) -> list[dict]:
    out, start, count = [], 0, 100
    while True:
        r = oc.dd_request("GET", f"{site}/api/v1/notebooks", headers=headers,
                          params={"start": start, "count": count,
                                  "include_cells": "false", "type": "runbook"})
        r.raise_for_status()
        page = r.json().get("data", [])
        for nb in page:
            attrs = nb.get("attributes", {})
            out.append({
                "id": str(nb["id"]),
                "name": attrs.get("name", ""),
                "author": (attrs.get("author") or {}).get("handle", ""),
                "modified": attrs.get("modified", ""),
            })
        if len(page) < count:
            return out
        start += count


# -----------------------------------------------------------------------------
# the diff
# -----------------------------------------------------------------------------
def reconcile(services: list[dict], notebooks: list[dict]) -> dict:
    ents = managed_entities()
    nb_ids, nb_names = managed_notebooks()
    own_repo = oc.load_policy()["global"]["org"]["repo"]

    svc_rows = []
    for s in services:
        if s["name"] in ents:
            verdict, why = "managed", "registered in platform/entities/"
        elif s["name"] in AUTO_CREATED_SERVICES:
            verdict, why = "auto_created", "created by Datadog; deleting it does not stick"
        else:
            foreign = [u for u in s["links"] if "github.com/" in u
                       and own_repo not in u]
            why = (f"no entry in platform/entities/; registry link points at "
                   f"{foreign[0]}" if foreign else "no entry in platform/entities/")
            verdict = "unmanaged"
        svc_rows.append({**s, "verdict": verdict, "reason": why})

    nb_rows = []
    for n in notebooks:
        if n["id"] in nb_ids:
            verdict, why = "managed", "id recorded in runbooks.yaml"
        elif n["name"] in nb_names:
            # See the module docstring: this is the case that makes the tool
            # safe to run between a publish and a registry commit.
            verdict, why = "managed_by_name", (
                "name matches a registered runbook; its id is not committed yet "
                "(publish_runbooks writes the registry in the CI checkout, which "
                "is discarded)")
        else:
            verdict, why = "unmanaged", f"not in runbooks.yaml; author {n['author'] or 'unknown'}"
        nb_rows.append({**n, "verdict": verdict, "reason": why})

    def count(rows, v):
        return sum(1 for r in rows if r["verdict"] == v)

    return {
        "summary": {
            "services_live": len(svc_rows),
            "services_managed": count(svc_rows, "managed"),
            "services_unmanaged": count(svc_rows, "unmanaged"),
            "services_auto_created": count(svc_rows, "auto_created"),
            "notebooks_live": len(nb_rows),
            "notebooks_managed": count(nb_rows, "managed") + count(nb_rows, "managed_by_name"),
            "notebooks_unmanaged": count(nb_rows, "unmanaged"),
            # The registry-drift measure, surfaced rather than silently absorbed
            # by the name fallback: runbooks that exist in production but whose
            # id the committed registry does not record. Non-zero is expected
            # between a deploy and a registry commit; permanently non-zero means
            # nobody is committing it back.
            "notebooks_published_but_unrecorded": count(nb_rows, "managed_by_name"),
        },
        "services": sorted(svc_rows, key=lambda r: (r["verdict"], r["name"])),
        "notebooks": sorted(nb_rows, key=lambda r: (r["verdict"], r["name"])),
    }


def to_markdown(report: dict) -> str:
    s = report["summary"]
    out = [
        "# Catalog reconciliation (§6)",
        "",
        "Does the catalog describe the estate this platform manages, or does it "
        "also describe things nothing owns?",
        "",
        "| | Live | Managed | Unmanaged |",
        "|---|---|---|---|",
        f"| Catalog services | {s['services_live']} | {s['services_managed']} | "
        f"{s['services_unmanaged']} |",
        f"| Runbook notebooks | {s['notebooks_live']} | {s['notebooks_managed']} | "
        f"{s['notebooks_unmanaged']} |",
        "",
    ]
    if s["notebooks_published_but_unrecorded"]:
        out += [f"**Registry drift:** {s['notebooks_published_but_unrecorded']} published "
                "runbook(s) are not recorded in `platform/policy/runbooks.yaml`. They are "
                "matched by name and are NOT candidates for deletion. This is expected "
                "between a deploy and a registry commit; permanently non-zero means the "
                "registry is never committed back.", ""]
    if s["services_auto_created"]:
        out += [f"{s['services_auto_created']} service(s) are created by Datadog itself "
                "and are excluded from both columns — they return after deletion.", ""]
    for kind, key in (("Services", "services"), ("Notebooks", "notebooks")):
        rows = [r for r in report[key] if r["verdict"] == "unmanaged"]
        if not rows:
            out += [f"## {kind}", "", "Nothing unmanaged.", ""]
            continue
        out += [f"## {kind} — {len(rows)} unmanaged", "",
                "| Name | Why |", "|---|---|"]
        out += [f"| `{r['name']}` | {r['reason']} |" for r in rows]
        out += [""]
    return "\n".join(out)


# -----------------------------------------------------------------------------
# deletion
# -----------------------------------------------------------------------------
def delete_unmanaged(report: dict, site: str, headers: dict, *,
                     kinds: set[str], max_delete: int) -> dict:
    results = {"deleted": [], "failed": []}
    targets = []
    if "services" in kinds:
        targets += [("service", r["name"], f"{site}/api/v2/services/definitions/{r['name']}")
                    for r in report["services"] if r["verdict"] == "unmanaged"]
    if "notebooks" in kinds:
        targets += [("notebook", f"{r['name']} ({r['id']})",
                     f"{site}/api/v1/notebooks/{r['id']}")
                    for r in report["notebooks"] if r["verdict"] == "unmanaged"]

    if len(targets) > max_delete:
        raise SystemExit(
            f"refusing to delete {len(targets)} objects in one run (--max-delete "
            f"{max_delete}). A reconciler that deletes hundreds of objects because "
            f"a path changed is worse than the drift it was fixing. Review the "
            f"dry-run report, then raise the cap deliberately.")

    for kind, label, url in targets:
        try:
            # Each deletion is independent: one 409 (an object something still
            # references) must not abandon the rest of the run.
            r = oc.dd_request("DELETE", url, headers=headers)
            if r.status_code >= 300:
                results["failed"].append({"kind": kind, "name": label,
                                          "status": r.status_code, "body": r.text[:300]})
            else:
                results["deleted"].append({"kind": kind, "name": label})
        except Exception as exc:                        # noqa: BLE001
            results["failed"].append({"kind": kind, "name": label, "error": str(exc)})
    return results


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--delete", action="store_true",
                    help="actually remove unmanaged objects. Omitted = dry run.")
    ap.add_argument("--kinds", default="services,notebooks",
                    help="comma-separated: services, notebooks")
    ap.add_argument("--max-delete", type=int, default=40)
    ap.add_argument("--out-json", type=Path,
                    default=oc.GENERATED_DIR / "catalog_reconcile.json")
    ap.add_argument("--out-md", type=Path,
                    default=oc.GENERATED_DIR / "catalog_reconcile.md")
    args = ap.parse_args()

    site, headers = oc.dd_site(), oc.dd_headers()
    report = reconcile(live_services(site, headers), live_notebooks(site, headers))

    if args.delete:
        # An empty managed set means the registry did not load. Deleting
        # everything is precisely the wrong response to not being able to see
        # what you are protecting.
        if not report["summary"]["services_managed"] and not report["summary"]["notebooks_managed"]:
            raise SystemExit("refusing to delete: nothing resolved as managed, which "
                             "means the registry failed to load rather than that the "
                             "org is empty")
        report["deletion"] = delete_unmanaged(
            report, site, headers,
            kinds={k.strip() for k in args.kinds.split(",")},
            max_delete=args.max_delete)

    oc.write_json(args.out_json, report)
    args.out_md.parent.mkdir(parents=True, exist_ok=True)
    args.out_md.write_text(to_markdown(report))
    print(json.dumps(report["summary"], indent=2))
    if "deletion" in report:
        d = report["deletion"]
        print(f"deleted {len(d['deleted'])}, failed {len(d['failed'])}")
        for f in d["failed"]:
            print(f"  FAILED {f['kind']} {f['name']}: {f.get('status') or f.get('error')}")
        return 1 if d["failed"] else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
