"""Datadog reads, and the adapters that normalise them.

Design rule: the FETCHERS differ between live and fixture mode, the ADAPTERS
never do. A recorded response in `portal/fixtures/` has the same shape as the
API returns, so running offline exercises the same parsing that production
runs. A fixture set that is parsed by a special offline code path proves
nothing about the live one.

Everything here is a GET. There is no POST/PUT/PATCH/DELETE in this package and
no code path that could add one by configuration; the portal cannot mutate the
Datadog org even if the credentials it is given would allow it.

Credentials never leave this module: `obs_common.dd_headers()` reads
DD_API_KEY / DD_APP_KEY from the process environment, the headers go straight
into the request, and no response field derived from them is ever forwarded to
the browser.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

# tools/ is on sys.path via app.config
import obs_common as oc

from .sources import _parse_ts

# How far back the event window reaches. 24h because that is the window an
# executive reads as "today", and because event reduction only means anything
# over a period long enough to contain a storm.
EVENT_WINDOW_SECONDS = 24 * 3600


# -----------------------------------------------------------------------------
# Live fetchers (opt-in; only called when the portal runs with --live)
# -----------------------------------------------------------------------------
def _get(path: str, **params):
    headers = oc.dd_headers()
    r = oc.dd_request("GET", f"{oc.dd_site()}{path}", headers=headers, params=params)
    r.raise_for_status()
    return r.json()


def fetch_slos() -> dict:
    """`GET /api/v1/slo` — the catalog plus `overall_status` per objective."""
    data, offset = [], 0
    while True:
        page = _get("/api/v1/slo", limit=100, offset=offset).get("data", [])
        data.extend(page)
        if len(page) < 100:
            break
        offset += 100
    return {"data": data}


def fetch_incidents() -> dict:
    """`GET /api/v2/incidents` with users included, so a commander has a name."""
    return _get("/api/v2/incidents", **{"page[size]": 50, "include": "commander_user"})


def fetch_events() -> dict:
    """`GET /api/v2/events` — the raw alert signal window.

    This is the numerator of the event-reduction statement: every alert Datadog
    raised, before any correlation. The monitors carry `correlation_key`,
    `dedup_key` and `signal` as tags (stamped by modules/monitor_factory), so
    the whole correlation input is reconstructable from the event tags alone.
    """
    now = int(dt.datetime.now(dt.timezone.utc).timestamp())
    return _get("/api/v2/events",
                **{"filter[from]": str(now - EVENT_WINDOW_SECONDS),
                   "filter[to]": str(now),
                   "filter[query]": "source:alert",
                   "page[limit]": 1000})


def fetch_oncall() -> dict:
    """`GET /api/v2/on-call/schedules` with the current on-call user included."""
    return _get("/api/v2/on-call/schedules", **{"include": "teams,layers",
                                                "page[size]": 100})


def fetch_fleet() -> dict:
    """`GET /api/v1/hosts` — agent presence and version across reporting hosts."""
    return _get("/api/v1/hosts", count=1000, start=0)


def fetch_cost() -> dict:
    """`GET /api/v2/usage/estimated_cost_by_org` — month-to-date observability spend."""
    today = dt.date.today()
    return _get("/api/v2/usage/estimated_cost_by_org",
                start_month=today.replace(day=1).isoformat(),
                view="summary")


LIVE_FETCHERS = {
    "datadog.slos": fetch_slos,
    "datadog.incidents": fetch_incidents,
    "datadog.events": fetch_events,
    "datadog.oncall": fetch_oncall,
    "datadog.fleet": fetch_fleet,
    "datadog.cost": fetch_cost,
}

FIXTURE_FILES = {
    "datadog.slos": "dd_slos.json",
    "datadog.incidents": "dd_incidents.json",
    "datadog.events": "dd_events.json",
    "datadog.oncall": "dd_oncall.json",
    "datadog.fleet": "dd_fleet.json",
    "datadog.cost": "dd_cost.json",
}


# -----------------------------------------------------------------------------
# Adapters — identical for live and recorded payloads
# -----------------------------------------------------------------------------
def parse_slos(payload: Any) -> list[dict]:
    """Datadog SLO objects → the fields an executive view needs.

    `error_budget_remaining` is a PERCENTAGE OF THE BUDGET, not of the SLI, and
    conflating the two is the classic way to report a healthy objective that is
    actually two days from breach. Datadog reports it per timeframe inside
    `overall_status`; the entry matching the SLO's own threshold timeframe is
    the one that means anything.
    """
    rows = []
    for slo in (payload or {}).get("data", []) or []:
        tags = oc.tags_to_map(slo.get("tags") or [])
        thresholds = slo.get("thresholds") or []
        primary_tf = (thresholds[0].get("timeframe") if thresholds else None) or "30d"
        target = thresholds[0].get("target") if thresholds else None

        statuses = slo.get("overall_status") or []
        status = next((s for s in statuses if s.get("timeframe") == primary_tf),
                      statuses[0] if statuses else {})
        sli = status.get("sli_value")
        budget = status.get("error_budget_remaining")
        rows.append({
            "id": slo.get("id"),
            "slo_id": tags.get("slo_id") or slo.get("id"),
            "name": slo.get("name", ""),
            "domain": tags.get("domain", ""),
            "service": tags.get("service", ""),
            "team": tags.get("team") or tags.get("owner", ""),
            "scope": tags.get("scope", "domain"),
            "type": slo.get("type", ""),
            "timeframe": primary_tf,
            "target": target if target is not None else status.get("target"),
            "sli": sli,
            "error_budget_remaining_pct": budget,
            # A status entry that carries an `error` is Datadog telling us the
            # objective cannot be computed — silent telemetry, a deleted member
            # monitor, an unparseable query. It is NOT a healthy SLO and must
            # never be counted as one.
            "error": status.get("error"),
            "raw_status": status,
        })
    return sorted(rows, key=lambda r: (r["domain"], r["name"]))


def _index_included(payload: dict) -> dict:
    out = {}
    for item in (payload or {}).get("included", []) or []:
        out[(item.get("type"), item.get("id"))] = item.get("attributes", {}) or {}
    return out


def parse_incidents(payload: Any) -> list[dict]:
    """Datadog Incidents v2 → the six things an executive asks about an incident.

    severity, business impact, probable cause, how long it has been running,
    who is commanding it and who owns the service. Anything the API does not
    carry is returned as an empty string and rendered as "not recorded" — the
    portal does not guess a root cause.
    """
    included = _index_included(payload)
    rows = []
    for inc in (payload or {}).get("data", []) or []:
        attrs = inc.get("attributes", {}) or {}
        fields = attrs.get("fields", {}) or {}

        def field(name, default=""):
            value = (fields.get(name) or {}).get("value", default)
            if isinstance(value, list):
                return ", ".join(str(v) for v in value)
            return value if value is not None else default

        commander = ""
        rel = ((inc.get("relationships") or {}).get("commander_user") or {}).get("data")
        if rel:
            commander = (included.get(("users", rel.get("id")), {}).get("name")
                         or included.get(("users", rel.get("id")), {}).get("handle", ""))
        commander = commander or (attrs.get("commander_user") or {}).get("name", "")

        created = _parse_ts(attrs.get("created"))
        detected = _parse_ts(attrs.get("detected")) or created
        resolved = _parse_ts(attrs.get("resolved"))
        end = resolved or dt.datetime.now(dt.timezone.utc)
        duration = (end - created).total_seconds() if created else None

        state = (attrs.get("state") or "").lower()
        rows.append({
            "id": inc.get("id"),
            "public_id": attrs.get("public_id"),
            "title": attrs.get("title", ""),
            "severity": (attrs.get("severity") or "UNKNOWN").upper(),
            "state": state,
            "active": state not in ("resolved", "completed", "stable"),
            "customer_impacted": bool(attrs.get("customer_impacted")),
            "impact": field("impact") or attrs.get("customer_impact_scope", ""),
            "probable_cause": field("root_cause"),
            "services": field("services"),
            "teams": field("teams"),
            "commander": commander,
            "created": created,
            "detected": detected,
            "resolved": resolved,
            "duration_seconds": duration,
            "time_to_detect_seconds": (
                (detected - created).total_seconds() if created and detected else None),
            "time_to_resolve_seconds": (
                (resolved - created).total_seconds() if created and resolved else None),
            "correlation_key": field("correlation_key"),
        })
    return sorted(rows, key=lambda r: (r["created"] or dt.datetime.min.replace(
        tzinfo=dt.timezone.utc)), reverse=True)


def parse_events(payload: Any) -> list[dict]:
    """Datadog alert events → the input `tools/correlate_events.correlate()` takes.

    Every field the correlator needs is already a monitor tag, because
    modules/monitor_factory stamps `correlation_key`, `dedup_key`, `signal`,
    `domain`, `env`, `region` and `service` on all 651 monitors. That is what
    makes the reduction number on the home page a MEASUREMENT of the deployed
    estate rather than a marketing figure: the same keys the platform ships are
    the keys being grouped on here.
    """
    signals = []
    for event in (payload or {}).get("data", []) or []:
        attrs = event.get("attributes", {}) or {}
        tags = oc.tags_to_map(attrs.get("tags") or [])
        inner = attrs.get("attributes", {}) or {}
        ts = _parse_ts(attrs.get("timestamp") or inner.get("timestamp"))
        if not tags.get("correlation_key") or not tags.get("dedup_key"):
            # An alert from a monitor this platform does not manage cannot be
            # correlated by key. It is still a raw signal (it counts in the
            # numerator) but it is passed through as its own group, which is
            # exactly what happens in Datadog.
            tags.setdefault("correlation_key",
                            f"unmanaged.{tags.get('env', 'unknown')}.{event.get('id')}")
            tags.setdefault("dedup_key", f"unmanaged.{event.get('id')}")
        status = (inner.get("status") or "").lower()
        evt_type = ((inner.get("evt") or {}).get("type") or "").lower()
        kind = ("recovery" if status in ("ok", "success", "recovery")
                else "change" if evt_type in ("deployment", "change") or
                tags.get("source_kind") == "change"
                else "alert")
        signals.append({
            "ts": ts.timestamp() if ts else 0.0,
            "correlation_key": tags["correlation_key"],
            "dedup_key": tags["dedup_key"],
            "priority": (tags.get("priority") or "p3").upper(),
            "signal": tags.get("signal", "telemetry_health"),
            "domain": tags.get("domain", ""),
            "env": tags.get("env", "prod"),
            "region": tags.get("region", "global"),
            "service": tags.get("service", ""),
            "archetype": tags.get("archetype", ""),
            "pack": tags.get("pack", ""),
            "kind": kind,
            "title": (inner.get("monitor") or {}).get("name") or attrs.get("title", ""),
            "monitor_id": (inner.get("monitor") or {}).get("id"),
            "maintenance": tags.get("maintenance") == "true",
            "tier": tags.get("tier", ""),
            "team": tags.get("team", ""),
        })
    return signals


def parse_oncall(payload: Any) -> dict:
    """On-call schedules and — the number that actually matters — occupancy.

    §28 of the requirement audit records that the schedules exist and the
    ROSTERS ARE EMPTY, so a page reaches nobody. That is precisely the kind of
    fact a coverage tile must show rather than round up to "on-call configured".
    """
    included = _index_included(payload)
    schedules = []
    for item in (payload or {}).get("data", []) or []:
        attrs = item.get("attributes", {}) or {}
        rels = item.get("relationships", {}) or {}
        members = []
        for layer in (rels.get("layers") or {}).get("data", []) or []:
            layer_attrs = included.get(("layers", layer.get("id")), {})
            members.extend(layer_attrs.get("members") or [])
        team_ids = [t.get("id") for t in ((rels.get("teams") or {}).get("data") or [])]
        team_names = [included.get(("teams", tid), {}).get("handle")
                      or included.get(("teams", tid), {}).get("name") or tid
                      for tid in team_ids]
        schedules.append({
            "id": item.get("id"),
            "name": attrs.get("name", ""),
            "teams": [t for t in team_names if t],
            "member_count": len(members),
            "current_oncall": attrs.get("current_oncall") or "",
        })
    staffed = [s for s in schedules if s["member_count"] > 0]
    return {
        "schedules": schedules,
        "total": len(schedules),
        "staffed": len(staffed),
        "unstaffed": [s["name"] for s in schedules if s["member_count"] == 0],
    }


def parse_fleet(payload: Any) -> dict:
    """Agent presence across reporting hosts.

    Note what this CANNOT answer: hosts that have no agent do not appear in
    `/api/v1/hosts`, so the denominator "how many hosts should have an agent"
    is not obtainable from Datadog. §36/§39 record that fleet management is not
    implemented in this platform, so the portal reports the numerator and says
    the denominator is uninstrumented instead of dividing by a number it made
    up.
    """
    hosts = (payload or {}).get("host_list", []) or []
    total = (payload or {}).get("total_returned", len(hosts))
    versions: dict[str, int] = {}
    reporting = up_to_date = 0
    for host in hosts:
        meta = host.get("meta", {}) or {}
        version = meta.get("agent_version") or "unknown"
        versions[version] = versions.get(version, 0) + 1
        if host.get("up"):
            reporting += 1
    newest = max((v for v in versions if v and v != "unknown"), default=None)
    if newest:
        up_to_date = versions.get(newest, 0)
    return {
        "hosts_known": total,
        "hosts_reporting": reporting,
        "agent_versions": dict(sorted(versions.items())),
        "newest_agent_version": newest,
        "hosts_on_newest": up_to_date,
        "expected_hosts": (payload or {}).get("expected_hosts"),
    }


def parse_cost(payload: Any) -> dict:
    """Month-to-date observability spend and a straight-line month-end forecast.

    Straight-line, and labelled as such on the page: a linear run-rate is the
    only projection defensible from a single month's daily totals, and dressing
    it up as a model would be false precision in front of a budget holder.
    """
    entries = []
    for item in (payload or {}).get("data", []) or []:
        attrs = item.get("attributes", {}) or {}
        entries.append({
            "date": attrs.get("date") or attrs.get("month"),
            "total": attrs.get("total_cost"),
            "charges": attrs.get("charges") or [],
        })
    entries = [e for e in entries if e["total"] is not None]
    if not entries:
        return {"month_to_date": None, "forecast": None, "by_product": {}, "days": 0}
    entries.sort(key=lambda e: str(e["date"]))
    latest = entries[-1]
    mtd = float(latest["total"])
    day = int(str(latest["date"])[-2:]) if str(latest["date"])[-2:].isdigit() else len(entries)
    days_in_month = 30
    forecast = mtd / day * days_in_month if day else None
    by_product: dict[str, float] = {}
    for charge in latest["charges"]:
        name = charge.get("product_name", "other")
        by_product[name] = by_product.get(name, 0.0) + float(charge.get("cost") or 0)
    return {
        "month_to_date": round(mtd, 2),
        "forecast": round(forecast, 2) if forecast else None,
        "by_product": {k: round(v, 2) for k, v in sorted(
            by_product.items(), key=lambda kv: -kv[1])},
        "days": day,
        "as_of": latest["date"],
    }


# -----------------------------------------------------------------------------
# Deep links (§48) — the portal answers "what and how bad"; Datadog answers
# "show me the graph". Every drilldown ends in a real Datadog URL rather than a
# reimplementation of a Datadog view.
# -----------------------------------------------------------------------------
def monitor_url(app_url: str, monitor_id) -> str:
    return f"{app_url}/monitors/{monitor_id}"


def slo_url(app_url: str, slo_id: str) -> str:
    from urllib.parse import quote

    return f"{app_url}/slo?query={quote(f'slo_id:{slo_id}')}"


def incident_url(app_url: str, public_id) -> str:
    return f"{app_url}/incidents/{public_id}"


def event_url(app_url: str, correlation_key: str) -> str:
    from urllib.parse import quote

    return f"{app_url}/event/explorer?query={quote(f'tags:correlation_key:{correlation_key}')}"


def service_url(app_url: str, service: str) -> str:
    from urllib.parse import quote

    return f"{app_url}/services/{quote(service)}"
