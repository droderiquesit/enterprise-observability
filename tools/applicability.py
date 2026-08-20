#!/usr/bin/env python3
"""MONITOR APPLICABILITY ENGINE — "can this monitor ever fire here?"

A monitor whose telemetry source is absent does not fail. It evaluates against
an empty series, reports OK, and stays OK forever. Nothing in Datadog marks it
as broken, nothing pages, and the estate looks covered — which is why the
question this tool answers has to be answered OUTSIDE the monitoring system:

    given what an entity actually emits, which of the archetypes aimed at it
    can produce a result, which cannot, and what exactly is missing?

Inputs (both offline; nothing here talks to Datadog):

  the archetype catalog   platform/policy/archetypes/*.yaml — each archetype's
                          `telemetry:` names the sources it cannot fire without
  an estate description   entities plus the telemetry sources available to
                          them, e.g. tests/fixtures/telemetry_estate.json

Outputs three things, per entity and rolled up:

  applicable                    archetype × entity pairs that can produce data
  blocked_by_missing_telemetry  pairs that cannot, WITH THE MISSING SOURCE NAMED
  coverage_pct                  applicable / (applicable + blocked)

WHY THE MISSING SOURCE IS NAMED. "62% coverage" is a number nobody can act on.
"snowflake-task-failure is blocked on custom_snowflake_exporter" is a ticket
with an owner. Every blocked row carries the source id, its display name and
what provides it, straight from global.yaml → telemetry_sources.

TWO VIEWS, because two different people ask this question:

  entity view    an owner asking "what does MY database get?" — resolves the
                 entity's service_archetype to its packs and evaluates those.
  catalog view   the platform team asking "what does the whole catalog cost
                 us in unmet prerequisites?" — evaluates all 264 archetypes
                 against the estate's sources, which is how you find the
                 emitters that would unlock the most coverage for one piece of
                 work.

Coverage here is a CEILING, not an achievement: it says a monitor is capable of
producing a result, not that the result is correct or that anyone is on call
for it. Those are the coverage report's and the scorecard's questions.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import obs_common as oc


# -----------------------------------------------------------------------------
# Resolution
# -----------------------------------------------------------------------------
def pack_archetypes(policy: dict, service_archetype: str,
                    platform: str | None = None) -> list[str]:
    """Archetypes a service archetype's packs instantiate.

    Unknown service archetypes resolve to nothing rather than to a guess: a
    silently-substituted default would report coverage for monitors that were
    never aimed at the entity.
    """
    return oc.archetypes_for(policy, service_archetype, platform)


def available_sources(estate: dict, entity: dict) -> set[str]:
    """What this entity can actually emit.

    Estate-level sources are the ones enabled once for everything (an Agent
    fleet, an Azure subscription integration); entity-level sources are the
    ones that are per-thing (this service is traced, this cluster runs
    kube-state-metrics). The union is what its monitors can read.
    """
    return set(estate.get("telemetry", []) or []) | set(entity.get("telemetry", []) or [])


def _source_detail(policy: dict, source_id: str) -> dict:
    s = oc.telemetry_sources(policy).get(source_id, {})
    return {
        "source": source_id,
        "display": s.get("display", source_id),
        "kind": s.get("kind", "unknown"),
        "provided_by": s.get("provided_by", "unknown — not in the vocabulary"),
    }


# -----------------------------------------------------------------------------
# Evaluation
# -----------------------------------------------------------------------------
def evaluate_archetypes(policy: dict, archetype_ids: list[str],
                        available: set[str]) -> dict:
    """Split a set of archetypes into applicable / blocked against `available`."""
    applicable, blocked = [], []
    for aid in archetype_ids:
        a = policy["archetypes"][aid]
        required = oc.archetype_telemetry(policy, a)
        missing = [t for t in required if t not in available]
        row = {
            "archetype": aid,
            "title": a["title"],
            "domain": a["domain"],
            "requires": required,
        }
        if missing:
            row["missing"] = missing
            row["reason"] = (
                f"{a['title']} reads {', '.join(required)}; "
                f"{', '.join(missing)} is not available here, so the monitor "
                "would evaluate against no series and report OK indefinitely"
            )
            row["remediation"] = [_source_detail(policy, m) for m in missing]
            blocked.append(row)
        else:
            applicable.append(row)
    return {"applicable": applicable, "blocked_by_missing_telemetry": blocked}


def coverage_pct(applicable: int, blocked: int) -> float:
    total = applicable + blocked
    # No aimed-at archetypes is not 100% coverage — there is nothing to cover
    # and claiming a perfect score would flatter an entity nobody monitors.
    return round(100.0 * applicable / total, 1) if total else 0.0


def evaluate_entity(policy: dict, estate: dict, entity: dict) -> dict:
    available = available_sources(estate, entity)
    vocab = oc.telemetry_sources(policy)
    unknown = sorted(s for s in available if s not in vocab)

    ids = pack_archetypes(policy, entity.get("service_archetype", ""),
                          entity.get("platform"))
    result = evaluate_archetypes(policy, ids, available)
    n_ok = len(result["applicable"])
    n_blocked = len(result["blocked_by_missing_telemetry"])
    return {
        "id": entity["id"],
        "kind": entity.get("kind"),
        "service": entity.get("service"),
        "env": entity.get("env"),
        "service_archetype": entity.get("service_archetype"),
        "telemetry_available": sorted(available),
        # An entity claiming a source the vocabulary does not define is a
        # typo in the inventory, and a typo here silently BLOCKS monitors.
        "telemetry_unknown": unknown,
        "applicable_count": n_ok,
        "blocked_count": n_blocked,
        "coverage_pct": coverage_pct(n_ok, n_blocked),
        **result,
    }


def evaluate(policy: dict, estate: dict) -> dict:
    entities = [evaluate_entity(policy, estate, e) for e in estate.get("entities", [])]

    # Which source, if it were turned on, unblocks the most? Counted over
    # entity × archetype pairs because that is the unit of lost coverage.
    blocked_by_source: Counter = Counter()
    blocked_archetypes: dict[str, set] = defaultdict(set)
    for e in entities:
        for row in e["blocked_by_missing_telemetry"]:
            for m in row["missing"]:
                blocked_by_source[m] += 1
                blocked_archetypes[m].add(row["archetype"])

    applicable = sum(e["applicable_count"] for e in entities)
    blocked = sum(e["blocked_count"] for e in entities)

    estate_sources = set(estate.get("telemetry", []) or [])
    for e in estate.get("entities", []):
        estate_sources |= set(e.get("telemetry", []) or [])
    catalog = evaluate_archetypes(policy, sorted(policy["archetypes"]), estate_sources)

    return {
        "generated_at": oc.utcnow().isoformat(),
        "estate": estate.get("name", "unnamed estate"),
        "summary": {
            "entities": len(entities),
            "archetype_instances_applicable": applicable,
            "archetype_instances_blocked": blocked,
            "coverage_pct": coverage_pct(applicable, blocked),
            "entities_fully_covered": sum(1 for e in entities if e["blocked_count"] == 0),
            "entities_fully_blocked": sum(
                1 for e in entities if e["applicable_count"] == 0 and e["blocked_count"]),
            "entities_with_no_archetypes": sum(
                1 for e in entities
                if e["applicable_count"] == 0 and e["blocked_count"] == 0),
            "catalog_archetypes": len(policy["archetypes"]),
            "catalog_applicable": len(catalog["applicable"]),
            "catalog_blocked": len(catalog["blocked_by_missing_telemetry"]),
            "catalog_coverage_pct": coverage_pct(
                len(catalog["applicable"]), len(catalog["blocked_by_missing_telemetry"])),
            "telemetry_sources_available": sorted(estate_sources),
            "telemetry_sources_missing": sorted(
                set(oc.telemetry_sources(policy)) - estate_sources),
        },
        "blocked_by_source": [
            {
                **_source_detail(policy, src),
                "blocked_instances": n,
                "blocked_archetypes": sorted(blocked_archetypes[src]),
            }
            for src, n in blocked_by_source.most_common()
        ],
        "entities": entities,
        "catalog": catalog,
    }


# -----------------------------------------------------------------------------
# Rendering
# -----------------------------------------------------------------------------
def to_markdown(report: dict) -> str:
    s = report["summary"]
    lines = [
        f"# Monitor applicability — {report['estate']}",
        "",
        "Which monitors can actually produce a result against this estate, and "
        "what is missing where they cannot. A blocked monitor is not a failing "
        "monitor: it reports OK forever, which is why it is counted here rather "
        "than discovered during an incident.",
        "",
        f"- Entities: **{s['entities']}** "
        f"({s['entities_fully_covered']} fully covered, "
        f"{s['entities_fully_blocked']} entirely blocked)",
        f"- Applicable archetype instances: **{s['archetype_instances_applicable']}**, "
        f"blocked: **{s['archetype_instances_blocked']}**",
        f"- Entity coverage ceiling: **{s['coverage_pct']}%**",
        f"- Catalog coverage against this estate's sources: "
        f"**{s['catalog_coverage_pct']}%** "
        f"({s['catalog_applicable']}/{s['catalog_archetypes']} archetypes)",
        "",
    ]
    if report["blocked_by_source"]:
        lines += [
            "## Missing telemetry, most expensive first",
            "",
            "Ordered by blocked entity × archetype pairs, so the top row is the "
            "single piece of work that buys the most coverage.",
            "",
            "| Source | Kind | Blocked | Archetypes | Provided by |",
            "|---|---|---|---|---|",
        ]
        for row in report["blocked_by_source"]:
            lines.append(
                f"| `{row['source']}` | {row['kind']} | {row['blocked_instances']} | "
                f"{len(row['blocked_archetypes'])} | {row['provided_by']} |")
        lines.append("")

    lines += ["## Per entity", "",
              "| Entity | Service archetype | Applicable | Blocked | Coverage | Missing |",
              "|---|---|---|---|---|---|"]
    for e in report["entities"]:
        missing = sorted({m for r in e["blocked_by_missing_telemetry"] for m in r["missing"]})
        lines.append(
            f"| `{e['id']}` | {e['service_archetype']} | {e['applicable_count']} | "
            f"{e['blocked_count']} | {e['coverage_pct']}% | "
            f"{', '.join(f'`{m}`' for m in missing) or '—'} |")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--estate", type=Path,
                    default=oc.REPO_ROOT / "tests" / "fixtures" / "telemetry_estate.json",
                    help="estate description: entities + available telemetry sources")
    ap.add_argument("--out-json", type=Path,
                    default=oc.GENERATED_DIR / "applicability.json")
    ap.add_argument("--out-md", type=Path,
                    default=oc.GENERATED_DIR / "applicability.md")
    ap.add_argument("--fail-under", type=float, default=None,
                    help="exit non-zero when entity coverage falls below this "
                         "percentage (for use as a CI gate once the estate's "
                         "emitters are deployed)")
    args = ap.parse_args()

    policy = oc.load_policy()
    estate = json.loads(args.estate.read_text())
    report = evaluate(policy, estate)

    oc.write_json(args.out_json, report)
    args.out_md.parent.mkdir(parents=True, exist_ok=True)
    args.out_md.write_text(to_markdown(report))
    print(json.dumps(report["summary"], indent=2))
    for row in report["blocked_by_source"][:10]:
        print(f"  blocked {row['blocked_instances']:4d} by {row['source']} "
              f"— {row['provided_by']}")
    if args.fail_under is not None and report["summary"]["coverage_pct"] < args.fail_under:
        print(f"\napplicability: FAIL — coverage {report['summary']['coverage_pct']}% "
              f"is below --fail-under {args.fail_under}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
