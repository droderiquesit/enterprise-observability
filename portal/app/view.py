"""The executive view model — §47 home view and §48 progressive drilldown.

This module turns sources into sentences. Its whole job is to answer, in the
order an executive actually asks:

    Is anything broken right now?  →  Are we meeting our promises?
    →  What is about to break?     →  Do we even have eyes on it?

Two rules govern every function here:

  1. NOTHING IS INVENTED. If a source is down or a number is not instrumented,
     the field comes back `unknown` with the reason attached. There is no
     default, no zero and no last-known-good.

  2. DEFINITIONS TRAVEL WITH THE NUMBER. Every measure carries a `note`
     stating how it was computed and from what, because the audience cannot
     inspect the query and should not have to trust the tile.
"""
from __future__ import annotations

import datetime as dt
from collections import Counter, defaultdict

import correlate_events                                   # tools/ — see config
import obs_common as oc

from . import datadog as dd
from .sources import SourceRegistry, measure, rollup, unknown, worst_state

# Error-budget thresholds. tiers.yaml states the consequence at 25% ("feature
# freeze until the budget recovers above 25%"), so that is the line the portal
# draws too — the page must not disagree with the policy the org signed up to.
BUDGET_RISK_PCT = 25.0
BUDGET_WATCH_PCT = 50.0

# "Critical system" is a policy statement, not a portal opinion:
# tiers.yaml → tier1.slo.objectives.availability. Anything promising at least
# this much availability is business-critical by the org's own definition.
TIER1_AVAILABILITY_TARGET = 99.9

SEVERITY_STATE = {"SEV-1": "critical", "SEV-2": "risk", "SEV-3": "watch",
                  "SEV-4": "neutral", "SEV-5": "neutral", "UNKNOWN": "watch"}


def _mean(values):
    values = [v for v in values if isinstance(v, (int, float))]
    return sum(values) / len(values) if values else None


def _fmt_duration(seconds) -> str:
    if seconds is None:
        return "—"
    seconds = int(max(0, seconds))
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h {(seconds % 3600) // 60}m"
    return f"{seconds // 86400}d {(seconds % 86400) // 3600}h"


class ExecutiveView:
    """Builds every payload the portal serves, from one SourceRegistry.

    One instance per HTTP request. Sources are read lazily and memoised on the
    registry, so a page that needs incidents twice fetches them once, and a
    drilldown that needs nothing from Datadog never calls Datadog.
    """

    def __init__(self, registry: SourceRegistry):
        self.reg = registry
        self.app_url = registry.settings.dd_app_site.rstrip("/")

    # -- source accessors ---------------------------------------------------
    def _policy(self):
        return self.reg.policy()

    def _dd(self, name: str):
        return self.reg.datadog(name, dd.FIXTURE_FILES[name], dd.LIVE_FETCHERS.get(name))

    def _coverage(self):
        return self.reg.report("report.coverage", "coverage_report.json")

    def _reconciliation(self):
        return self.reg.report("report.reconciliation", "monitor_reconciliation.json")

    def _scorecard(self):
        return self.reg.report("report.scorecard", "scorecard.json")

    # -- derived collections ------------------------------------------------
    def slos(self) -> tuple[list[dict], str | None]:
        """Live SLO status, enriched with the objective's declared intent.

        Datadog knows the current SLI; `platform/policy/slos.yaml` knows what
        the objective is FOR — which service, which domain, which team, and
        whether it is domain-scoped or per-service. Joining them is what turns
        "99.2%" into "the API availability promise, owned by Application
        Development, is 0.75 points under target".
        """
        src = self._dd("datadog.slos")
        if not src.ok:
            return [], src.error or "SLO status unavailable"
        catalog = (self._policy().data or {}).get("slos", {}) if self._policy().ok else {}
        rows = []
        for row in dd.parse_slos(src.data):
            declared = catalog.get(row["slo_id"], {})
            row = dict(row)
            row["declared_target"] = declared.get("target")
            row["domain"] = row["domain"] or declared.get("domain", "")
            row["service"] = row["service"] or declared.get("service", "")
            row["team"] = row["team"] or declared.get("team", "")
            row["burn_alerts"] = declared.get("burn_alerts", [])
            row["telemetry_dependency"] = declared.get("telemetry_dependency")
            row["state"], row["state_reason"] = _slo_state(row)
            row["link"] = dd.slo_url(self.app_url, row["slo_id"])
            rows.append(row)
        return rows, None

    def incidents(self) -> tuple[list[dict], str | None]:
        src = self._dd("datadog.incidents")
        if not src.ok:
            return [], src.error or "incident feed unavailable"
        rows = []
        for inc in dd.parse_incidents(src.data):
            inc = dict(inc)
            inc["state_class"] = SEVERITY_STATE.get(inc["severity"], "watch")
            inc["duration_label"] = _fmt_duration(inc["duration_seconds"])
            inc["link"] = (dd.incident_url(self.app_url, inc["public_id"])
                           if inc["public_id"] else None)
            rows.append(inc)
        return rows, None

    def correlation(self) -> tuple[dict, str | None]:
        """Raw signals → correlated events → incidents, measured not asserted.

        The grouping is performed by `tools/correlate_events.py` — the same
        module CI runs as the platform's executable correlation specification.
        The portal deliberately does NOT reimplement the reduction: if the
        rules change, this number changes with them, and if the rules are
        wrong, the test suite fails before the executive sees a number.
        """
        src = self._dd("datadog.events")
        if not src.ok:
            return {}, src.error or "event stream unavailable"
        signals = dd.parse_events(src.data)
        alerts = [s for s in signals if s["kind"] == "alert" and not s["maintenance"]]
        try:
            groups = correlate_events.correlate(signals)
        except Exception as exc:                                   # noqa: BLE001
            return {}, f"correlation failed: {type(exc).__name__}: {exc}"
        incidents = [g for g in groups if g.get("creates_incident")]
        return {
            "signals": signals,
            "raw": len(alerts),
            "groups": groups,
            "correlated": len(groups),
            "incidents": len(incidents),
            "paging": sum(g.get("pages", 0) for g in groups),
        }, None

    def services(self) -> dict:
        """The service model: registered services first, platform systems second.

        Two populations, and conflating them would misreport both:
          * REGISTERED services (`platform/services/*.yaml`) declare a business
            tier. That declaration is the input to everything in tiers.yaml.
          * PLATFORM systems (the `service` of each domain SLO) are the shared
            systems the domain objectives are written against. They carry an
            objective, not a declared tier.
        """
        out: dict[str, dict] = {}
        policy = self._policy()
        if not policy.ok:
            return out
        try:
            registered = oc.load_services()
        except Exception:                                          # noqa: BLE001
            registered = {}
        for name, svc in registered.items():
            out[name] = {
                "name": name, "kind": "registered_service",
                "tier": svc.get("tier", ""), "team": svc.get("team", ""),
                "domain": "", "description": svc.get("description", ""),
                "envs": svc.get("envs", []), "dependencies": svc.get("dependencies", []),
                "links": svc.get("links", []),
            }
        for slo_id, slo in (policy.data.get("slos") or {}).items():
            name = slo.get("service")
            if not name:
                continue
            entry = out.setdefault(name, {
                "name": name, "kind": "platform_system", "tier": "",
                "team": slo.get("team", ""), "domain": slo.get("domain", ""),
                "description": "", "envs": ["prod"], "dependencies": [], "links": [],
            })
            entry.setdefault("slo_ids", []).append(slo_id)
            entry["domain"] = entry["domain"] or slo.get("domain", "")
            entry["team"] = entry["team"] or slo.get("team", "")
        return out

    # -----------------------------------------------------------------------
    # §47 — the home view
    # -----------------------------------------------------------------------
    def overview(self) -> dict:
        slos, slo_err = self.slos()
        incidents, inc_err = self.incidents()
        reduction, red_err = self.correlation()

        health = self._health(slos, slo_err, incidents, inc_err)
        payload = {
            "generated_at": dt.datetime.now(dt.timezone.utc).isoformat().replace(
                "+00:00", "Z"),
            "health": health,
            "reliability": self._reliability(slos, slo_err, incidents, inc_err),
            "risk": self._risk(slos, slo_err, incidents, inc_err, reduction, red_err),
            "coverage": self._coverage_panel(),
            "event_reduction": self._event_reduction(reduction, red_err),
            "active_incidents": self._active_incidents(incidents, inc_err, reduction),
            "systems": self.systems(slos, incidents),
        }
        payload["sources"] = self.reg.sources()
        payload["freshness"] = self.reg.freshness()
        # The headline cannot be greener than the data behind it. A source
        # outage degrades the overall statement even when every number the
        # portal DID obtain looks fine — otherwise the page reassures precisely
        # when it should not.
        payload["health"]["overall"]["state"] = worst_state([
            payload["health"]["overall"]["state"],
            "unknown" if payload["freshness"]["unavailable"] else "ok",
        ])
        payload["health"]["overall"]["label"] = _overall_label(
            payload["health"]["overall"]["state"])
        if payload["freshness"]["unavailable"]:
            payload["health"]["overall"]["note"] = (
                "Part of the estate is not visible: "
                + ", ".join(payload["freshness"]["unavailable"])
                + ". This status is incomplete.")
        return payload

    # -- enterprise health --------------------------------------------------
    def _health(self, slos, slo_err, incidents, inc_err) -> dict:
        active = [i for i in incidents if i["active"]]
        p1 = [i for i in active if i["severity"] == "SEV-1"]
        p2 = [i for i in active if i["severity"] == "SEV-2"]

        systems = self.systems(slos, incidents)
        critical = [s for s in systems if s["critical"]]
        degraded = [s for s in systems if s["state"] in ("critical", "risk", "watch")]
        blind = [s for s in systems if s["state"] == "unknown"]

        contributions = [s["state"] for s in systems]
        contributions += [SEVERITY_STATE.get(i["severity"], "watch") for i in active]
        if slo_err or inc_err:
            contributions.append("unknown")
        overall, blind_count = rollup(contributions)

        return {
            "overall": {
                "state": overall,
                "label": _overall_label(overall),
                "note": _overall_note(overall, len(p1), len(p2), len(degraded),
                                      len(blind)),
                "blind_spots": blind_count,
            },
            "tier1": (unknown(slo_err, source="datadog.slos") if slo_err else measure(
                f"{len([s for s in critical if s['state'] == 'ok'])}/{len(critical)}",
                state=worst_state([s["state"] for s in critical]) if critical else "ok",
                label=("All critical systems healthy"
                       if all(s["state"] == "ok" for s in critical) and critical
                       else f"{len([s for s in critical if s['state'] != 'ok'])} "
                            "critical system(s) not healthy"),
                note="Critical = a tier-0/tier-1 registered service, or a platform "
                     f"system whose availability objective is {TIER1_AVAILABILITY_TARGET}% "
                     "or better (platform/policy/tiers.yaml → tier1)",
                source="datadog.slos + platform/policy")),
            "critical_systems": [
                {"id": s["id"], "name": s["name"], "state": s["state"],
                 "label": s["label"], "reason": s["reason"]}
                for s in critical],
            "degraded_services": [
                {"id": s["id"], "name": s["name"], "state": s["state"],
                 "label": s["label"], "reason": s["reason"]}
                for s in sorted(degraded, key=lambda x: x["state"])],
            "not_visible": [{"id": s["id"], "name": s["name"], "reason": s["reason"]}
                            for s in blind],
            "incidents": {
                "p1": (unknown(inc_err, source="datadog.incidents") if inc_err
                       else measure(len(p1), state="critical" if p1 else "ok",
                                    label=("P1 major incident in progress" if p1
                                           else "No P1 incidents"),
                                    note="Datadog SEV-1 — policy: page, 24x7, "
                                         "incident commander on the bridge "
                                         "(priorities.yaml → P1)",
                                    source="datadog.incidents")),
                "p2": (unknown(inc_err, source="datadog.incidents") if inc_err
                       else measure(len(p2), state="risk" if p2 else "ok",
                                    label=(f"{len(p2)} P2 degradation(s)" if p2
                                           else "No P2 incidents"),
                                    note="Datadog SEV-2 — serious degradation, rapid "
                                         "engineering response (priorities.yaml → P2)",
                                    source="datadog.incidents")),
            },
        }

    # -- reliability --------------------------------------------------------
    def _reliability(self, slos, slo_err, incidents, inc_err) -> dict:
        if slo_err:
            slo_block = {k: unknown(slo_err, source="datadog.slos")
                         for k in ("attainment", "error_budget", "availability")}
        else:
            met = [s for s in slos if s["sli"] is not None and s["target"] is not None
                   and s["sli"] >= s["target"]]
            computable = [s for s in slos if s["error"] is None and s["sli"] is not None]
            broken = [s for s in slos if s["error"] or s["sli"] is None]
            pct = (100.0 * len(met) / len(computable)) if computable else None

            budgets = [s for s in computable
                       if isinstance(s["error_budget_remaining_pct"], (int, float))]
            exhausted = [s for s in budgets if s["error_budget_remaining_pct"] <= 0]
            at_risk = [s for s in budgets
                       if 0 < s["error_budget_remaining_pct"] < BUDGET_RISK_PCT]

            avail = [s for s in computable if "availability" in s["slo_id"]]
            avail_mean = _mean([s["sli"] for s in avail])

            slo_block = {
                "attainment": (measure(
                    round(pct, 1), unit="%",
                    state=("ok" if pct >= 100 else "watch" if pct >= 90 else "risk"),
                    label=f"{len(met)} of {len(computable)} objectives met",
                    note=(f"{len(broken)} objective(s) cannot be computed and are "
                          "excluded from this ratio" if broken else
                          "every declared objective is computable"),
                    source="datadog.slos")
                    if pct is not None else
                    unknown("no objective returned a computable SLI",
                            source="datadog.slos")),
                "error_budget": measure(
                    f"{len(exhausted)} exhausted · {len(at_risk)} under "
                    f"{BUDGET_RISK_PCT:.0f}%",
                    state=("critical" if exhausted else "risk" if at_risk else "ok"),
                    label=("Error budget exhausted" if exhausted
                           else "Error budget under pressure" if at_risk
                           else "Error budgets healthy"),
                    note="Budget exhausted → feature freeze for the owning team until "
                         "it recovers above 25% (tiers.yaml → error_budget_policy)",
                    source="datadog.slos"),
                "availability": (measure(
                    round(avail_mean, 3), unit="%",
                    state=("ok" if avail_mean >= TIER1_AVAILABILITY_TARGET
                           else "risk" if avail_mean >= 99.0 else "critical"),
                    label=f"Mean of {len(avail)} availability objectives",
                    note="Unweighted mean of the availability SLIs over their own "
                         "30-day windows; per-system figures are in the drilldown",
                    source="datadog.slos")
                    if avail_mean is not None else
                    unknown("no availability objective returned an SLI",
                            source="datadog.slos")),
            }

        if inc_err:
            inc_block = {k: unknown(inc_err, source="datadog.incidents")
                         for k in ("mttr", "mttd", "trend")}
        else:
            resolved = [i for i in incidents if i["resolved"]]
            mttr = _mean([i["time_to_resolve_seconds"] for i in resolved])
            mttd = _mean([i["time_to_detect_seconds"] for i in incidents
                          if i["time_to_detect_seconds"] is not None])
            inc_block = {
                "mttr": (measure(_fmt_duration(mttr), state="neutral",
                                 label="Mean time to resolve",
                                 note=f"Mean over {len(resolved)} resolved incident(s) "
                                      "in the feed; open incidents are excluded because "
                                      "their resolution time is not yet a fact",
                                 source="datadog.incidents")
                         if mttr is not None else
                         unknown("no resolved incident in the window",
                                 source="datadog.incidents")),
                "mttd": (measure(_fmt_duration(mttd), state="neutral",
                                 label="Mean time to detect",
                                 note="Incident creation → detection timestamp, as "
                                      "recorded by Datadog Incident Management",
                                 source="datadog.incidents")
                         if mttd is not None else
                         unknown("no incident carries a detection timestamp",
                                 source="datadog.incidents")),
                "trend": self._incident_trend(incidents),
            }
        return {**slo_block, **inc_block}

    def _incident_trend(self, incidents) -> dict:
        """Incidents per week for the last six weeks, plus the direction."""
        now = dt.datetime.now(dt.timezone.utc)
        buckets = [0] * 6
        for inc in incidents:
            if not inc["created"]:
                continue
            weeks = int((now - inc["created"]).total_seconds() // (7 * 86400))
            if 0 <= weeks < 6:
                buckets[5 - weeks] += 1
        if not any(buckets):
            return unknown("no incident in the last six weeks carries a timestamp",
                           source="datadog.incidents")
        recent, prior = sum(buckets[3:]), sum(buckets[:3])
        direction = ("rising" if recent > prior else
                     "falling" if recent < prior else "flat")
        state = {"rising": "risk", "falling": "ok", "flat": "neutral"}[direction]
        payload = measure(
            direction, state=state,
            label=f"Incidents {direction}: {prior} → {recent} per 3 weeks",
            note="Count of incidents opened, bucketed by week, last six weeks",
            source="datadog.incidents")
        payload["series"] = buckets
        return payload

    # -- risk ---------------------------------------------------------------
    def _risk(self, slos, slo_err, incidents, inc_err, reduction, red_err) -> dict:
        return {
            "slo_breach_forecast": self._breach_forecast(slos, slo_err),
            "recurring_issues": self._recurring(reduction, red_err),
            "capacity": self._capacity(reduction, red_err),
            "fleet": self._fleet_risk(),
            "telemetry_gaps": self._telemetry_gaps(slos, slo_err),
            "cost": self._cost_risk(),
        }

    def _breach_forecast(self, slos, slo_err) -> dict:
        if slo_err:
            return unknown(slo_err, source="datadog.slos")
        forecasts = []
        for slo in slos:
            budget = slo["error_budget_remaining_pct"]
            if not isinstance(budget, (int, float)) or slo["error"]:
                continue
            days = _days_to_exhaustion(budget, slo["timeframe"])
            if days is None or days > 30:
                continue
            forecasts.append({
                "slo_id": slo["slo_id"], "name": slo["name"],
                "service": slo["service"], "domain": slo["domain"],
                "team": slo["team"], "days": round(days, 1),
                "budget_remaining_pct": round(budget, 1),
                "link": slo["link"],
            })
        forecasts.sort(key=lambda f: f["days"])
        soonest = forecasts[0]["days"] if forecasts else None
        payload = measure(
            len(forecasts),
            state=("critical" if soonest is not None and soonest <= 3
                   else "risk" if forecasts else "ok"),
            label=(f"{len(forecasts)} objective(s) forecast to breach within 30 days"
                   if forecasts else "No objective forecast to breach within 30 days"),
            note="Straight-line projection at the last 30 days' average burn rate — "
                 "a trend, not a prediction. It assumes today's burn continues and "
                 "ignores planned work",
            source="datadog.slos")
        payload["items"] = forecasts[:8]
        return payload

    def _recurring(self, reduction, red_err) -> dict:
        if red_err:
            return unknown(red_err, source="datadog.events")
        counts = Counter(g["correlation_key"].split("#")[0]
                         for g in reduction.get("groups", []))
        repeats = [{"correlation_key": k, "occurrences": n,
                    "link": dd.event_url(self.app_url, k)}
                   for k, n in counts.most_common() if n > 1]
        payload = measure(
            len(repeats),
            state=("risk" if any(r["occurrences"] >= 3 for r in repeats)
                   else "watch" if repeats else "ok"),
            label=(f"{len(repeats)} failure pattern(s) recurred in 24h"
                   if repeats else "No repeating failure pattern in 24h"),
            note="A correlation key that opened more than one group in the window: "
                 "the same failure returning, not one long failure",
            source="datadog.events")
        payload["items"] = repeats[:8]
        return payload

    def _capacity(self, reduction, red_err) -> dict:
        """Capacity pressure = the predictive monitors that are actually firing.

        This platform is predictive-first: forecast and anomaly archetypes exist
        specifically to fire BEFORE the resource runs out. So capacity risk is
        not modelled here — it is read off the monitors that were built to
        answer it (global.yaml → detection_policy.predictive_functions).
        """
        if red_err:
            return unknown(red_err, source="datadog.events")
        policy = self._policy()
        forecast_archetypes = set()
        if policy.ok:
            for aid, arch in (policy.data.get("archetypes") or {}).items():
                if str(arch.get("detection", "")).startswith(("forecast", "predict")):
                    forecast_archetypes.add(aid)
        firing = [s for s in reduction.get("signals", [])
                  if s["kind"] == "alert" and s["archetype"] in forecast_archetypes]
        services = sorted({s["service"] for s in firing if s["service"]})
        payload = measure(
            len(services),
            state=("risk" if len(services) >= 3 else "watch" if services else "ok"),
            label=(f"{len(services)} system(s) forecast to exhaust a resource"
                   if services else "No capacity forecast alerting"),
            note=f"Distinct systems with a firing predictive monitor in 24h, across "
                 f"{len(forecast_archetypes)} forecast archetypes",
            source="datadog.events + platform/policy")
        payload["items"] = [{"service": s} for s in services[:8]]
        return payload

    def _fleet_risk(self) -> dict:
        """Agent and fleet gaps — including the gap in knowing the gap.

        §36/§39 of the requirement audit record that fleet management is not
        implemented: nothing declares which hosts are REQUIRED to run an agent.
        Datadog can only show hosts that are already reporting, so a compliance
        percentage computed from this source would have the answer built into
        the question. The portal reports what is knowable and names what is not.
        """
        src = self._dd("datadog.fleet")
        if not src.ok:
            return unknown(src.error or "host inventory unavailable",
                           source="datadog.fleet")
        fleet = dd.parse_fleet(src.data)
        expected = fleet.get("expected_hosts")
        versions = fleet["agent_versions"]
        drifted = fleet["hosts_known"] - fleet["hosts_on_newest"]
        if expected:
            state = "risk" if fleet["hosts_known"] < expected else "ok"
            label = f"{fleet['hosts_known']} of {expected} expected hosts reporting"
        else:
            state = "watch"
            label = f"{fleet['hosts_known']} hosts reporting; required fleet not declared"
        payload = measure(
            fleet["hosts_known"], state=state, label=label,
            note="Datadog lists hosts that ALREADY report. Nothing in this platform "
                 "declares which hosts must run an agent (requirement §36/§39 — fleet "
                 "management not implemented), so no compliance percentage is claimed",
            source="datadog.fleet")
        payload["detail"] = {
            "reporting": fleet["hosts_reporting"],
            "newest_agent_version": fleet["newest_agent_version"],
            "hosts_on_newest": fleet["hosts_on_newest"],
            "hosts_behind": drifted,
            "versions": versions,
        }
        return payload

    def _telemetry_gaps(self, slos, slo_err) -> dict:
        """Signals the business asked for that nothing currently emits."""
        items = []
        cov = self._coverage()
        if cov.ok:
            for finding in (cov.data.get("checks", {}) or {}).get("C13", []):
                if isinstance(finding, dict) and finding.get("slo_id"):
                    items.append({"kind": "declared_dependency",
                                  "id": finding["slo_id"],
                                  "detail": finding.get("problem", "")})
        if not slo_err:
            for slo in slos:
                if slo["error"]:
                    items.append({"kind": "objective_uncomputable",
                                  "id": slo["slo_id"], "detail": slo["error"]})
        if not cov.ok and slo_err:
            return unknown("neither the coverage report nor SLO status is available",
                           source="report.coverage")
        uncomputable = [i for i in items if i["kind"] == "objective_uncomputable"]
        payload = measure(
            len(items),
            state=("critical" if uncomputable else "watch" if items else "ok"),
            label=(f"{len(items)} declared telemetry gap(s)" if items
                   else "No declared telemetry gap"),
            note="A gap is NAMED and owned, not hidden: docs/telemetry-gaps.md holds "
                 "the emission contract for each. An objective that cannot be computed "
                 "counts as a gap, never as a pass",
            source="report.coverage + datadog.slos")
        payload["items"] = items[:8]
        return payload

    def _cost_risk(self) -> dict:
        src = self._dd("datadog.cost")
        if not src.ok:
            return unknown(src.error or "usage/cost API unavailable",
                           source="datadog.cost")
        cost = dd.parse_cost(src.data)
        if cost["month_to_date"] is None:
            return unknown("the cost endpoint returned no billable day",
                           source="datadog.cost")
        payload = measure(
            cost["forecast"], unit="USD", state="neutral",
            label=f"Month-end forecast · {cost['month_to_date']:,.0f} spent "
                  f"to day {cost['days']}",
            note="Straight-line run-rate from month-to-date spend. Datadog's own "
                 "estimated-cost endpoint; not a contractual figure",
            source="datadog.cost")
        payload["detail"] = {"month_to_date": cost["month_to_date"],
                             "by_product": cost["by_product"],
                             "as_of": cost["as_of"]}
        return payload

    # -- coverage (§47) -----------------------------------------------------
    def _coverage_panel(self) -> dict:
        cov, recon = self._coverage(), self._reconciliation()
        out: dict[str, dict] = {}

        if cov.ok:
            summary = cov.data.get("summary", {}) or {}
            checks = summary.get("check_counts", {}) or {}
            total = summary.get("resources_total") or 0
            unowned = checks.get("C2", 0)
            owned_pct = (100.0 * (total - unowned) / total) if total else None
            out["ownership"] = (measure(
                round(owned_pct, 1), unit="%",
                state=("ok" if unowned == 0 else "risk"),
                label=f"{total - unowned:,} of {total:,} resources have an owner",
                note="C2 — every resource resolves to a team, or lands in the unowned "
                     "pool and is reported. An unowned resource is a governance "
                     "incident, not a warning",
                source="report.coverage") if owned_pct is not None
                else unknown("the coverage report has no resource denominator",
                             source="report.coverage"))
            out["monitoring"] = measure(
                summary.get("coverage_pct"), unit="%",
                state=("ok" if (summary.get("coverage_pct") or 0) >= 100 else "risk"),
                label=f"{summary.get('resources_covered', 0):,} of "
                      f"{summary.get('resources_alertable', 0):,} alertable resources",
                note=f"C1 — {summary.get('resources_observe_only', 0):,} resources are "
                     "observe-only by explicit policy, each with a recorded reason, and "
                     "are excluded from the denominator",
                source="report.coverage")
        else:
            for key in ("ownership", "monitoring"):
                out[key] = unknown(cov.error or "coverage report unavailable",
                                   source="report.coverage")

        if recon.ok and isinstance(recon.data, list):
            rows = recon.data
            attached = sum(1 for r in rows if r.get("attachment") == "ATTACHED")
            with_slo = sum(1 for r in rows if r.get("slo"))
            services = {r.get("service") for r in rows if r.get("service")}
            slo_services = {r.get("service") for r in rows
                            if r.get("service") and r.get("slo")}
            out["runbook"] = measure(
                round(100.0 * attached / len(rows), 1) if rows else None, unit="%",
                state="ok" if attached == len(rows) else "risk",
                label=f"{attached}/{len(rows)} monitors have an ATTACHED runbook",
                note="C16 — attached as a Datadog notebook asset, not a URL in the "
                     "alert body. A named-but-unreachable runbook counts as missing",
                source="report.reconciliation")
            out["slo"] = measure(
                round(100.0 * len(slo_services) / len(services), 1) if services else None,
                unit="%",
                state="ok" if len(slo_services) == len(services) else "risk",
                label=f"{len(slo_services)}/{len(services)} monitored systems map to an "
                      "objective",
                note=f"{with_slo}/{len(rows)} monitors carry an `slo_id` tag; C4 checks "
                     "the same promise from the resource side",
                source="report.reconciliation")
        else:
            for key in ("runbook", "slo"):
                out[key] = unknown(recon.error or "reconciliation report unavailable",
                                   source="report.reconciliation")

        out["oncall"] = self._oncall_coverage()
        out["agent"] = self._agent_coverage()
        return out

    def _oncall_coverage(self) -> dict:
        src = self._dd("datadog.oncall")
        if not src.ok:
            return unknown(src.error or "on-call API unavailable",
                           source="datadog.oncall")
        oncall = dd.parse_oncall(src.data)
        total, staffed = oncall["total"], oncall["staffed"]
        pct = (100.0 * staffed / total) if total else None
        payload = measure(
            round(pct, 1) if pct is not None else None, unit="%",
            state=("ok" if total and staffed == total
                   else "critical" if staffed == 0 else "risk"),
            label=f"{staffed}/{total} schedules have anyone assigned",
            note="A schedule with an empty roster still routes — to nobody. This is "
                 "counted as UNCOVERED because a page that reaches no human is the "
                 "same outcome as no page at all",
            source="datadog.oncall")
        payload["items"] = [{"schedule": n} for n in oncall["unstaffed"][:8]]
        return payload

    def _agent_coverage(self) -> dict:
        """Deliberately unknown until §36/§37 ship.

        Reporting "100% of reporting hosts have an agent" would be a tautology
        printed as a reassurance. Until something declares the required fleet,
        the honest coverage value is no value.
        """
        src = self._dd("datadog.fleet")
        if not src.ok:
            return unknown(src.error or "host inventory unavailable",
                           source="datadog.fleet")
        fleet = dd.parse_fleet(src.data)
        if fleet.get("expected_hosts"):
            pct = 100.0 * fleet["hosts_known"] / fleet["expected_hosts"]
            return measure(round(pct, 1), unit="%",
                           state="ok" if pct >= 99 else "risk",
                           label=f"{fleet['hosts_known']}/{fleet['expected_hosts']} "
                                 "required hosts report an agent",
                           source="datadog.fleet")
        return unknown(
            "no source declares which hosts are REQUIRED to run an agent — fleet "
            "management is not implemented (requirement §36/§37). Datadog can only "
            "list hosts already reporting, so any percentage would be 100% by "
            "construction",
            source="datadog.fleet")

    # -- event reduction ----------------------------------------------------
    def _event_reduction(self, reduction, red_err) -> dict:
        if red_err:
            return {"available": False, "reason": red_err,
                    "stages": [], "note": "", "source": "datadog.events"}
        raw = reduction["raw"]
        correlated = reduction["correlated"]
        incidents = reduction["incidents"]
        pct = (100.0 * (raw - incidents) / raw) if raw else None
        return {
            "available": True,
            "stages": [
                {"key": "raw", "label": "Raw signals", "value": raw,
                 "detail": "every alert Datadog raised in 24h, before correlation"},
                {"key": "correlated", "label": "Correlated events", "value": correlated,
                 "detail": "grouped by failure domain, env and service; topology and "
                           "vendor rules adopt symptoms under their cause"},
                {"key": "incidents", "label": "Incidents", "value": incidents,
                 "detail": "groups that policy says create an incident "
                           "(correlation-rules.yaml → incident_creation)"},
            ],
            "reduction_pct": round(pct, 1) if pct is not None else None,
            "paging_events": reduction["paging"],
            "note": "Computed by tools/correlate_events.py — the same module CI runs "
                    "as the platform's executable correlation specification",
            "source": "datadog.events",
        }

    # -- active incidents ---------------------------------------------------
    def _active_incidents(self, incidents, inc_err, reduction) -> dict:
        if inc_err:
            return {"available": False, "reason": inc_err, "items": [],
                    "source": "datadog.incidents"}
        by_key = {}
        for group in (reduction or {}).get("groups", []):
            by_key.setdefault(group["correlation_key"].split("#")[0], group)

        items = []
        for inc in incidents:
            if not inc["active"]:
                continue
            group = by_key.get(inc["correlation_key"]) if inc["correlation_key"] else None
            probable = inc["probable_cause"]
            cause_source = "recorded on the incident"
            if not probable and group:
                probable = group["parent"].get("title", "")
                cause_source = ("highest-ranked signal in the correlation group "
                                "(correlation-rules.yaml → root_cause_ranking)")
            items.append({
                "id": inc["id"], "public_id": inc["public_id"],
                "title": inc["title"], "severity": inc["severity"],
                "state": inc["state"], "state_class": inc["state_class"],
                "impact": inc["impact"] or ("Customer impact confirmed"
                                            if inc["customer_impacted"] else
                                            "No customer impact recorded"),
                "customer_impacted": inc["customer_impacted"],
                "probable_cause": probable or "Not recorded",
                "probable_cause_source": probable and cause_source or "",
                "duration_label": inc["duration_label"],
                "duration_seconds": inc["duration_seconds"],
                "commander": inc["commander"] or "Unassigned",
                "owner": inc["teams"] or "Unassigned",
                "services": inc["services"],
                "correlated_signals": (1 + len(group["children"])) if group else None,
                "link": inc["link"],
            })
        items.sort(key=lambda i: (i["severity"], -(i["duration_seconds"] or 0)))
        return {"available": True, "items": items, "source": "datadog.incidents"}

    # -----------------------------------------------------------------------
    # §48 — progressive drilldown
    # -----------------------------------------------------------------------
    def systems(self, slos=None, incidents=None) -> list[dict]:
        """Enterprise → SYSTEM. A system is a technology domain (domains.yaml).

        Domains are the platform's own top-level grouping — they own archetypes,
        a default team, a failure-domain vocabulary and a default SLO — so the
        portal groups by them rather than inventing an executive taxonomy that
        nothing else in the repository would agree with.
        """
        if slos is None:
            slos, _ = self.slos()
        if incidents is None:
            incidents, _ = self.incidents()
        policy = self._policy()
        if not policy.ok:
            return []
        domains = policy.data.get("domains", {}) or {}
        services = self.services()

        slo_by_domain = defaultdict(list)
        for slo in slos:
            slo_by_domain[slo["domain"]].append(slo)
        inc_by_domain = defaultdict(list)
        for inc in incidents:
            if not inc["active"]:
                continue
            for name in [s.strip() for s in (inc["services"] or "").split(",") if s.strip()]:
                domain = (services.get(name) or {}).get("domain")
                if domain:
                    inc_by_domain[domain].append(inc)

        monitors_by_domain = self._monitor_counts_by_domain()
        quality_by_domain = self._quality_by_domain()

        out = []
        for did, domain in domains.items():
            dom_slos = slo_by_domain.get(did, [])
            dom_incidents = inc_by_domain.get(did, [])
            states = [s["state"] for s in dom_slos] + [
                SEVERITY_STATE.get(i["severity"], "watch") for i in dom_incidents]
            state = worst_state(states) if states else "unknown"
            reason = _system_reason(state, dom_slos, dom_incidents)
            targets = [s["target"] for s in dom_slos
                       if isinstance(s.get("target"), (int, float))]
            dom_services = sorted(n for n, s in services.items()
                                  if s.get("domain") == did)
            out.append({
                "id": did,
                "name": domain.get("display", did),
                "owner": domain.get("owner_team", ""),
                "state": state,
                "label": _overall_label(state),
                "reason": reason,
                "critical": bool(targets) and max(targets) >= TIER1_AVAILABILITY_TARGET,
                "slo_count": len(dom_slos),
                "incident_count": len(dom_incidents),
                "service_count": len(dom_services),
                "monitor_count": monitors_by_domain.get(did),
                # Monitor QUALITY, not monitor count: an executive asking "are
                # we watching this properly?" is asking whether the monitors are
                # actionable, owned and SLO-linked, which is exactly what
                # tools/monitor_scorecard.py grades.
                "monitor_grade": quality_by_domain.get(did),
                "failure_domains": domain.get("failure_domains", []),
            })
        # Registered services declare a tier directly; a tier-0/tier-1 one is
        # critical regardless of what its domain's objectives say.
        for name, svc in services.items():
            if svc.get("kind") == "registered_service" and svc.get("tier") in ("tier0", "tier1"):
                for system in out:
                    if system["id"] == svc.get("domain"):
                        system["critical"] = True
        out.sort(key=lambda s: (WORST_ORDER.index(s["state"]), s["name"]))
        return out

    def _monitor_counts_by_domain(self) -> dict:
        """Monitors per domain, joined through each monitor's `slo_id` tag."""
        recon, policy = self._reconciliation(), self._policy()
        if not (recon.ok and policy.ok and isinstance(recon.data, list)):
            return {}
        catalog = policy.data.get("slos", {}) or {}
        counts: Counter = Counter()
        for row in recon.data:
            domain = (catalog.get(row.get("slo")) or {}).get("domain")
            if domain:
                counts[domain] += 1
        return dict(counts)

    def _quality_by_domain(self) -> dict:
        """Monitor-quality grade per domain, from the platform's own scorecard."""
        card = self._scorecard()
        if not (card.ok and isinstance(card.data, dict)):
            return {}
        return {domain: {"grade": row.get("grade"), "average": row.get("average"),
                         "monitors": row.get("monitors")}
                for domain, row in (card.data.get("by_domain") or {}).items()}

    def system_detail(self, system_id: str) -> dict | None:
        """SYSTEM → SERVICE. What lives here, what it promises, what is wrong."""
        slos, slo_err = self.slos()
        incidents, inc_err = self.incidents()
        systems = {s["id"]: s for s in self.systems(slos, incidents)}
        system = systems.get(system_id)
        if not system:
            return None
        services = self.services()
        dom_services = []
        for name, svc in sorted(services.items()):
            if svc.get("domain") != system_id:
                continue
            svc_slos = [s for s in slos if s["service"] == name]
            state = worst_state([s["state"] for s in svc_slos]) if svc_slos else "unknown"
            dom_services.append({
                "name": name, "kind": svc.get("kind"), "tier": svc.get("tier", ""),
                "team": svc.get("team", ""), "state": state,
                "label": _overall_label(state),
                "slo_count": len(svc_slos),
                "link": dd.service_url(self.app_url, name),
            })
        # An incident belongs to this system when one of its recorded services
        # does. Matching the domain id against the free-text service field would
        # both miss incidents (services are named, not domain-tagged) and match
        # by accident ("data" inside "database-platform").
        member_names = {s["name"] for s in dom_services}
        dom_incidents = [
            i for i in incidents
            if i["active"] and member_names & {
                part.strip() for part in (i["services"] or "").split(",") if part.strip()}
        ]
        return {
            "system": system,
            "services": dom_services,
            "slos": [_slo_row(s) for s in slos if s["domain"] == system_id],
            "incidents": [{**i,
                           "created": i["created"].isoformat() if i["created"] else None,
                           "detected": i["detected"].isoformat() if i["detected"] else None,
                           "resolved": i["resolved"].isoformat() if i["resolved"] else None}
                          for i in dom_incidents],
            "errors": {"slos": slo_err, "incidents": inc_err},
            "sources": self.reg.sources(),
            "freshness": self.reg.freshness(),
        }

    def service_detail(self, name: str) -> dict | None:
        """SERVICE → SLO and its technical evidence."""
        services = self.services()
        svc = services.get(name)
        if not svc:
            return None
        slos, slo_err = self.slos()
        incidents, inc_err = self.incidents()
        svc_slos = [s for s in slos if s["service"] == name]
        monitors = self._monitors_for(service=name)
        state = worst_state([s["state"] for s in svc_slos]) if svc_slos else "unknown"
        return {
            "service": {**svc, "state": state, "label": _overall_label(state),
                        "link": dd.service_url(self.app_url, name)},
            "slos": [_slo_row(s) for s in svc_slos],
            "monitors": monitors,
            "incidents": [i for i in incidents if name in (i["services"] or "")],
            "errors": {"slos": slo_err, "incidents": inc_err},
            "sources": self.reg.sources(),
            "freshness": self.reg.freshness(),
        }

    def slo_detail(self, slo_id: str) -> dict | None:
        """SLO → the monitors that defend it and the events that consumed it."""
        slos, slo_err = self.slos()
        slo = next((s for s in slos if s["slo_id"] == slo_id), None)
        if slo is None:
            policy = self._policy()
            declared = (policy.data.get("slos", {}) if policy.ok else {}).get(slo_id)
            if not declared:
                return None
            # The objective is DECLARED in policy but Datadog returned nothing
            # for it. That is a finding, not an empty page.
            return {
                "slo": {"slo_id": slo_id, "name": declared.get("name", slo_id),
                        "domain": declared.get("domain", ""),
                        "service": declared.get("service", ""),
                        "team": declared.get("team", ""),
                        "target": declared.get("target"), "sli": None,
                        "error_budget_remaining_pct": None, "state": "unknown",
                        "state_reason": slo_err or
                        "declared in platform/policy/slos.yaml but absent from the "
                        "live SLO list — the objective is not deployed",
                        "link": dd.slo_url(self.app_url, slo_id)},
                "monitors": self._monitors_for(slo_id=slo_id),
                "errors": {"slos": slo_err},
                "sources": self.reg.sources(),
                "freshness": self.reg.freshness(),
            }
        reduction, red_err = self.correlation()
        related = [g for g in (reduction.get("groups") or [])
                   if any(m.get("service") == slo["service"]
                          for m in [g["parent"], *g["children"]])]
        return {
            "slo": {**_slo_row(slo),
                    "burn_alerts": slo["burn_alerts"],
                    "telemetry_dependency": slo["telemetry_dependency"],
                    "days_to_exhaustion": _days_to_exhaustion(
                        slo["error_budget_remaining_pct"], slo["timeframe"])},
            "monitors": self._monitors_for(slo_id=slo_id),
            "event_groups": [_group_row(g, self.app_url) for g in related[:10]],
            "errors": {"slos": slo_err, "events": red_err},
            "sources": self.reg.sources(),
            "freshness": self.reg.freshness(),
        }

    def incident_detail(self, incident_id: str) -> dict | None:
        """INCIDENT → the technical evidence, then out to Datadog."""
        incidents, inc_err = self.incidents()
        inc = next((i for i in incidents
                    if str(i["id"]) == str(incident_id)
                    or str(i["public_id"]) == str(incident_id)), None)
        if inc is None:
            return None
        reduction, red_err = self.correlation()
        group = next((g for g in (reduction.get("groups") or [])
                      if g["correlation_key"].split("#")[0] == inc["correlation_key"]),
                     None)
        services = [s.strip() for s in (inc["services"] or "").split(",") if s.strip()]
        monitors: list[dict] = []
        for name in services:
            monitors.extend(self._monitors_for(service=name))
        return {
            "incident": {
                **{k: v for k, v in inc.items()
                   if k not in ("created", "detected", "resolved")},
                "created": inc["created"].isoformat() if inc["created"] else None,
                "detected": inc["detected"].isoformat() if inc["detected"] else None,
                "resolved": inc["resolved"].isoformat() if inc["resolved"] else None,
            },
            "correlation": _group_row(group, self.app_url) if group else None,
            "monitors": monitors[:40],
            "errors": {"incidents": inc_err, "events": red_err},
            "sources": self.reg.sources(),
            "freshness": self.reg.freshness(),
        }

    def _monitors_for(self, *, service: str | None = None,
                      slo_id: str | None = None) -> list[dict]:
        """Technical evidence: the reconciliation row for each relevant monitor.

        The reconciliation report already joins plan, runbook registry and
        routing policy per monitor, so the deepest drilldown level is a
        projection of an artifact the platform publishes anyway — not a fourth
        opinion about what a monitor is.
        """
        recon = self._reconciliation()
        if not (recon.ok and isinstance(recon.data, list)):
            return []
        rows = []
        for row in recon.data:
            if service and row.get("service") != service:
                continue
            if slo_id and row.get("slo") != slo_id:
                continue
            rows.append({
                "id": row.get("id"),
                "name": row.get("name", ""),
                "env": row.get("env", ""),
                "priority": row.get("priority", ""),
                "pages": bool(row.get("pages")),
                "owner": row.get("owner", ""),
                "route": row.get("route", ""),
                "runbook": row.get("runbook", ""),
                "attachment": row.get("attachment", ""),
                "auto_resolve": row.get("auto_resolve", ""),
                "status": row.get("status", ""),
                "slo": row.get("slo", ""),
                # `id` is a plan ordinal under --fixtures and the real Datadog
                # monitor id after a live reconciliation run; the deep link is
                # only meaningful in the latter case, which is why the origin of
                # report.reconciliation is shown alongside it.
                "link": dd.monitor_url(self.app_url, row.get("id")),
            })
        rows.sort(key=lambda r: (r["priority"], r["env"], r["name"]))
        return rows


WORST_ORDER = ["unknown", "critical", "risk", "watch", "neutral", "ok"]


# -----------------------------------------------------------------------------
# Pure helpers
# -----------------------------------------------------------------------------
def _slo_state(row: dict) -> tuple[str, str]:
    if row.get("error"):
        return "unknown", f"Datadog cannot compute this objective: {row['error']}"
    sli, target = row.get("sli"), row.get("target")
    budget = row.get("error_budget_remaining_pct")
    if sli is None:
        return "unknown", "no SLI returned for this objective"
    if isinstance(budget, (int, float)):
        if budget <= 0:
            return "critical", "error budget exhausted"
        if budget < BUDGET_RISK_PCT:
            return "risk", f"only {budget:.0f}% of the error budget remains"
        if budget < BUDGET_WATCH_PCT:
            return "watch", f"{budget:.0f}% of the error budget remains"
    if target is not None and sli < target:
        return "risk", f"SLI {sli:.3f}% is under the {target}% objective"
    return "ok", f"SLI {sli:.3f}% against a {target}% objective"


def _days_to_exhaustion(budget_pct, timeframe: str) -> float | None:
    """Days until the error budget runs out at the window's average burn rate.

    Deliberately the simplest defensible projection. The window is rolling, so
    the burn already observed across it IS the average rate; extrapolating that
    is a trend statement. Anything fancier would imply a confidence the input
    does not support, in front of an audience that cannot audit it.
    """
    if not isinstance(budget_pct, (int, float)) or budget_pct <= 0:
        return 0.0 if isinstance(budget_pct, (int, float)) else None
    try:
        days = float(str(timeframe).rstrip("d") or 30)
    except ValueError:
        days = 30.0
    consumed = 100.0 - budget_pct
    if consumed <= 0:
        return None                       # nothing burned: no trend to project
    return budget_pct * days / consumed


def _overall_label(state: str) -> str:
    return {
        "ok": "Healthy",
        "watch": "Watch",
        "risk": "Degraded",
        "critical": "Critical",
        "neutral": "Steady",
        "unknown": "Not visible",
    }.get(state, state.title())


def _overall_note(state: str, p1: int, p2: int, degraded: int, blind: int) -> str:
    """The one sentence under the headline. Incident first, blind spot second.

    Both facts are always stated when both are true: an executive who reads
    only this line must not be able to miss either a running P1 or the fact
    that part of the estate is unreadable.
    """
    if state == "unknown":
        return ("Nothing is currently visible: no system reported a computable "
                "state. Treat this page as unavailable, not as healthy.")
    if p1:
        head = f"{p1} major incident(s) in progress."
    elif p2:
        head = f"{p2} serious degradation(s) in progress."
    elif degraded:
        head = f"{degraded} system(s) are not fully healthy."
    else:
        head = "No incident open and every objective inside its error budget."
    if blind:
        head += (f" {blind} system(s) are not visible — their state is unknown, "
                 "not healthy.")
    return head


def _system_reason(state: str, slos: list, incidents: list) -> str:
    if state == "unknown":
        broken = [s["name"] for s in slos if s["state"] == "unknown"]
        if broken:
            return f"objective not computable: {', '.join(broken[:2])}"
        return "no objective reported for this system"
    if incidents:
        worst = min(incidents, key=lambda i: i["severity"])
        return f"{worst['severity']} — {worst['title']}"
    bad = [s for s in slos if s["state"] in ("critical", "risk", "watch")]
    if bad:
        return f"{bad[0]['name']}: {bad[0]['state_reason']}"
    return "every objective inside its error budget"


def _slo_row(slo: dict) -> dict:
    return {
        "slo_id": slo["slo_id"], "name": slo["name"], "domain": slo["domain"],
        "service": slo["service"], "team": slo["team"], "type": slo["type"],
        "timeframe": slo["timeframe"], "target": slo["target"], "sli": slo["sli"],
        "error_budget_remaining_pct": slo["error_budget_remaining_pct"],
        "state": slo["state"], "label": _overall_label(slo["state"]),
        "state_reason": slo["state_reason"], "error": slo["error"],
        "link": slo["link"],
    }


def _group_row(group: dict | None, app_url: str) -> dict | None:
    if not group:
        return None
    return {
        "correlation_key": group["correlation_key"],
        "priority": group["priority"],
        "parent": group["parent"].get("title", ""),
        "parent_signal": group["parent"].get("signal", ""),
        "children": [c.get("title", "") for c in group["children"]][:20],
        "suppressed": group.get("suppressed", 0),
        "context": [c.get("title", "") for c in group.get("context", [])][:10],
        "creates_incident": group.get("creates_incident", False),
        "closed": group.get("closed", False),
        "link": dd.event_url(app_url, group["correlation_key"].split("#")[0]),
    }
