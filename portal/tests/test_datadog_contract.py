"""The live path and the offline path must be the SAME path.

A fixture set that is only ever read by an offline-specific branch proves
nothing about production. These tests pin the contract: identical adapters,
identical shapes, a live fetcher registered for every source, and read-only
HTTP verbs throughout.
"""
import datetime as dt
import inspect
import json

import pytest

from portal.app import datadog as dd
from portal.app.sources import SourceRegistry, TTLCache, replay_shift


def test_every_source_has_both_a_live_fetcher_and_a_recorded_response(settings):
    assert set(dd.LIVE_FETCHERS) == set(dd.FIXTURE_FILES)
    for filename in dd.FIXTURE_FILES.values():
        assert (settings.fixtures_dir / filename).is_file(), filename


def test_recorded_responses_parse_with_the_production_adapters(settings):
    reg = SourceRegistry(settings)
    slos = dd.parse_slos(reg.datadog("datadog.slos", "dd_slos.json").data)
    assert slos and all(s["slo_id"] for s in slos)
    assert any(s["error"] for s in slos), (
        "the recorded set must include an objective Datadog cannot compute")

    incidents = dd.parse_incidents(reg.datadog("datadog.incidents",
                                               "dd_incidents.json").data)
    assert incidents
    assert any(i["active"] for i in incidents)
    assert all(i["commander"] for i in incidents), (
        "commander must resolve through the JSON:API `included` block")

    signals = dd.parse_events(reg.datadog("datadog.events", "dd_events.json").data)
    assert signals
    for key in ("ts", "correlation_key", "dedup_key", "priority", "signal",
                "domain", "env", "service", "kind"):
        assert key in signals[0], key

    fleet = dd.parse_fleet(reg.datadog("datadog.fleet", "dd_fleet.json").data)
    assert fleet["hosts_known"] > 0
    assert fleet["expected_hosts"] is None, (
        "nothing declares the required fleet — see §36/§37")

    cost = dd.parse_cost(reg.datadog("datadog.cost", "dd_cost.json").data)
    assert cost["month_to_date"] and cost["forecast"]


def test_recorded_responses_carry_their_own_recording_time(settings):
    """A git checkout rewrites mtimes; `_recorded_at` survives it."""
    for filename in dd.FIXTURE_FILES.values():
        data = json.loads((settings.fixtures_dir / filename).read_text())
        assert "_recorded_at" in data, filename
        assert "_source" in data, f"{filename} must name the endpoint it recorded"


def test_the_portal_only_ever_issues_get(settings):
    source = inspect.getsource(dd)
    for verb in ('"POST"', '"PUT"', '"PATCH"', '"DELETE"'):
        assert verb not in source, f"{verb} appears in the Datadog client"
    assert source.count('_get(') >= 6


def test_unmanaged_alerts_still_count_as_raw_signal(settings):
    """A click-ops monitor has no correlation key, and must not vanish."""
    payload = {"data": [{
        "id": "evt-1",
        "attributes": {
            "timestamp": "2026-08-20T01:00:00Z",
            "tags": ["env:prod", "service:mystery"],
            "attributes": {"status": "error", "evt": {"type": "alert"},
                           "monitor": {"id": 9, "name": "somebody's monitor"}},
        }}]}
    signals = dd.parse_events(payload)
    assert len(signals) == 1
    assert signals[0]["correlation_key"].startswith("unmanaged.")
    assert signals[0]["kind"] == "alert"


def test_slo_error_never_becomes_a_healthy_reading():
    payload = {"data": [{
        "id": "slo1", "name": "Broken", "type": "metric",
        "tags": ["slo_id:slo-x", "domain:data", "service:svc"],
        "thresholds": [{"timeframe": "30d", "target": 99.9}],
        "overall_status": [{"timeframe": "30d", "target": 99.9,
                            "error": "metric not found"}],
    }]}
    row = dd.parse_slos(payload)[0]
    assert row["error"] == "metric not found"
    assert row["sli"] is None
    assert row["error_budget_remaining_pct"] is None


def test_deep_links_point_at_the_configured_datadog_site(settings):
    app = "https://acme.datadoghq.eu"
    assert dd.monitor_url(app, 42) == f"{app}/monitors/42"
    assert dd.incident_url(app, 4471) == f"{app}/incidents/4471"
    assert "slo_id%3Aslo-x" in dd.slo_url(app, "slo-x")
    assert "correlation_key" in dd.event_url(app, "a.b.c")


# --- caching (live mode only) -------------------------------------------------

def test_the_cache_is_never_consulted_offline(settings):
    cache = TTLCache(60)
    reg = SourceRegistry(settings, cache)
    reg.datadog("datadog.slos", "dd_slos.json", lambda: {"data": []})
    assert cache.get("datadog.slos") is None, (
        "fixture mode must read the file every time; there is nothing to rate-limit")


def test_a_cached_live_read_reports_the_age_of_the_data_not_the_request(settings):
    settings.mode = "live"
    cache = TTLCache(60)
    calls = []

    def fetcher():
        calls.append(1)
        return {"data": []}

    first = SourceRegistry(settings, cache).datadog("datadog.slos", "dd_slos.json",
                                                    fetcher)
    second = SourceRegistry(settings, cache).datadog("datadog.slos", "dd_slos.json",
                                                     fetcher)
    assert len(calls) == 1, "the second read must come from the cache"
    assert second.origin == "datadog"
    assert "cached" in second.detail
    assert second.produced_at == first.produced_at, (
        "a cached payload must keep the fetch time, not adopt the request time")


def test_a_live_read_that_raises_becomes_an_unavailable_source(settings):
    settings.mode = "live"

    def boom():
        raise RuntimeError("401 Forbidden")

    result = SourceRegistry(settings, TTLCache(60)).datadog(
        "datadog.slos", "dd_slos.json", boom)
    assert result.status == "unavailable"
    assert result.data is None, "a failed read must not fall back to the fixture"
    assert "401" in result.error


# --- opt-in demo replay -------------------------------------------------------

def test_replay_preserves_every_interval(settings):
    recorded = dt.datetime(2026, 8, 20, 2, 0, tzinfo=dt.timezone.utc)
    data = {"data": [{"attributes": {"created": "2026-08-20T00:00:00Z",
                                     "resolved": "2026-08-20T01:00:00Z"}}]}
    shifted = replay_shift(data, recorded)
    attrs = shifted["data"][0]["attributes"]
    created = dt.datetime.fromisoformat(attrs["created"].replace("Z", "+00:00"))
    resolved = dt.datetime.fromisoformat(attrs["resolved"].replace("Z", "+00:00"))
    assert (resolved - created) == dt.timedelta(hours=1)
    assert created > dt.datetime(2026, 8, 20, 0, 0, tzinfo=dt.timezone.utc)


def test_replay_is_off_by_default_and_announces_itself_when_on(settings):
    assert settings.fixture_replay is False
    plain = SourceRegistry(settings).datadog("datadog.incidents", "dd_incidents.json")
    assert "REPLAY" not in plain.detail

    settings.fixture_replay = True
    replayed = SourceRegistry(settings).datadog("datadog.incidents",
                                                "dd_incidents.json")
    assert "REPLAY" in replayed.detail
    assert settings.public()["fixture_replay"] is True


@pytest.mark.parametrize("key", ["dd_api_key", "DD_API_KEY", "api_key", "app_key"])
def test_no_recorded_response_contains_a_credential_field(settings, key):
    for filename in dd.FIXTURE_FILES.values():
        text = (settings.fixtures_dir / filename).read_text()
        assert key not in text, f"{filename} mentions {key}"
