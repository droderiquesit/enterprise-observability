"""Portal configuration and path resolution.

Two run modes, and the default is the safe one:

  fixtures  (default)  every upstream is a recorded API response on disk.
                       No credentials, no network, deterministic. This is what
                       CI and `portal/tests/` exercise.
  live      (opt-in)   Datadog reads using DD_API_KEY / DD_APP_KEY, taken from
                       the process environment and NEVER sent to the browser.
                       The browser only ever sees this module's `public()`.

Report artifacts (`generated/`) are read in BOTH modes: they are produced by
this platform's own tooling, not by Datadog, and a fresh clone has no
`generated/` directory at all — hence the fixture fallback.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

PORTAL_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = PORTAL_DIR.parent
TOOLS_DIR = REPO_ROOT / "tools"
STATIC_DIR = PORTAL_DIR / "static"
FIXTURES_DIR = PORTAL_DIR / "fixtures"
GENERATED_DIR = REPO_ROOT / "generated"

# The portal reuses tools/obs_common.py rather than re-reading the policy YAML
# with its own loader. One parser, one interpretation: if the portal and the
# coverage report disagreed about what a tier or a priority means, the portal
# would be quietly wrong in front of the people least able to notice.
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


@dataclass
class Settings:
    mode: str = "fixtures"                  # "fixtures" | "live"
    host: str = "127.0.0.1"
    port: int = 8787
    fixtures_dir: Path = FIXTURES_DIR
    generated_dir: Path = GENERATED_DIR
    static_dir: Path = STATIC_DIR

    # Live reads only. Datadog rate-limits per endpoint hard enough that a bulk
    # caller in this repo has already been 429'd on a real run (see
    # obs_common.dd_request). An executive portal is a fan-in — one open tab per
    # viewer, all polling the same handful of endpoints — so an unbounded
    # pass-through would spend the org's rate-limit budget on refreshes and
    # starve the deploy pipeline. The TTL is therefore an operational
    # requirement, not a performance nicety, and every cached payload carries
    # the timestamp of the FETCH so the page reports data age, not request age.
    cache_ttl_seconds: int = 60

    # Freshness budgets, per kind of source, because "stale" means a different
    # thing for each and one global number would be wrong for all three:
    #   live Datadog  — several multiples of the cache TTL; one slow upstream
    #                   must not flip the whole page amber on every refresh.
    #   report        — the governance loop runs nightly, so a report is
    #                   expected to be hours old and is only stale past a day.
    #   fixture       — a recorded snapshot is old by definition; it goes stale
    #                   once it is no longer describing roughly today.
    # Policy files are never stale: they are a git artifact, and their mtime
    # says when somebody last edited a YAML file, not how current the data is.
    stale_after_seconds: int = 900
    report_stale_after_seconds: int = 26 * 3600
    fixture_stale_after_seconds: int = 26 * 3600

    dd_site: str = "https://api.datadoghq.com"
    dd_app_site: str = "https://app.datadoghq.com"

    # Read-only by construction — this application has no write path at all.
    # The role exists so an SSO integration has somewhere to land (auth.py).
    default_role: str = "executive_viewer"

    # Demo replay (opt-in, off by default). A committed snapshot ages, so an
    # offline demonstration eventually shows an empty 24-hour window. With
    # PORTAL_FIXTURE_REPLAY=1 the recorded timestamps are shifted onto the
    # current clock so the recorded day plays as today. It is off by default
    # and the page says REPLAY when it is on, because a page that silently
    # relabels old data as current is the exact failure this portal is built to
    # avoid — a demo aid must never be mistakable for a live read.
    fixture_replay: bool = False

    @property
    def live(self) -> bool:
        return self.mode == "live"

    def public(self) -> dict:
        """The ONLY configuration the browser is allowed to see.

        Deliberately an allow-list rather than a filtered copy of the settings:
        a credential added to this dataclass later must not leak because
        somebody forgot to extend a deny-list.
        """
        return {
            "mode": self.mode,
            "cache_ttl_seconds": self.cache_ttl_seconds if self.live else 0,
            "stale_after_seconds": self.stale_after_seconds,
            "datadog_app_url": self.dd_app_site.rstrip("/"),
            "role": self.default_role,
            "fixture_replay": self.fixture_replay,
        }


def from_env(**overrides) -> Settings:
    s = Settings(
        host=os.environ.get("PORTAL_HOST", Settings.host),
        port=_int_env("PORTAL_PORT", Settings.port),
        cache_ttl_seconds=_int_env("PORTAL_CACHE_TTL", Settings.cache_ttl_seconds),
        stale_after_seconds=_int_env("PORTAL_STALE_AFTER", Settings.stale_after_seconds),
        dd_site=os.environ.get("DD_SITE", Settings.dd_site),
        dd_app_site=os.environ.get("DD_APP_SITE", Settings.dd_app_site),
        fixture_replay=os.environ.get("PORTAL_FIXTURE_REPLAY", "").lower()
        in ("1", "true", "yes"),
    )
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def credentials_present() -> bool:
    return bool(os.environ.get("DD_API_KEY") and os.environ.get("DD_APP_KEY"))
