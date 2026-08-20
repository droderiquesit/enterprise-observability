"""The two properties this portal exists to guarantee.

  1. Freshness is REPORTED. Every number carries the age of the data behind it.
  2. A failed upstream renders an EXPLICIT ERROR STATE, never a confident zero
     and never a green tile.

The second is the important one. A reporting surface that silently degrades to
"everything is 0, therefore everything is fine" is worse than no surface: it
manufactures exactly the reassurance its audience came for. These tests break a
source on purpose and assert that the page says so.
"""
import datetime as dt

import pytest

from portal.app import sources as src
from portal.app.http_app import route
from portal.app.sources import SourceRegistry, SourceResult
from portal.app.view import ExecutiveView


class BrokenRegistry(SourceRegistry):
    """A registry where the named Datadog sources always fail."""

    def __init__(self, settings, broken):
        super().__init__(settings)
        self.broken = set(broken)

    def datadog(self, name, filename, fetcher=None):
        if name in self.broken:
            return self.record(SourceResult(
                name=name, origin=src.ORIGIN_DATADOG, status=src.UNAVAILABLE,
                error="HTTPError: 503 Service Unavailable"))
        return super().datadog(name, filename, fetcher)


# --- freshness ---------------------------------------------------------------

def test_every_source_reports_its_age(settings, headers):
    payload = route("/api/sources", {}, headers, settings).payload()
    import json

    data = json.loads(payload)
    assert data["sources"], "no source was reported at all"
    for source in data["sources"]:
        assert "age_label" in source and source["age_label"]
        assert source["origin"] in ("policy", "report", "fixture", "datadog")
        assert source["status"] in ("ok", "stale", "unavailable")
    assert data["freshness"]["state"] in ("ok", "risk", "critical", "unknown")


def test_stale_data_is_labelled_stale_not_dropped(settings):
    """An old source keeps its data AND gains a stale marker."""
    reg = SourceRegistry(settings)
    old = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=9)
    result = reg.record(SourceResult(name="datadog.slos", origin=src.ORIGIN_DATADOG,
                                     data={"data": []}, produced_at=old))
    assert result.status == "stale"
    assert result.data is not None, "stale data must still be shown, with its age"
    assert "freshness budget" in result.detail
    assert reg.freshness()["state"] == "risk"


def test_a_fixture_is_never_labelled_live(settings, headers):
    import json

    data = json.loads(route("/api/sources", {}, headers, settings).payload())
    dd_sources = [s for s in data["sources"] if s["name"].startswith("datadog.")]
    assert dd_sources
    assert all(s["origin"] == "fixture" for s in dd_sources)
    assert all("recorded" in (s["detail"] or "") for s in dd_sources)
    assert data["config"]["mode"] == "fixtures"


def test_freshness_budget_differs_by_kind_of_source(settings):
    reg = SourceRegistry(settings)
    assert reg.freshness_budget(src.ORIGIN_POLICY) is None
    assert (reg.freshness_budget(src.ORIGIN_DATADOG)
            < reg.freshness_budget(src.ORIGIN_REPORT))


# --- failure renders as failure ----------------------------------------------

def test_a_failed_slo_read_never_reports_healthy_objectives(settings):
    view = ExecutiveView(BrokenRegistry(settings, ["datadog.slos"]))
    payload = view.overview()

    reliability = payload["reliability"]
    for key in ("attainment", "error_budget", "availability"):
        assert reliability[key]["known"] is False, key
        assert reliability[key]["state"] == "unknown", key
        assert reliability[key]["value"] is None, key
        assert "503" in reliability[key]["note"]

    assert payload["health"]["overall"]["state"] == "unknown"
    assert "not visible" in payload["health"]["overall"]["note"].lower()
    assert "datadog.slos" in payload["freshness"]["unavailable"]


def test_a_failed_incident_feed_is_not_zero_incidents(settings):
    view = ExecutiveView(BrokenRegistry(settings, ["datadog.incidents"]))
    payload = view.overview()

    for key in ("p1", "p2"):
        measure = payload["health"]["incidents"][key]
        assert measure["known"] is False
        assert measure["value"] is None, "a broken feed must not read as zero"
    assert payload["active_incidents"]["available"] is False
    assert "503" in payload["active_incidents"]["reason"]


def test_a_failed_event_stream_does_not_claim_perfect_noise_reduction(settings):
    view = ExecutiveView(BrokenRegistry(settings, ["datadog.events"]))
    payload = view.overview()
    assert payload["event_reduction"]["available"] is False
    assert payload["event_reduction"].get("reduction_pct") is None
    assert payload["event_reduction"]["stages"] == []
    assert "503" in payload["event_reduction"]["reason"]
    assert payload["risk"]["recurring_issues"]["known"] is False
    assert payload["risk"]["capacity"]["known"] is False


def test_a_missing_report_artifact_blanks_coverage_rather_than_scoring_100(settings):
    settings.fixtures_dir = settings.fixtures_dir.parent / "does-not-exist"
    view = ExecutiveView(SourceRegistry(settings))
    coverage = view._coverage_panel()                              # noqa: SLF001
    for key in ("ownership", "monitoring", "runbook", "slo"):
        assert coverage[key]["known"] is False, key
        assert coverage[key]["value"] is None, key


def test_everything_down_reads_as_not_visible_not_as_healthy(settings):
    settings.fixtures_dir = settings.fixtures_dir.parent / "does-not-exist"
    view = ExecutiveView(BrokenRegistry(settings, [
        "datadog.slos", "datadog.incidents", "datadog.events",
        "datadog.oncall", "datadog.fleet", "datadog.cost"]))
    payload = view.overview()
    assert payload["health"]["overall"]["state"] == "unknown"
    assert payload["health"]["overall"]["label"] == "Not visible"
    assert payload["freshness"]["state"] == "critical"


def test_a_blind_spot_never_hides_a_running_p1(settings):
    """Rollup rule: the incident is the headline, the blind spot is the footnote.

    An uncomputable objective must not downgrade a SEV-1 to "Not visible" — an
    executive needs the incident first.
    """
    state, blind = src.rollup(["unknown", "critical", "ok"])
    assert state == "critical"
    assert blind == 1
    assert src.rollup(["ok", "unknown"])[0] == "watch", (
        "an unseen corner is not a clean bill of health")
    assert src.rollup(["unknown", "unknown"])[0] == "unknown"
    assert src.rollup(["ok", "ok"]) == ("ok", 0)


def test_an_uncomputable_objective_is_not_counted_as_met(settings):
    """The backup SLO's producer is not deployed; Datadog returns an error.

    That objective must appear as a telemetry gap and must be excluded from the
    attainment ratio — never silently counted as a pass.
    """
    view = ExecutiveView(SourceRegistry(settings))
    slos, err = view.slos()
    assert err is None
    broken = [s for s in slos if s["error"]]
    assert broken, "the fixture must contain an objective Datadog cannot compute"
    assert all(s["state"] == "unknown" for s in broken)

    payload = view.overview()
    gaps = payload["risk"]["telemetry_gaps"]
    assert gaps["known"] is True and gaps["value"] >= 1
    assert any(item["kind"] == "objective_uncomputable" for item in gaps["items"])


def test_agent_coverage_stays_unknown_until_the_fleet_is_declared(settings):
    """§36/§37 are not implemented; the portal must not invent a percentage."""
    coverage = ExecutiveView(SourceRegistry(settings))._coverage_panel()  # noqa: SLF001
    assert coverage["agent"]["known"] is False
    assert "36" in coverage["agent"]["note"]


def test_empty_oncall_rosters_count_as_uncovered(settings):
    """§28: schedules exist, rosters are empty, so a page reaches nobody."""
    coverage = ExecutiveView(SourceRegistry(settings))._coverage_panel()  # noqa: SLF001
    oncall = coverage["oncall"]
    assert oncall["known"] is True
    assert oncall["value"] == 0.0
    assert oncall["state"] == "critical"


@pytest.mark.parametrize("path", ["/api/overview", "/api/systems"])
def test_an_unexpected_error_propagates_rather_than_half_rendering(settings, headers,
                                                                   monkeypatch, path):
    """A bug in the view must not produce a page that looks finished.

    `route()` deliberately does not swallow exceptions; the HTTP handler above
    it turns them into an explicit 500 with a message telling the reader not to
    trust the page. Silently returning whatever was assembled before the error
    is how a half-built view gets read as a full one.
    """
    def explode(self, *args, **kwargs):
        raise RuntimeError("upstream exploded")

    monkeypatch.setattr(SourceRegistry, "policy", explode)
    monkeypatch.setattr(SourceRegistry, "report", explode)
    monkeypatch.setattr(SourceRegistry, "datadog", explode)
    with pytest.raises(RuntimeError):
        route(path, {}, headers, settings)
