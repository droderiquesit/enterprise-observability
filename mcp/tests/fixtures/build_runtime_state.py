#!/usr/bin/env python3
"""Build `runtime_state.json` — the OFFLINE runtime snapshot.

`tests/fixtures/monitors_planned.json` and `tests/fixtures/slos.json` describe
what the platform CONFIGURES. Nothing in the repository describes what is
HAPPENING — monitor states, alert and change events, incidents, agent health,
how often a monitor has fired. Ask mode needs both, so this generates the
second half offline, DERIVED FROM the first half rather than invented beside
it: every monitor id, correlation key, service, team and priority in the
snapshot is copied from a real planned monitor, so an answer grounded in this
file is grounded in the real estate's shape.

Deterministic (seeded), so regenerating produces a byte-identical file and CI
can tell a fixture change from a code change.

    cd mcp/tests/fixtures && python3 build_runtime_state.py

It never touches tests/fixtures/monitors_planned.json — that file is the
Terraform plan's own output and is regenerated only by `make fixtures`.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
PLANNED = REPO_ROOT / "tests" / "fixtures" / "monitors_planned.json"
SLOS = REPO_ROOT / "tests" / "fixtures" / "slos.json"
OUT = HERE / "runtime_state.json"

# A fixed wall-clock anchor. Real timestamps would make the fixture change on
# every regeneration and turn every diff into noise; the tests assert relative
# behaviour, so the absolute instant only has to be stable.
CAPTURED_AT = "2026-08-19T09:00:00+00:00"
CAPTURED_TS = 1787130000          # 2026-08-19T09:00:00Z, epoch seconds
DAY = 86400
WINDOW_DAYS = 30


def tags_to_map(tags):
    out = {}
    for t in tags or []:
        if ":" in t:
            k, v = t.split(":", 1)
            out.setdefault(k, v)
    return out


def build() -> dict:
    rng = random.Random(11)
    monitors = json.loads(PLANNED.read_text())
    slos = json.loads(SLOS.read_text())

    managed = [m for m in monitors if tags_to_map(m.get("tags")).get("managed_by") == "terraform"]

    # --- monitor states ------------------------------------------------------
    # A realistic estate is overwhelmingly OK. Alerting a fifth of 651 monitors
    # would make every "what is unhealthy" answer meaningless.
    states, alerting = {}, []
    for m in managed:
        t = tags_to_map(m.get("tags"))
        roll = rng.random()
        if roll < 0.018 and t.get("env") == "prod":
            state = "Alert"
        elif roll < 0.033:
            state = "Warn"
        elif roll < 0.040:
            state = "No Data"
        else:
            state = "OK"
        groups = {}
        if state in ("Alert", "Warn", "No Data"):
            svc = t.get("service", "unknown")
            n = rng.choice([1, 1, 1, 2, 3])
            groups = {f"service:{svc}-{i:02d}": state for i in range(n)}
            alerting.append((m, t, state))
        states[str(m["id"])] = {
            "overall_state": state,
            "last_triggered_ts": CAPTURED_TS - rng.randint(120, 6 * 3600)
            if state != "OK" else CAPTURED_TS - rng.randint(DAY, 40 * DAY),
            "groups": groups,
        }

    # --- events --------------------------------------------------------------
    # Shaped for tools/correlate_events.correlate(): the same keys the monitor
    # factory stamps onto every monitor are what the correlation rules join on.
    events = []
    for i, (m, t, state) in enumerate(alerting):
        events.append({
            "id": f"evt-{i:04d}",
            "ts": states[str(m["id"])]["last_triggered_ts"],
            "kind": "alert" if state != "No Data" else "alert",
            "title": m.get("name", ""),
            "monitor_id": str(m["id"]),
            "correlation_key": t.get("correlation_key", ""),
            "dedup_key": t.get("dedup_key", ""),
            "priority": (t.get("priority") or "p3").upper(),
            "signal": t.get("signal", "telemetry_health"),
            "domain": t.get("domain", ""),
            "archetype": t.get("archetype", ""),
            "env": t.get("env", "prod"),
            "region": "eastus2",
            "service": t.get("service", ""),
            "team": t.get("team", ""),
            "maintenance": False,
        })

    # Change events. §8 of docs/requirement-traceability.md records that NO
    # pipeline in this org sets DD_VERSION or DD_GIT_COMMIT_SHA, so deployment
    # metadata does not actually reach Datadog today. These three exist so the
    # correlation path is exercised offline; `ask.what_changed` reports the gap
    # regardless of what it finds here.
    for i, svc in enumerate(["api-services", "application-platform", "cloud-platform"]):
        events.append({
            "id": f"chg-{i:04d}",
            "ts": CAPTURED_TS - (900 * (i + 1)),
            "kind": "change",
            "title": f"deployment {svc} v2026.08.19-{i + 1}",
            "monitor_id": None,
            "correlation_key": f"{svc}.prod.{svc}",
            "dedup_key": f"deploy.{svc}.{i}",
            "priority": "P4",
            "signal": "deployment",
            "domain": "application",
            "archetype": "deployment",
            "env": "prod",
            "region": "eastus2",
            "service": svc,
            "team": "sre",
            "maintenance": False,
            "source": "synthetic-change-event",
        })
    events.sort(key=lambda e: e["ts"])

    # --- SLO status ----------------------------------------------------------
    # `overall_status: [{}]` in tests/fixtures/slos.json is correct for a PLAN
    # (a plan has no runtime status). This overlays a plausible burn state so
    # error-budget questions have something to read offline.
    slo_status = {}
    for i, s in enumerate(slos):
        target = 99.9
        if i % 7 == 0:
            sli, budget = 99.62, -0.28          # breaching
        elif i % 5 == 0:
            sli, budget = 99.86, 0.11           # burning
        else:
            sli, budget = 99.97, 0.94
        slo_status[s["id"]] = {
            "sli_value": sli,
            "target": target,
            "timeframe": "30d",
            "error_budget_remaining_pct": round(budget * 100, 2),
            "burn_rate_1h": round(1.0 + (0 if budget > 0.5 else (2.4 if budget > 0 else 9.6)), 2),
            "raw_error_budget_remaining": round(budget * 100, 2),
            "state": "breaching" if budget < 0 else ("burning" if budget < 0.25 else "healthy"),
        }

    # --- incidents -----------------------------------------------------------
    # created/resolved pairs are what MTTR is computed from. Two are resolved,
    # one is still open — an open incident must not be averaged into MTTR.
    incidents = [
        {"id": "INC-4471", "title": "API availability degraded in prod", "severity": "SEV-1",
         "created": CAPTURED_TS - 5 * DAY, "resolved": CAPTURED_TS - 5 * DAY + 4260,
         "services": ["api-services"], "team": "application-development",
         "correlation_key": "api-services.prod.api-services"},
        {"id": "INC-4468", "title": "Cosmos RU throttling, orders region", "severity": "SEV-2",
         "created": CAPTURED_TS - 11 * DAY, "resolved": CAPTURED_TS - 11 * DAY + 9180,
         "services": ["database-platform"], "team": "data-engineering",
         "correlation_key": "database-platform.prod.database-platform"},
        {"id": "INC-4480", "title": "Front Door origin unhealthy", "severity": "SEV-2",
         "created": CAPTURED_TS - 3600, "resolved": None,
         "services": ["cloud-platform"], "team": "cloud-engineering",
         "correlation_key": "cloud-platform.prod.cloud-platform"},
    ]

    # --- hosts / agents ------------------------------------------------------
    hosts = []
    for i in range(24):
        stale = i in (3, 17)
        old_agent = i in (5, 9, 17)
        hosts.append({
            "name": f"vm-app-eastus2-{i:03d}",
            "up": not stale,
            "agent_version": "7.52.0" if old_agent else "7.66.1",
            "last_reported_ts": CAPTURED_TS - (3 * DAY if stale else 45),
            "apps": ["azure", "sqlserver"] if i % 3 == 0 else ["azure"],
            "tags": {"env": "prod", "team": "infrastructure-engineering",
                     "service": f"svc-{i:06d}"},
        })

    # --- monitor activity ----------------------------------------------------
    # Datadog exposes no "how many times did this monitor fire" endpoint; live
    # mode reconstructs this from the event stream, which is why every noise
    # answer states the window it counted over.
    activity = {}
    for m in managed:
        mid = str(m["id"])
        st = states[mid]
        if st["overall_state"] == "OK" and rng.random() < 0.22:
            triggers = 0
            last = None                                     # never fired
        else:
            triggers = rng.choice([0, 1, 1, 2, 3, 4, 6, 9, 14, 31, 47])
            last = st["last_triggered_ts"] if triggers else None
        activity[mid] = {
            "triggers": triggers,
            "flaps": max(0, triggers - rng.randint(0, 4)) if triggers > 6 else 0,
            "last_triggered_ts": last,
        }

    return {
        "_provenance": (
            "Generated by mcp/tests/fixtures/build_runtime_state.py from "
            "tests/fixtures/monitors_planned.json + slos.json. Offline runtime "
            "snapshot for the MCP server; not live data."),
        "captured_at": CAPTURED_AT,
        "captured_ts": CAPTURED_TS,
        "window_days": WINDOW_DAYS,
        "monitor_states": states,
        "slo_status": slo_status,
        "events": events,
        "incidents": incidents,
        "hosts": hosts,
        "integrations": sorted({app for h in hosts for app in h["apps"]}),
        "monitor_activity": activity,
        # EMPTY ON PURPOSE. §28 of docs/requirement-traceability.md: every
        # on-call schedule position in this org is UNASSIGNED. A fabricated
        # roster here would make `ask.who_is_on_call` return a confident lie,
        # which is the single most dangerous answer this server could give.
        "oncall": {},
    }


if __name__ == "__main__":
    OUT.write_text(json.dumps(build(), indent=2, sort_keys=True) + "\n")
    print(f"wrote {OUT}")
