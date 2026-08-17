"""Shared helpers for the observability platform tooling.

Every tool reads the SAME policy files Terraform reads. There is no second
source of truth and no duplicated logic: if a rule exists in Python and in HCL
they are both interpreting `platform/policy/`, never each other.
"""
from __future__ import annotations

import datetime as dt
import json
import os
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
        "exceptions_doc": _yaml(POLICY_DIR / "exceptions.yaml"),
        "exceptions": _yaml(POLICY_DIR / "exceptions.yaml")["exceptions"],
        "runbooks_doc": _yaml(POLICY_DIR / "runbooks.yaml"),
        "runbooks": _yaml(POLICY_DIR / "runbooks.yaml")["runbooks"],
        "workflows_doc": _yaml(POLICY_DIR / "workflows.yaml"),
        "workflows": _yaml(POLICY_DIR / "workflows.yaml")["workflows"],
        "grouping": _yaml(POLICY_DIR / "grouping.yaml"),
        "composites_doc": _yaml(POLICY_DIR / "composites.yaml"),
        "composites": _yaml(POLICY_DIR / "composites.yaml")["composites"],
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
    return policy


def load_services() -> dict:
    """Registered services (platform/services/*.yaml)."""
    out = {}
    for f in sorted((PLATFORM_DIR / "services").glob("*.yaml")):
        doc = _yaml(f)
        svc = doc["service"]
        out[svc["name"]] = svc
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
