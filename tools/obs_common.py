"""Shared helpers for the observability platform tooling."""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
POLICY_DIR = REPO_ROOT / "platform" / "policy"
GENERATED_DIR = REPO_ROOT / "generated"

REQUIRED_TAGS = None  # populated by load_policy


def load_policy() -> dict:
    """Load the full policy hierarchy into one dict."""
    policy = {
        "global": _yaml(POLICY_DIR / "global.yaml"),
        "domains": _yaml(POLICY_DIR / "domains.yaml")["domains"],
        "profiles": _yaml(POLICY_DIR / "profiles.yaml"),
        "environments": _yaml(POLICY_DIR / "environments.yaml")["environments"],
        "tiers": _yaml(POLICY_DIR / "criticality.yaml")["tiers"],
        "teams": _yaml(POLICY_DIR / "teams.yaml"),
        "routing": _yaml(POLICY_DIR / "routing.yaml"),
        "slos": _yaml(POLICY_DIR / "slos.yaml")["slos"],
        "exceptions": _yaml(POLICY_DIR / "exceptions.yaml")["exceptions"],
        "runbooks": _yaml(POLICY_DIR / "runbooks.yaml"),
        "workflows": _yaml(POLICY_DIR / "workflows.yaml")["workflows"],
        "archetypes": {},
    }
    for f in sorted((POLICY_DIR / "archetypes").glob("*.yaml")):
        doc = _yaml(f)
        for aid, arch in doc["archetypes"].items():
            arch = dict(arch)
            arch["id"] = aid
            arch["domain"] = doc["domain"]
            policy["archetypes"][aid] = arch
    return policy


def _yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


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
            "DD_API_KEY / DD_APP_KEY are required for --live mode. "
            "Use the svc-observability-coverage service-account keys from the "
            "secret store — never personal credentials."
        )
    return {
        "DD-API-KEY": api_key,
        "DD-APPLICATION-KEY": app_key,
        "Content-Type": "application/json",
    }


def dd_site() -> str:
    return os.environ.get("DD_SITE", "https://api.datadoghq.com")
