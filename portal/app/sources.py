"""Data sources, their freshness, and what happens when one is down.

THE RULE THIS MODULE EXISTS TO ENFORCE (§49):

    An unavailable source must never render as a confident zero.

A dashboard that shows "0 open incidents" because the incidents API returned
503 is worse than no dashboard, because it manufactures the exact reassurance
an executive is looking for. So every fetch returns a `SourceResult` carrying
its own status, and every number derived from a source is a `Measure` that can
be `unknown`. The view layer has no way to produce a value without a source,
and the frontend renders `unknown` as a visible gap, not as a green tile.

Freshness is the age of the DATA, not of the request:
  * report artifacts  →  the report's own `generated_at`, falling back to the
                         file mtime for artifacts that do not carry one
  * Datadog reads     →  when the portal actually called the API (which, with
                         the cache, may be up to `cache_ttl_seconds` ago)
  * policy            →  the newest mtime under platform/policy/
"""
from __future__ import annotations

import datetime as dt
import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from . import config

OK = "ok"
STALE = "stale"
UNAVAILABLE = "unavailable"

# origin values, most-authoritative first
ORIGIN_DATADOG = "datadog"
ORIGIN_REPORT = "report"
ORIGIN_FIXTURE = "fixture"
ORIGIN_POLICY = "policy"


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _iso(ts: dt.datetime | None) -> str | None:
    return ts.isoformat().replace("+00:00", "Z") if ts else None


def _parse_ts(value: Any) -> dt.datetime | None:
    """Best-effort timestamp parse across the shapes upstreams actually use.

    Datadog returns epoch seconds in some payloads and RFC3339 in others; the
    platform's own reports write `datetime.isoformat()`. An unparseable value
    yields None, which surfaces as "age unknown" rather than as age zero — the
    same rule as everywhere else in this module.
    """
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        # Datadog mixes seconds and milliseconds; anything past year 5000 in
        # seconds is certainly milliseconds.
        seconds = value / 1000.0 if value > 1e11 else float(value)
        try:
            return dt.datetime.fromtimestamp(seconds, dt.timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)


def humanize_age(seconds: float | None) -> str:
    if seconds is None:
        return "age unknown"
    seconds = max(0.0, seconds)
    if seconds < 90:
        return f"{int(seconds)}s ago"
    if seconds < 5400:
        return f"{int(seconds / 60)} min ago"
    if seconds < 172800:
        return f"{int(seconds / 3600)} h ago"
    return f"{int(seconds / 86400)} d ago"


# Keys whose values are timestamps in the recorded Datadog payloads. Used only
# by the opt-in demo replay below.
_TIME_KEYS = {"timestamp", "created", "detected", "resolved", "modified",
              "created_at", "modified_at", "last_updated"}


def replay_shift(data, recorded_at: dt.datetime):
    """Shift every recorded timestamp forward by (now − recorded_at).

    Opt-in demo aid (PORTAL_FIXTURE_REPLAY=1) so a committed snapshot's 24-hour
    window plays as the last 24 hours instead of showing an empty day. The
    shift is uniform, so every duration, interval and ordering in the fixture is
    preserved exactly — only the anchor moves. The freshness panel says REPLAY
    whenever this ran, and the portal refuses to do it in live mode because
    there is nothing to replay there.
    """
    delta = _utcnow() - recorded_at
    if delta.total_seconds() <= 0:
        return data

    def walk(node, key=None):
        if isinstance(node, dict):
            return {k: walk(v, k) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(v, key) for v in node]
        if key in _TIME_KEYS and node not in (None, ""):
            parsed = _parse_ts(node)
            if parsed is None:
                return node
            shifted = parsed + delta
            if isinstance(node, (int, float)):
                seconds = shifted.timestamp()
                return int(seconds * 1000) if node > 1e11 else int(seconds)
            return shifted.isoformat().replace("+00:00", "Z")
        return node

    return walk(data)


# -----------------------------------------------------------------------------
# On-disk parse cache, keyed on the file's own modification time.
#
# NOT a data cache and not a store of truth: the key IS the mtime, so a
# changed file is re-read on the next request and stale content cannot be
# served — the only thing avoided is re-parsing bytes that have not changed.
# It exists because the portal re-reads ~30 policy YAML files and a 350 KB
# reconciliation report on EVERY request, which costs ~0.9 s of CPU per view
# for a result that is byte-identical until somebody runs the tooling again.
# The freshness a viewer sees is still derived from the file, never from when
# the cache happened to fill.
# -----------------------------------------------------------------------------
_parse_lock = threading.Lock()
_parse_cache: dict[str, tuple[Any, Any]] = {}


def _cached_parse(key: str, signature, load: Callable[[], Any]):
    with _parse_lock:
        entry = _parse_cache.get(key)
        if entry is not None and entry[0] == signature:
            return entry[1]
    value = load()
    with _parse_lock:
        _parse_cache[key] = (signature, value)
    return value


def clear_parse_cache() -> None:
    with _parse_lock:
        _parse_cache.clear()


@dataclass
class SourceResult:
    """One upstream read, with everything needed to render it honestly."""

    name: str
    origin: str
    status: str = OK
    data: Any = None
    produced_at: dt.datetime | None = None   # when the DATA was made
    read_at: dt.datetime = field(default_factory=_utcnow)
    error: str | None = None
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status != UNAVAILABLE

    @property
    def age_seconds(self) -> float | None:
        if self.produced_at is None:
            return None
        return (_utcnow() - self.produced_at).total_seconds()

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "origin": self.origin,
            "status": self.status,
            "produced_at": _iso(self.produced_at),
            "read_at": _iso(self.read_at),
            "age_seconds": None if self.age_seconds is None else round(self.age_seconds, 1),
            "age_label": humanize_age(self.age_seconds),
            "error": self.error,
            "detail": self.detail,
        }


# -----------------------------------------------------------------------------
# Measures — a number that knows whether it is real
# -----------------------------------------------------------------------------
def measure(value, *, unit: str = "", state: str = "ok", label: str | None = None,
            note: str = "", source: str = "", link: str | None = None) -> dict:
    """A known value.

    `state` drives the visual treatment and is one of ok / watch / risk /
    critical / neutral. It is ALWAYS accompanied by `label`, because status
    colour must not be the only signal (§49 accessibility).
    """
    return {
        "known": True, "value": value, "unit": unit, "state": state,
        "label": label if label is not None else _default_label(state),
        "note": note, "source": source, "link": link,
    }


def unknown(reason: str, *, source: str = "", unit: str = "") -> dict:
    """A value the portal could not obtain.

    Never call this with a fallback number. The whole point is that the page
    shows a gap where a gap exists.
    """
    return {
        "known": False, "value": None, "unit": unit, "state": "unknown",
        "label": "No data", "note": reason, "source": source, "link": None,
    }


_STATE_LABELS = {
    "ok": "Healthy",
    "watch": "Watch",
    "risk": "At risk",
    "critical": "Critical",
    "neutral": "Informational",
    "unknown": "No data",
}


def _default_label(state: str) -> str:
    return _STATE_LABELS.get(state, state.title())


WORST_FIRST = ["unknown", "critical", "risk", "watch", "neutral", "ok"]
KNOWN_WORST_FIRST = ["critical", "risk", "watch", "neutral", "ok"]


def worst_state(states) -> str:
    """Roll several states into one, `unknown` first.

    "We cannot see this" outranks "this is broken": a blind spot is the more
    serious statement, because a known failure is already being worked and an
    unknown one is not.
    """
    states = [s for s in states if s]
    for candidate in WORST_FIRST:
        if candidate in states:
            return candidate
    return "ok"


def rollup(states) -> tuple[str, int]:
    """Roll up for a HEADLINE: worst known state, plus how many are unseen.

    Different rule from `worst_state`, and the difference matters exactly once
    — at the top of the page. If a single objective cannot be computed while a
    SEV-1 is running, the headline must say "Critical", not "Not visible": the
    executive needs the incident first and the blind spot second. So the two
    facts are returned separately, and the caller states both.

    All-unknown still yields "unknown" — with nothing visible there is no
    health claim to make.
    """
    states = [s for s in states if s]
    if not states:
        return "ok", 0
    blind = sum(1 for s in states if s == "unknown")
    known = [s for s in states if s != "unknown"]
    if not known:
        return "unknown", blind
    for candidate in KNOWN_WORST_FIRST:
        if candidate in known:
            # A clean bill of health with an unseen corner is not a clean bill
            # of health; it is a "watch".
            return ("watch" if candidate == "ok" and blind else candidate), blind
    return "ok", blind


# -----------------------------------------------------------------------------
# The registry
# -----------------------------------------------------------------------------
class SourceRegistry:
    """Resolves every upstream and remembers how each read went.

    One registry instance per request. It is the only thing that touches the
    disk or the network, so the view layer is pure and testable, and a test can
    make any single source fail by stubbing one entry.
    """

    def __init__(self, settings: config.Settings, cache: "TTLCache | None" = None):
        self.settings = settings
        self.cache = cache
        self.results: dict[str, SourceResult] = {}

    # --- recording ---------------------------------------------------------
    def freshness_budget(self, origin: str) -> int | None:
        """How old this KIND of source may be before it is called stale.

        Policy has no budget: `platform/policy/` is a git artifact and its mtime
        records when a human last edited a YAML file, which says nothing about
        whether the data is current. Calling it stale would be noise.
        """
        return {
            ORIGIN_DATADOG: self.settings.stale_after_seconds,
            ORIGIN_REPORT: self.settings.report_stale_after_seconds,
            ORIGIN_FIXTURE: self.settings.fixture_stale_after_seconds,
            ORIGIN_POLICY: None,
        }.get(origin, self.settings.stale_after_seconds)

    def record(self, result: SourceResult) -> SourceResult:
        budget = self.freshness_budget(result.origin)
        age = result.age_seconds
        if result.status == OK and budget and age is not None and age > budget:
            result.status = STALE
            hours = budget / 3600
            result.detail = (
                (result.detail + " — " if result.detail else "")
                + f"older than the {hours:.0f}h freshness budget for a "
                  f"{result.origin} source")
        self.results[result.name] = result
        return result

    def get(self, name: str) -> SourceResult:
        return self.results.get(
            name, SourceResult(name=name, origin="none", status=UNAVAILABLE,
                               error="source was never read"))

    def sources(self) -> list[dict]:
        return [r.to_dict() for r in sorted(self.results.values(), key=lambda r: r.name)]

    def freshness(self) -> dict:
        """One sentence the page can put next to the clock."""
        results = list(self.results.values())
        if not results:
            return {"state": "unknown", "label": "No sources read",
                    "worst_age_seconds": None, "worst_age_label": "age unknown",
                    "unavailable": [], "stale": []}
        down = sorted(r.name for r in results if r.status == UNAVAILABLE)
        stale = sorted(r.name for r in results if r.status == STALE)
        aged = [(r.age_seconds, r.name) for r in results if r.age_seconds is not None]
        worst_age, worst_name = max(aged) if aged else (None, None)
        if down:
            state, label = "critical", f"{len(down)} data source(s) unavailable"
        elif stale:
            state, label = "risk", f"{len(stale)} data source(s) stale"
        else:
            state, label = "ok", "All data sources current"
        return {
            "state": state,
            "label": label,
            "worst_age_seconds": None if worst_age is None else round(worst_age, 1),
            "worst_age_label": humanize_age(worst_age),
            "worst_source": worst_name,
            "unavailable": down,
            "stale": stale,
        }

    # --- concrete sources --------------------------------------------------
    def policy(self) -> SourceResult:
        """platform/policy/ — the same files Terraform reads.

        Always local, always available, and a failure here is a broken checkout
        rather than an outage, so it is reported as unavailable like anything
        else instead of raising through the request.
        """
        if "policy" in self.results:
            return self.results["policy"]
        try:
            import obs_common as oc

            paths = sorted(oc.POLICY_DIR.rglob("*.yaml"))
            signature = tuple((str(p), p.stat().st_mtime) for p in paths)
            newest = max((m for _, m in signature), default=None)
            data = _cached_parse("policy", signature, oc.load_policy)
            return self.record(SourceResult(
                name="policy", origin=ORIGIN_POLICY, data=data,
                produced_at=(dt.datetime.fromtimestamp(newest, dt.timezone.utc)
                             if newest else None),
                detail="platform/policy — read with the same loader as the "
                       "Terraform-facing tooling"))
        except Exception as exc:                                   # noqa: BLE001
            return self.record(SourceResult(
                name="policy", origin=ORIGIN_POLICY, status=UNAVAILABLE,
                error=f"{type(exc).__name__}: {exc}"))

    def report(self, name: str, filename: str) -> SourceResult:
        """A platform report artifact: generated/ first, portal fixture second.

        `generated/` is gitignored and rebuilt by the tooling, so a fresh
        clone legitimately has none. Falling back to the committed fixture keeps
        the portal demonstrable offline, but the origin flips to `fixture` and
        the age is the fixture's age, so nobody mistakes a snapshot from last
        quarter for this morning's governance run.
        """
        if name in self.results:
            return self.results[name]
        live_path = self.settings.generated_dir / filename
        fixture_path = self.settings.fixtures_dir / filename
        for path, origin in ((live_path, ORIGIN_REPORT), (fixture_path, ORIGIN_FIXTURE)):
            if not path.is_file():
                continue
            try:
                data = _cached_parse(
                    f"report:{path}", path.stat().st_mtime,
                    lambda p=path: json.loads(p.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError) as exc:
                return self.record(SourceResult(
                    name=name, origin=origin, status=UNAVAILABLE,
                    error=f"{path.name}: {type(exc).__name__}: {exc}"))
            produced = None
            if isinstance(data, dict):
                produced = _parse_ts(data.get("generated_at"))
            if produced is None:
                produced = dt.datetime.fromtimestamp(path.stat().st_mtime,
                                                     dt.timezone.utc)
            detail = (f"generated/{filename}" if origin == ORIGIN_REPORT
                      else f"portal/fixtures/{filename} — no generated/{filename}; "
                           "run `make coverage` for current numbers")
            return self.record(SourceResult(name=name, origin=origin, data=data,
                                            produced_at=produced, detail=detail))
        return self.record(SourceResult(
            name=name, origin=ORIGIN_REPORT, status=UNAVAILABLE,
            error=f"neither generated/{filename} nor portal/fixtures/{filename} exists"))

    def datadog(self, name: str, filename: str,
                fetcher: Callable[[], Any] | None = None) -> SourceResult:
        """A Datadog read — live when the portal was started with --live.

        In fixture mode the recorded response is returned from disk. Both paths
        hand the SAME payload shape to the adapters in `datadog.py`, so the
        offline mode exercises the real parsing rather than a parallel
        code path that only works in tests.
        """
        if name in self.results:
            return self.results[name]

        if not (self.settings.live and fetcher):
            path = self.settings.fixtures_dir / filename
            try:
                data = _cached_parse(
                    f"fixture:{path}", path.stat().st_mtime,
                    lambda p=path: json.loads(p.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError) as exc:
                return self.record(SourceResult(
                    name=name, origin=ORIGIN_FIXTURE, status=UNAVAILABLE,
                    error=f"{path.name}: {type(exc).__name__}: {exc}"))
            # `_recorded_at` is portal metadata carried inside the recorded
            # response (the underscore marks it as not-from-Datadog; every
            # adapter ignores unknown keys). It is used instead of the file
            # mtime because a git checkout rewrites mtimes, which would make a
            # year-old snapshot claim to be seconds old.
            recorded = _parse_ts(data.get("_recorded_at")) if isinstance(data, dict) else None
            produced = recorded or dt.datetime.fromtimestamp(path.stat().st_mtime,
                                                             dt.timezone.utc)
            detail = f"recorded Datadog response — portal/fixtures/{filename}"
            if self.settings.fixture_replay and recorded:
                data = replay_shift(data, recorded)
                produced = _utcnow()
                detail += " — REPLAY: recorded timestamps shifted onto the current clock"
            # A recorded response is a snapshot, not a live read, and saying so
            # is the difference between a demo and a lie. The status stays OK
            # (the data IS what it claims to be) while origin and detail make
            # the substitution visible on the freshness panel.
            return self.record(SourceResult(
                name=name, origin=ORIGIN_FIXTURE, data=data, produced_at=produced,
                detail=detail))

        cached = self.cache.get(name) if self.cache else None
        if cached is not None:
            data, fetched_at = cached
            return self.record(SourceResult(
                name=name, origin=ORIGIN_DATADOG, data=data,
                produced_at=fetched_at,
                detail=f"cached for up to {self.settings.cache_ttl_seconds}s"))
        try:
            data = fetcher()
        except Exception as exc:                                   # noqa: BLE001
            # Deliberately broad: an upstream can fail with a network error, an
            # auth error, a rate limit or a schema surprise, and the portal's
            # response to all four is identical — say so on the page.
            return self.record(SourceResult(
                name=name, origin=ORIGIN_DATADOG, status=UNAVAILABLE,
                error=f"{type(exc).__name__}: {exc}",
                detail="Datadog read failed — the panels that depend on this "
                       "source show no data rather than a stale or zero value"))
        now = _utcnow()
        if self.cache:
            self.cache.put(name, data, now)
        return self.record(SourceResult(name=name, origin=ORIGIN_DATADOG, data=data,
                                        produced_at=now, detail="live Datadog read"))


class TTLCache:
    """Process-local, bounded-lifetime cache for live Datadog reads only.

    Not a database, not a store of truth, and never consulted in fixture mode.
    It exists solely to keep N open browser tabs from becoming N× the API call
    volume; entries expire, are never persisted, and always carry their fetch
    time so the page can display data age.
    """

    def __init__(self, ttl_seconds: int):
        self.ttl = ttl_seconds
        self._lock = threading.Lock()
        self._entries: dict[str, tuple[Any, dt.datetime, float]] = {}

    def get(self, key: str):
        with self._lock:
            entry = self._entries.get(key)
            if not entry:
                return None
            data, fetched_at, monotonic = entry
            if time.monotonic() - monotonic > self.ttl:
                self._entries.pop(key, None)
                return None
            return data, fetched_at

    def put(self, key: str, data, fetched_at: dt.datetime) -> None:
        with self._lock:
            self._entries[key] = (data, fetched_at, time.monotonic())

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
