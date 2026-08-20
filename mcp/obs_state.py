"""PLATFORM STATE — the single read surface every MCP tool answers from.

The whole point of this server is that it is NOT a second configuration system.
Every structural fact it reports is computed by the modules under `tools/` that
Terraform's own inputs come from:

    policy hierarchy      obs_common.load_policy()          (the same YAML)
    profile / band        profile_engine.assign()           (the same resolver)
    monitor expansion     obs_common.expand_instances()     (the same product)
    coverage C1..C17      coverage_report.run_checks()      (the same checks)
    routing               reconciliation_report.route_for() (the same routes)
    correlation           correlate_events.correlate()      (the same rules)

If a rule needs to change, it changes in `platform/policy/` and this server
changes with it. There is deliberately no rule implemented here that policy
does not already state — the one exception is documented at NOISE_DEFAULTS.

TWO MODES, and the difference is only WHERE the runtime facts come from:

  fixtures (default)  the plan-derived estate in `tests/fixtures/` plus the
                      runtime snapshot in `mcp/tests/fixtures/runtime_state.json`.
                      Everything runs offline; CI needs no credentials.
  live                the Datadog API, opted into with DD_API_KEY/DD_APP_KEY.
                      READ ONLY — see `_get`, which is the only HTTP verb this
                      module can issue. Configuration never reaches Datadog
                      from here; it reaches it through Git → CI → Terraform.
"""
from __future__ import annotations

import datetime as dt
import functools
import json
import os
import sys
from pathlib import Path

MCP_DIR = Path(__file__).resolve().parent
REPO_ROOT = MCP_DIR.parent
TOOLS_DIR = REPO_ROOT / "tools"

# The tools/ modules import each other flat (`import obs_common as oc`), which
# is why they are put on the path rather than imported as a package. Same
# reason mcp/ itself is a flat directory and not a package: a top-level Python
# package literally named `mcp` would shadow the `mcp` PyPI SDK for anything
# else running in the same interpreter.
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import build_inventory                     # noqa: E402
import correlate_events                    # noqa: E402
import coverage_report                     # noqa: E402
import obs_common as oc                    # noqa: E402
import profile_engine                      # noqa: E402
import reconciliation_report               # noqa: E402

REPO_FIXTURES = REPO_ROOT / "tests" / "fixtures"
RUNTIME_FIXTURE = MCP_DIR / "tests" / "fixtures" / "runtime_state.json"

# The estate denominator. `tests/` uses 2000 for the same reason: it is large
# enough that every governance path is exercised and small enough to run in a
# tool call. The real denominator in live mode is the discovered inventory.
DEFAULT_ESTATE_SIZE = int(os.environ.get("OBS_MCP_ESTATE_SIZE", "2000"))

# NOISE THRESHOLDS ARE NOT POLICY — a real gap, recorded here rather than
# hidden. `platform/policy/` budgets the monitor COUNT (global.yaml →
# cardinality.max_total_managed_monitors) and the paging RULE
# (priorities.yaml → paging_rule) but states nothing about how often a monitor
# may fire before it is noise. Until it does, these are server defaults that
# every answer discloses, and they are overridable per call so nobody mistakes
# them for a standard.
NOISE_DEFAULTS = {"noisy_triggers_30d": 20, "flapping_flaps_30d": 8, "silent_days": 90}


class DatadogUnavailable(RuntimeError):
    """A live-only surface was asked for and no credentials/data exist.

    Raised rather than returning empty: "there are no incidents" and "we cannot
    see incidents" are different answers, and only one of them is safe to act
    on.
    """


class PlatformState:
    """Lazily-loaded, per-request-cached view of policy + estate + runtime."""

    def __init__(self, mode: str = "fixtures", *, estate_size: int | None = None,
                 runtime_fixture: Path | None = None):
        if mode not in ("fixtures", "live"):
            raise ValueError(f"unknown mode {mode!r}")
        if mode == "live" and not (os.environ.get("DD_API_KEY") and os.environ.get("DD_APP_KEY")):
            raise DatadogUnavailable(
                "live mode needs DD_API_KEY and DD_APP_KEY (the read-only "
                "svc-observability-coverage service account, never personal keys)"
            )
        self.mode = mode
        self.estate_size = estate_size or DEFAULT_ESTATE_SIZE
        self.runtime_fixture = runtime_fixture or RUNTIME_FIXTURE
        self.loaded_at = oc.utcnow().isoformat()

    # -- source locators -----------------------------------------------------
    # Every Evidence.source in an answer comes from one of these, so a reader
    # can always get from a claim to the file or endpoint that produced it.

    def rel(self, path: Path) -> str:
        return str(Path(path).resolve().relative_to(REPO_ROOT))

    @property
    def monitor_source(self) -> str:
        return ("datadog:/api/v1/monitor" if self.mode == "live"
                else f"fixture:{self.rel(REPO_FIXTURES / 'monitors_planned.json')}")

    @property
    def slo_source(self) -> str:
        return ("datadog:/api/v1/slo" if self.mode == "live"
                else f"fixture:{self.rel(REPO_FIXTURES / 'slos.json')}")

    @property
    def runtime_source(self) -> str:
        return ("datadog:runtime" if self.mode == "live"
                else f"fixture:{self.rel(self.runtime_fixture)}")

    @property
    def estate_source(self) -> str:
        return ("datadog:/api/v1/hosts+/api/v2/services/definitions" if self.mode == "live"
                else f"synthetic-inventory:{self.estate_size}")

    # -- policy --------------------------------------------------------------

    @functools.cached_property
    def policy(self) -> dict:
        p = oc.load_policy()
        # reconciliation_report.route_for() reads the raw notification profile
        # document, not the digest load_policy() keeps. Load it the same way it
        # does so routes resolve identically in both tools.
        p["notification_profiles"] = oc._yaml(oc.POLICY_DIR / "notification_profiles.yaml")
        return p

    @functools.cached_property
    def services(self) -> dict:
        return oc.load_services()

    @functools.cached_property
    def custom_monitors(self) -> dict:
        return oc.load_custom_monitors()

    @functools.cached_property
    def instances(self) -> list[dict]:
        """(archetype × env × band) — exactly what Terraform expands."""
        return oc.expand_instances(self.policy)

    # -- estate --------------------------------------------------------------

    @functools.cached_property
    def inventory(self) -> dict:
        resources = (build_inventory.fetch_live() if self.mode == "live"
                     else build_inventory.synthesize(self.estate_size))
        return {
            "generated_at": self.loaded_at,
            "resource_count": len(resources),
            "service_count": len({r["service"] for r in resources if r.get("service")}),
            "resources": resources,
        }

    @functools.cached_property
    def assignments(self) -> dict:
        return profile_engine.assign(self.inventory, self.policy, self.services)

    # -- Datadog objects -----------------------------------------------------

    @functools.cached_property
    def monitors(self) -> list[dict]:
        if self.mode == "live":
            return self._paged_monitors()
        return json.loads((REPO_FIXTURES / "monitors_planned.json").read_text())

    @functools.cached_property
    def slos(self) -> list[dict]:
        if self.mode == "live":
            return self._paged_slos()
        slos = json.loads((REPO_FIXTURES / "slos.json").read_text())
        # The committed fixture carries `overall_status: [{}]` because a plan
        # has no runtime status. Overlay the runtime snapshot so burn-rate
        # questions have something real-shaped to read offline.
        status = self.runtime.get("slo_status") or {}
        for s in slos:
            st = status.get(s["id"])
            if st:
                s["overall_status"] = [dict(st)]
        return slos

    @functools.cached_property
    def monitors_by_id(self) -> dict:
        return {str(m["id"]): m for m in self.monitors}

    @functools.cached_property
    def managed_monitors(self) -> list[dict]:
        return [m for m in self.monitors
                if oc.tags_to_map(m.get("tags")).get("managed_by") == "terraform"]

    def monitor_tags(self, m: dict) -> dict:
        return oc.tags_to_map(m.get("tags"))

    # -- runtime snapshot ----------------------------------------------------

    @functools.cached_property
    def runtime(self) -> dict:
        """Monitor states, events, incidents, hosts, on-call, activity.

        These are the surfaces that do not exist in the repository at all:
        they describe what is happening, not what is configured. Offline they
        come from one committed snapshot; live they are fetched read-only.
        """
        if self.mode == "live":
            return self._live_runtime()
        if not self.runtime_fixture.exists():
            raise DatadogUnavailable(
                f"no runtime snapshot at {self.runtime_fixture} and not in live mode"
            )
        return json.loads(self.runtime_fixture.read_text())

    # -- derived reports (reusing the platform's own engines) ----------------

    @functools.cached_property
    def coverage(self) -> dict:
        return coverage_report.run_checks(
            self.inventory, self.assignments, self.monitors, self.slos, self.policy)

    @functools.cached_property
    def reconciliation(self) -> list[dict]:
        return reconciliation_report.build(self.monitors, self.policy)

    def route_for(self, profile: str, priority: str, pages: bool) -> str:
        return reconciliation_report.route_for(self.policy, profile, priority, pages)

    def correlate(self, events: list[dict]) -> list[dict]:
        return correlate_events.correlate(events)

    # -- live fetchers (READ ONLY) -------------------------------------------

    def _get(self, path: str, **params):
        """The only HTTP verb this server can issue against Datadog.

        Act mode never writes to Datadog: configuration reaches the org through
        Git → PR → CI → Terraform, and nothing else. Hard-coding GET here means
        a future contributor cannot add a write path by accident — they would
        have to delete this comment and the method to do it.
        """
        r = oc.dd_request("GET", f"{oc.dd_site()}{path}", headers=oc.dd_headers(),
                          params=params or None)
        r.raise_for_status()
        return r.json()

    def _paged_monitors(self) -> list[dict]:
        out, page = [], 0
        while True:
            batch = self._get("/api/v1/monitor", page=page, page_size=200,
                              group_states="all")
            out.extend(batch)
            if len(batch) < 200:
                return out
            page += 1

    def _paged_slos(self) -> list[dict]:
        out, offset = [], 0
        while True:
            batch = self._get("/api/v1/slo", limit=100, offset=offset).get("data", [])
            out.extend(batch)
            if len(batch) < 100:
                return out
            offset += 100

    def _live_runtime(self) -> dict:
        now = oc.utcnow()
        start = int((now - dt.timedelta(days=1)).timestamp())

        states = {}
        for m in self.monitors:
            groups = ((m.get("state") or {}).get("groups") or {})
            states[str(m["id"])] = {
                "overall_state": m.get("overall_state", "Unknown"),
                "last_triggered_ts": m.get("overall_state_modified"),
                "groups": {g: v.get("status") for g, v in groups.items()
                           if v.get("status") in ("Alert", "Warn", "No Data")},
            }

        events = []
        try:
            for e in self._get("/api/v1/events", start=start,
                               end=int(now.timestamp())).get("events", []):
                events.append({
                    "id": str(e.get("id")),
                    "ts": e.get("date_happened"),
                    "title": e.get("title", ""),
                    "kind": "alert" if e.get("alert_type") in ("error", "warning") else "change",
                    "source": e.get("source_type_name", ""),
                    "tags": oc.tags_to_map(e.get("tags")),
                    "monitor_id": str(e.get("monitor_id")) if e.get("monitor_id") else None,
                })
        except Exception as exc:                       # noqa: BLE001 — reported, not raised
            events = []
            self._runtime_errors = {"events": str(exc)}

        incidents = []
        try:
            for i in self._get("/api/v2/incidents", **{"page[size]": 50}).get("data", []):
                a = i.get("attributes", {})
                incidents.append({
                    "id": i.get("id"),
                    "title": a.get("title", ""),
                    "severity": a.get("fields", {}).get("severity", {}).get("value", ""),
                    "created": a.get("created"),
                    "resolved": a.get("resolved"),
                    "services": a.get("fields", {}).get("services", {}).get("value", []),
                })
        except Exception:                              # noqa: BLE001
            incidents = []

        hosts = []
        try:
            for h in self._get("/api/v1/hosts", count=1000).get("host_list", []):
                hosts.append({
                    "name": h.get("name"),
                    "up": h.get("up", False),
                    "agent_version": (h.get("meta") or {}).get("agent_version"),
                    "last_reported_ts": h.get("last_reported_time"),
                    "apps": h.get("apps", []),
                    "tags": oc.tags_to_map(sum((h.get("tags_by_source") or {}).values(), [])),
                })
        except Exception:                              # noqa: BLE001
            hosts = []

        # Monitor trigger COUNTS have no first-class Datadog endpoint. The
        # closest honest source is the event stream: every monitor transition
        # emits an event carrying `monitor_id`. That only covers the retention
        # window, which is why every noise answer states its window.
        activity: dict[str, dict] = {}
        for e in events:
            if e.get("monitor_id") and e["kind"] == "alert":
                a = activity.setdefault(e["monitor_id"], {"triggers": 0, "last_triggered_ts": None})
                a["triggers"] += 1
                a["last_triggered_ts"] = max(a["last_triggered_ts"] or 0, e["ts"] or 0)

        return {
            "captured_at": now.isoformat(),
            "window_days": 1,
            "monitor_states": states,
            "slo_status": {},
            "events": events,
            "incidents": incidents,
            "hosts": hosts,
            "integrations": sorted({app for h in hosts for app in h.get("apps", [])}),
            "monitor_activity": activity,
            # Rosters: §28 of docs/requirement-traceability.md records that
            # every schedule position in this org is UNASSIGNED. There is no
            # API answer to "who is on call" while that is true, so nothing is
            # fetched and `oncall` stays empty rather than fabricating a name.
            "oncall": {},
        }


@functools.lru_cache(maxsize=4)
def _cached_state(mode: str, estate_size: int, runtime_fixture: str) -> PlatformState:
    return PlatformState(mode, estate_size=estate_size,
                         runtime_fixture=Path(runtime_fixture))


def get_state(mode: str = "fixtures", *, estate_size: int | None = None,
              runtime_fixture: Path | None = None) -> PlatformState:
    """Process-wide cached state.

    Loading policy + synthesizing + assigning + running seventeen checks takes
    seconds; a chat client will make dozens of calls in a row. The cache is
    keyed on everything that changes the answer, and `reset_state()` drops it
    when a test (or an operator with `obs.describe_platform(refresh=true)`)
    needs a fresh read.
    """
    return _cached_state(mode, estate_size or DEFAULT_ESTATE_SIZE,
                         str(runtime_fixture or RUNTIME_FIXTURE))


def reset_state() -> None:
    _cached_state.cache_clear()
