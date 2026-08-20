"""The portal must be fully usable with no credentials and no network.

If these fail, nobody can review the portal, CI cannot gate it, and the only
way to see it is to point it at production — which is how a reporting surface
ends up untested.
"""
import json

from portal.app.http_app import route
from portal.app.sources import SourceRegistry
from portal.app.view import ExecutiveView


def _view(settings):
    return ExecutiveView(SourceRegistry(settings))


def test_overview_builds_from_fixtures_alone(settings):
    payload = _view(settings).overview()
    assert payload["health"]["overall"]["state"] in (
        "ok", "watch", "risk", "critical", "unknown")
    assert payload["event_reduction"]["available"] is True
    assert payload["active_incidents"]["available"] is True
    assert payload["systems"], "the domain model produced no systems"


def test_no_source_reports_unavailable_in_the_default_offline_run(settings):
    payload = _view(settings).overview()
    down = [s for s in payload["sources"] if s["status"] == "unavailable"]
    assert not down, f"offline run should read every fixture: {down}"


def test_report_artifacts_fall_back_to_the_committed_snapshot(settings):
    """A clean clone has no generated/ — the portal must still render."""
    reg = SourceRegistry(settings)
    result = reg.report("report.coverage", "coverage_report.json")
    assert result.ok
    assert result.origin == "fixture"
    assert "portal/fixtures" in result.detail


def test_report_artifacts_prefer_generated_over_the_snapshot(settings, tmp_path):
    """When the tooling HAS run, its output wins over the recorded copy."""
    settings.generated_dir = tmp_path
    (tmp_path / "coverage_report.json").write_text(json.dumps(
        {"generated_at": "2026-08-20T01:00:00Z", "summary": {"resources_total": 7}}))
    result = SourceRegistry(settings).report("report.coverage", "coverage_report.json")
    assert result.origin == "report"
    assert result.data["summary"]["resources_total"] == 7


def test_every_api_route_answers_offline(settings, headers):
    for path in ("/api/healthz", "/api/session", "/api/overview", "/api/sources",
                 "/api/systems", "/api/systems/database", "/api/slos",
                 "/api/slos/slo-database-availability",
                 "/api/services/database-platform", "/api/incidents/4471"):
        response = route(path, {}, headers, settings)
        assert response.status == 200, f"{path} returned {response.status}"
        assert json.loads(response.payload())


def test_unknown_resources_are_404_not_a_blank_page(settings, headers):
    for path in ("/api/systems/not-a-domain", "/api/services/not-a-service",
                 "/api/slos/not-an-slo", "/api/incidents/999999"):
        assert route(path, {}, headers, settings).status == 404


def test_the_portal_serves_nothing_but_reads(settings, headers):
    """No write path exists, and the router refuses to pretend otherwise."""
    from portal.app.http_app import Handler

    for method in ("do_POST", "do_PUT", "do_PATCH", "do_DELETE"):
        assert getattr(Handler, method) is Handler._refuse


def test_static_assets_are_confined_to_the_static_root(settings, headers):
    assert route("/static/app.js", {}, headers, settings).status == 200
    for attempt in ("/static/../app/config.py", "/static/../../platform/policy/global.yaml",
                    "/static/..%2f..%2fetc%2fpasswd"):
        assert route(attempt, {}, headers, settings).status in (403, 404)


def test_no_credential_reaches_the_browser(settings, headers, monkeypatch):
    monkeypatch.setenv("DD_API_KEY", "super-secret-api-key")
    monkeypatch.setenv("DD_APP_KEY", "super-secret-app-key")
    body = b""
    for path in ("/api/session", "/api/overview", "/api/sources"):
        body += route(path, {}, headers, settings).payload()
    assert b"super-secret" not in body
    assert b"DD_API_KEY" not in body


def test_the_parse_cache_is_invalidated_by_the_file_itself(settings, tmp_path):
    """Re-parsing is avoided; stale content is not served.

    The cache key IS the file's mtime, so editing the file changes the key. A
    cache that could outlive its file would be a second source of truth, which
    is the one thing this portal must not become.
    """
    import os
    import time

    settings.generated_dir = tmp_path
    path = tmp_path / "coverage_report.json"
    path.write_text(json.dumps({"summary": {"resources_total": 1}}))
    first = SourceRegistry(settings).report("report.coverage", "coverage_report.json")
    assert first.data["summary"]["resources_total"] == 1

    path.write_text(json.dumps({"summary": {"resources_total": 2}}))
    os.utime(path, (time.time() + 5, time.time() + 5))
    second = SourceRegistry(settings).report("report.coverage", "coverage_report.json")
    assert second.data["summary"]["resources_total"] == 2


def test_the_system_view_reports_monitor_quality_from_the_scorecard(settings):
    """The scorecard is the platform's own grade; the portal must not re-grade."""
    systems = _view(settings).systems()
    graded = [s for s in systems if s["monitor_grade"]]
    assert graded, "no system carried a scorecard grade"
    assert all(g["monitor_grade"]["grade"] in "ABCDF" for g in graded)


def test_correlation_uses_the_platforms_own_engine(settings):
    """Event reduction is measured, not asserted.

    The three stages must be monotonically decreasing and must be derived from
    tools/correlate_events.py — the module CI already gates as the platform's
    executable correlation specification.
    """
    reduction, err = _view(settings).correlation()
    assert err is None
    assert reduction["raw"] > reduction["correlated"] > reduction["incidents"] > 0
    assert reduction["paging"] <= reduction["correlated"]
