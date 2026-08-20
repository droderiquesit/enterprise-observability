"""Shared helpers for the observability platform tooling.

Every tool reads the SAME policy files Terraform reads. There is no second
source of truth and no duplicated logic: if a rule exists in Python and in HCL
they are both interpreting `platform/policy/`, never each other.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
PLATFORM_DIR = REPO_ROOT / "platform"
POLICY_DIR = PLATFORM_DIR / "policy"
GENERATED_DIR = REPO_ROOT / "generated"


def _yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_policy() -> dict:
    """Load the whole configuration hierarchy into one dict."""
    policy = {
        "global": _yaml(POLICY_DIR / "global.yaml"),
        "domains": _yaml(POLICY_DIR / "domains.yaml")["domains"],
        "profiles": _yaml(POLICY_DIR / "profiles.yaml"),
        "environments": _yaml(POLICY_DIR / "environments.yaml")["environments"],
        "tiers_doc": _yaml(POLICY_DIR / "tiers.yaml"),
        "tiers": _yaml(POLICY_DIR / "tiers.yaml")["tiers"],
        "priorities": _yaml(POLICY_DIR / "priorities.yaml"),
        "teams_doc": _yaml(POLICY_DIR / "teams.yaml"),
        "teams": _yaml(POLICY_DIR / "teams.yaml")["teams"],
        "notification_profiles": _yaml(POLICY_DIR / "notification_profiles.yaml"),
        "service_archetypes_doc": _yaml(POLICY_DIR / "service_archetypes.yaml"),
        "slos": _yaml(POLICY_DIR / "slos.yaml")["slos"],
        "slos_doc": _yaml(POLICY_DIR / "slos.yaml"),
        "slo_profiles_doc": _yaml(POLICY_DIR / "slo_profiles.yaml"),
        "exceptions_doc": _yaml(POLICY_DIR / "exceptions.yaml"),
        "exceptions": _yaml(POLICY_DIR / "exceptions.yaml")["exceptions"],
        "runbooks_doc": _yaml(POLICY_DIR / "runbooks.yaml"),
        "runbooks": _yaml(POLICY_DIR / "runbooks.yaml")["runbooks"],
        "workflows_doc": _yaml(POLICY_DIR / "workflows.yaml"),
        "workflows": _yaml(POLICY_DIR / "workflows.yaml")["workflows"],
        "grouping": _yaml(POLICY_DIR / "grouping.yaml"),
        "entity_kinds_doc": _yaml(POLICY_DIR / "entity_kinds.yaml"),
        "composites_doc": _yaml(POLICY_DIR / "composites.yaml"),
        "composites": _yaml(POLICY_DIR / "composites.yaml")["composites"],
        # The report catalog and the entity-aware scorecard rules are policy
        # like everything else: tools/reports.py implements exactly the ids in
        # reports.yaml, and the scorecard reads its weights from scorecards.yaml
        # rather than carrying a second copy in Python.
        "reports_doc": _yaml(POLICY_DIR / "reports.yaml"),
        "reports": _yaml(POLICY_DIR / "reports.yaml")["reports"],
        "scorecards": _yaml(POLICY_DIR / "scorecards.yaml"),
        "archetypes": {},
    }
    for f in sorted((POLICY_DIR / "archetypes").glob("*.yaml")):
        doc = _yaml(f)
        for aid, arch in doc["archetypes"].items():
            arch = dict(arch)
            arch["id"] = aid
            arch["domain"] = doc["domain"]
            policy["archetypes"][aid] = arch
    policy["service_archetypes"] = policy["service_archetypes_doc"]["service_archetypes"]
    policy["packs"] = policy["service_archetypes_doc"]["packs"]
    policy["entity_kinds"] = policy["entity_kinds_doc"]["entity_kinds"]
    return policy


def load_agent_profiles() -> dict:
    """Agent profiles (platform/policy/agent_profiles.yaml, §37).

    Deliberately NOT folded into load_policy(): agent profiles describe how
    telemetry is PRODUCED, and load_policy() is the contract for what the
    monitor factory consumes. Terraform never reads this file, so putting it in
    the same dict would imply a coupling that does not exist.
    """
    return _yaml(POLICY_DIR / "agent_profiles.yaml")

def load_entities() -> dict:
    """Registered catalog entities (platform/entities/*.yaml), keyed by name.

    Every kind, not just services — that is the whole point of the entity
    model (§5). Callers that only want the service-shaped subset should use
    `load_services()`, which projects these onto the legacy registration shape.
    """
    out = {}
    for f in sorted((PLATFORM_DIR / "entities").glob("*.yaml")):
        ent = _yaml(f)["entity"]
        ent = dict(ent)
        ent.setdefault("source_file", f.name)
        out[ent["name"]] = ent
    return out


# Which legacy `service:` keys an entity carries under a different name. Only
# `tier` was renamed (to the §10 name `criticality`); everything else in the
# old service registration kept its name, which is what makes the projection
# below a rename rather than a translation.
_ENTITY_TO_SERVICE_KEY = {"criticality": "tier"}


def entity_as_service(entity: dict) -> dict:
    """Project an entity onto the legacy service-registration shape.

    Kept so that every existing consumer — the profile engine, the self-service
    monitor validator, the scorecard, both Terraform stacks — reads exactly
    what it read before the entity model landed. The projection is lossy on
    purpose: it drops the fields the old shape has no slot for (kind, region,
    oncall) rather than inventing keys nobody reads.

    `platform` is carried for the same reason `slo` is: packs_for() selects the
    technology-specific monitor packs from it, so dropping it silently reduced
    every datastore to the engine-agnostic pack.

    `slo` IS carried, and the reason is worth stating because it was dropped
    once and the loss was silent. tools/slo_resolver.py reads it twice: as the
    `slo_profile`/`service_override` layers of the §12 resolution chain, and as
    the tier1 OPT-IN in materializes_per_service_slos(). Dropping it here did
    not make a tier1 entity's `slo:` block resolve to a default — it made the
    entity materialize no SLO at all, and made two of the eight layers
    structurally unreachable, with nothing failing to say so.
    """
    svc = {_ENTITY_TO_SERVICE_KEY.get(k, k): v for k, v in entity.items()
           if k in ("name", "team", "criticality", "service_archetype", "description",
                    "envs", "dependencies", "links", "compliance_scope", "idempotent",
                    "slo", "platform")}
    return svc


def load_services() -> dict:
    """Service-shaped registrations, from BOTH registries.

    `platform/entities/` is the source of truth (it can express every kind);
    `platform/services/` is the superseded format, still read so that a branch
    written against it keeps working — see platform/services/README.md. It
    ships empty, so in practice this returns the entity projection.

    Only entities whose kind is pack-driven (they declare a
    `service_archetype`) appear here: a system has no packs and a queue has no
    service archetype, so handing either to a caller expecting a service would
    be a KeyError waiting to happen. Those callers want `load_entities()`.
    """
    out = {}
    for f in sorted((PLATFORM_DIR / "services").glob("*.yaml")):
        svc = _yaml(f)["service"]
        out[svc["name"]] = svc
    for name, ent in load_entities().items():
        if "service_archetype" not in ent:
            continue
        out.setdefault(name, entity_as_service(ent))
    return out


def packs_for(policy: dict, service_archetype: str, platform: str | None = None) -> list[str]:
    """The packs an entity actually gets: the archetype's base packs, plus the
    ones its `platform` selects.

    Implemented ONCE, here, because five callers ask this question — the
    coverage report, applicability, the MCP's onboarding preview and telemetry
    check, and Terraform's catalog links — and a caller that reads `packs`
    directly silently gets the platform-independent subset. An unknown or
    absent platform contributes nothing: a datastore whose technology we have
    not recorded is measured against the engine-agnostic pack only, which is
    the honest answer, not a default engine.
    """
    sa = policy["service_archetypes"].get(service_archetype)
    if not sa:
        return []
    out = list(sa.get("packs") or [])
    for pack in (sa.get("packs_by_platform") or {}).get(platform, []) if platform else []:
        if pack not in out:
            out.append(pack)
    return out


def archetypes_for(policy: dict, service_archetype: str, platform: str | None = None,
                   mandatory_only: bool = False) -> list[str]:
    """The monitor archetypes reachable through packs_for(), in pack order."""
    out: list[str] = []
    for pack in packs_for(policy, service_archetype, platform):
        for aid in policy["packs"].get(pack, {}).get("archetypes", []):
            if aid in policy["archetypes"] and aid not in out:
                if mandatory_only and not policy["archetypes"][aid].get("mandatory"):
                    continue
                out.append(aid)
    return out


def load_custom_monitors() -> dict:
    """Self-service monitor manifests (platform/monitors/*.yaml)."""
    out = {}
    for f in sorted((PLATFORM_DIR / "monitors").glob("*.yaml")):
        doc = _yaml(f)
        out[f.stem] = doc["monitor"]
    return out


# -----------------------------------------------------------------------------
# The priority function. Implemented ONCE, here, and reused by every tool so
# the scorecard, the coverage report and the matrix cannot disagree about what
# a monitor's priority is.
# -----------------------------------------------------------------------------
PRIORITY_RANK = {"P1": 1, "P2": 2, "P3": 3, "P4": 4}
RANK_PRIORITY = {v: k for k, v in PRIORITY_RANK.items()}

# The predictive-detection function list comes from policy (global.yaml →
# detection_policy.predictive_functions) so the validator, the scorecard and
# the manifest checker cannot each carry their own copy.
PREDICTIVE_FUNCS = tuple(
    _yaml(POLICY_DIR / "global.yaml")["detection_policy"]["predictive_functions"]
)


def resolve_priority(policy: dict, impact_class: str, band: str, env: str) -> str:
    """priority = clamp(matrix[impact_class][band], environment ceiling).

    An environment can only ever make a signal quieter — there is no path that
    raises priority in a non-production environment.
    """
    base = policy["priorities"]["matrix"][impact_class][band]
    ceiling = policy["environments"][env]["priority_ceiling"]
    return RANK_PRIORITY[max(PRIORITY_RANK[base], PRIORITY_RANK[ceiling])]


def resolve_notification_profile(policy: dict, domain: str, env: str, band: str) -> str:
    if domain == "security":
        return "security_operational"
    if env == "dev":
        return "nonprod_dev"
    if env in ("qa", "stage"):
        return "nonprod_standard"
    return {
        "critical": "production_critical",
        "standard": "production_standard",
        "baseline": "production_baseline",
    }[band]


def pages(policy: dict, priority: str, band: str, env: str, source: str = "archetype") -> bool:
    """Does this monitor wake a human?

    P1 always pages. P2 pages only from a source that has CONFIRMED impact —
    an SLO burn-rate monitor or a composite. A P2 symptom notifies and tickets
    but never pages. See platform/policy/priorities.yaml → paging_rule.
    """
    rule = policy["priorities"]["paging_rule"]
    if not policy["environments"][env]["paging_allowed"] or band != "critical":
        return False
    if priority == "P1":
        return True
    if priority == "P2":
        return source in rule["p2_pages_only_from"]
    return False


def expand_instances(policy: dict, environments: list[str] | None = None) -> list[dict]:
    """The same (archetype × env × band) expansion Terraform performs.

    Used by the matrix generator, the scorecard and the tests so that what the
    documentation claims and what Terraform plans cannot drift apart.
    """
    environments = environments or ["qa", "stage", "prod"]
    out = []
    for aid, a in sorted(policy["archetypes"].items()):
        for env in environments:
            ep = policy["environments"][env]
            if not ep["alerting"] or env not in a["envs"]:
                continue
            for band in ep["bands_instantiated"]:
                if band not in a["bands"]:
                    continue
                priority = resolve_priority(policy, a["impact_class"], band, env)
                out.append(
                    {
                        "key": f"{env}.{band}.{a['domain']}.{aid}",
                        "archetype": aid,
                        "title": a["title"],
                        "domain": a["domain"],
                        "env": env,
                        "band": band,
                        "signal": a["signal"],
                        "impact_class": a["impact_class"],
                        "detection": a["detection"],
                        "monitor_type": a["monitor_type"],
                        "resource_type": a["resource_type"],
                        "group_by": a.get("group_by", []),
                        "notify_by": a.get("notify_by", []),
                        "evaluation_window": a.get("evaluation_window", ""),
                        "priority": priority,
                        "pages": pages(policy, priority, band, env),
                        "notification_profile": resolve_notification_profile(
                            policy, a["domain"], env, band
                        ),
                        "slo_id": a["slo_id"],
                        "runbook": a["runbook"],
                        "workflow": a["workflow"],
                        "mandatory": a.get("mandatory", False),
                        "compliance": a.get("compliance", False),
                    }
                )
    return out


# ======================================================================
# BEGIN telemetry requirements (§38) — derive what an archetype needs to exist
#
# The vocabulary and the namespace→source mapping both live in
# platform/policy/global.yaml → telemetry_sources, so this module interprets
# policy rather than carrying a second copy of it. Everything that asks "can
# this monitor fire?" — the lint, the applicability engine, the profile engine
# — goes through these two functions.
# =============================================================================

# A Datadog query names its metrics as dotted tokens. Case matters: SNMP metric
# names are camelCase (`snmp.ifBandwidthInUsage.rate`), and a lowercase-only
# pattern splits them into two fragments, neither of which resolves.
_METRIC_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+")
_EVENT_SOURCE = re.compile(r"source:([A-Za-z0-9_.-]+)")


def telemetry_sources(policy: dict) -> dict:
    return policy["global"]["telemetry_sources"]


def derive_telemetry(policy: dict, query: str) -> list[str]:
    """The telemetry sources a query CANNOT work without.

    Longest-prefix match, because the namespaces overlap where the products do:
    `azure.cost.*` is Cloud Cost Management (separately licensed and separately
    enabled) while everything else under `azure.` is the Azure integration, and
    `acme.database.restore_verification*` comes from a different job than
    `acme.database.hours_since_backup`. Matching the shorter prefix first would
    quietly attribute a signal to the wrong producer, which is the exact class
    of mistake this whole field exists to prevent.

    Tokens that match no namespace are tag keys (`peer.service`,
    `http.status_class`) or Datadog function syntax, not metrics — ignored.
    """
    sources = telemetry_sources(policy)
    prefixes: list[tuple[str, str]] = []
    events: dict[str, str] = {}
    for sid, s in sources.items():
        for ns in s.get("metric_namespaces", []) or []:
            prefixes.append((ns, sid))
        for ev in s.get("event_sources", []) or []:
            events[ev] = sid
    prefixes.sort(key=lambda p: len(p[0]), reverse=True)

    found: set[str] = set()
    for token in _METRIC_TOKEN.findall(query):
        for ns, sid in prefixes:
            if token.startswith(ns):
                found.add(sid)
                break
    # An event monitor reads no metric at all; its producer is the event source.
    for src in _EVENT_SOURCE.findall(query):
        if src in events:
            found.add(events[src])
    return sorted(found)


def archetype_telemetry(policy: dict, archetype: dict) -> list[str]:
    """What an archetype declares it needs, falling back to what its query implies.

    The fallback is not a convenience — it keeps every consumer working against
    a catalog file that a parallel branch added before the lint made the field
    mandatory, instead of raising KeyError halfway through a report.
    """
    declared = archetype.get("telemetry")
    if declared:
        return sorted(declared)
    return derive_telemetry(policy, archetype.get("query", ""))


# END telemetry requirements (§38)
# =============================================================================
# -----------------------------------------------------------------------------
# ENTITY KIND (§41). Implemented ONCE, here, for the same reason resolve_priority
# is: the scorecard, the reports and the tests must not each carry their own
# opinion about whether an Azure Storage account is a datastore.
# -----------------------------------------------------------------------------
def entity_kind(policy: dict, resource_type: str) -> str:
    """`resource_type` -> service | datastore | infrastructure.

    Raises on an unclassified type rather than defaulting. A silent default is
    how a new datastore technology gets graded as a request path and is never
    asked for a backup check; validate_policy.py catches it before this can.
    """
    try:
        return policy["scorecards"]["resource_type_kind"][resource_type]
    except KeyError:
        raise KeyError(
            f"resource_type {resource_type!r} is not classified in "
            "platform/policy/scorecards.yaml -> resource_type_kind"
        ) from None


def entity_kind_of_service_archetype(policy: dict, service_archetype: str) -> str:
    """The same three kinds, seen from the RESOURCE side (profile engine output)."""
    return policy["scorecards"]["service_archetype_kind"].get(
        service_archetype, "service")


def durability_covered_types(policy: dict) -> set[str]:
    """Datastore resource_types whose catalog answers "would we see it coming?".

    Judged per TECHNOLOGY, not per monitor: durability coverage is a property of
    the archetype set for a resource_type, and one monitor cannot be blamed for
    a missing sibling.
    """
    signals = set(policy["scorecards"]["durability_signals"])
    covered: set[str] = set()
    for a in policy["archetypes"].values():
        if a["detection"] == "forecast" or a["signal"] in signals:
            covered.add(a["resource_type"])
    return covered


def tags_to_map(tags: list[str] | None) -> dict:
    """`["k:v", ...]` → `{k: v}`, first value wins for a repeated key."""
    out: dict[str, str] = {}
    for t in tags or []:
        if ":" in t:
            k, v = t.split(":", 1)
            out.setdefault(k, v)
    return out


def dd_request(method: str, url: str, *, headers: dict, attempts: int = 6,
               session=None, **kwargs):
    """One Datadog call with rate-limit-aware retry.

    Bulk callers exceed Datadog's per-endpoint rate limits in practice
    (publishing 152 notebooks 429'd on a real run). Honour the wait the API
    states in Retry-After (or X-RateLimit-Reset), fall back to exponential
    backoff, retry 5xx the same way; everything else returns as-is for the
    caller to inspect.
    """
    import time

    import requests
    delay = 2.0
    for attempt in range(attempts):
        r = (session or requests).request(method, url, headers=headers,
                                          timeout=60, **kwargs)
        if r.status_code != 429 and r.status_code < 500:
            return r
        if attempt == attempts - 1:
            return r
        wait = r.headers.get("Retry-After") or r.headers.get("X-RateLimit-Reset")
        try:
            sleep_for = float(wait)
        except (TypeError, ValueError):
            sleep_for = delay
            delay *= 2
        print(f"  rate-limited ({r.status_code}) on {method} {url.rsplit('/', 1)[-1]}"
              f" — waiting {sleep_for:.0f}s")
        time.sleep(min(sleep_for, 60.0))
    return r


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=True, default=str)
        fh.write("\n")


def dd_headers() -> dict:
    api_key = os.environ.get("DD_API_KEY")
    app_key = os.environ.get("DD_APP_KEY")
    if not api_key or not app_key:
        raise SystemExit(
            "DD_API_KEY / DD_APP_KEY are required for --live mode. Use the "
            "svc-observability-coverage service-account keys from the secret "
            "store — never personal credentials."
        )
    return {
        "DD-API-KEY": api_key,
        "DD-APPLICATION-KEY": app_key,
        "Content-Type": "application/json",
    }


def dd_site() -> str:
    return os.environ.get("DD_SITE", "https://api.datadoghq.com")
