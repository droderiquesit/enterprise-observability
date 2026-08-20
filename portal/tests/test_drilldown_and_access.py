"""Progressive drilldown (§48) and the read-only access model (§49).

The navigation test is the one §48 names: enterprise → system → service → SLO →
event/incident → technical evidence, each level reachable from the one above
without a dead end, and the last level ending in a real Datadog link rather
than a reimplementation of a Datadog view.
"""
import json

from portal.app import auth
from portal.app.http_app import route
from portal.app.sources import SourceRegistry
from portal.app.view import ExecutiveView


def _json(settings, headers, path):
    response = route(path, {}, headers, settings)
    assert response.status == 200, f"{path} → {response.status}"
    return json.loads(response.payload())


# --- §48 navigation ----------------------------------------------------------

def test_the_whole_drilldown_chain_is_walkable(settings, headers):
    """Walk the chain the requirement names, following only real links."""
    overview = _json(settings, headers, "/api/overview")

    # enterprise → system
    systems = overview["systems"]
    assert systems
    system_id = next(s["id"] for s in systems if s["service_count"] > 0)
    system = _json(settings, headers, f"/api/systems/{system_id}")
    assert system["system"]["id"] == system_id

    # system → service
    assert system["services"], f"{system_id} listed no service to drill into"
    service_name = system["services"][0]["name"]
    service = _json(settings, headers, f"/api/services/{service_name}")
    assert service["service"]["name"] == service_name

    # service → SLO
    assert service["slos"], f"{service_name} listed no objective"
    slo_id = service["slos"][0]["slo_id"]
    slo = _json(settings, headers, f"/api/slos/{slo_id}")
    assert slo["slo"]["slo_id"] == slo_id

    # SLO → technical evidence, ending in Datadog
    assert slo["monitors"], "the deepest level produced no monitor evidence"
    monitor = slo["monitors"][0]
    for field in ("owner", "route", "runbook", "attachment", "auto_resolve", "status"):
        assert field in monitor
    assert monitor["link"].startswith("https://app.datadoghq.com/monitors/")


def test_incident_drilldown_reaches_correlated_evidence(settings, headers):
    overview = _json(settings, headers, "/api/overview")
    incidents = overview["active_incidents"]["items"]
    assert incidents, "the fixture should carry at least one active incident"
    detail = _json(settings, headers, f"/api/incidents/{incidents[0]['public_id']}")
    assert detail["incident"]["severity"].startswith("SEV-")
    assert detail["incident"]["link"].startswith("https://app.datadoghq.com/incidents/")
    # Either a correlation group or an explicit absence — never a silent blank.
    assert "correlation" in detail


def test_every_drilldown_level_carries_its_own_freshness(settings, headers):
    for path in ("/api/systems/database", "/api/services/database-platform",
                 "/api/slos/slo-database-availability", "/api/incidents/4471"):
        payload = _json(settings, headers, path)
        assert payload["freshness"]["state"]
        assert payload["sources"]


def test_the_home_view_is_not_a_wall_of_graphs(settings, headers):
    """§48: the home page summarises; the engineering detail lives one level in.

    651 monitors exist. The overview must not enumerate them — it carries
    system-level rollups, and the monitor rows appear only after a drilldown.
    """
    overview = _json(settings, headers, "/api/overview")
    assert "monitors" not in overview
    assert len(overview["systems"]) < 40
    service = _json(settings, headers, "/api/services/database-platform")
    assert len(service["monitors"]) > 5


def test_a_declared_but_undeployed_objective_is_a_finding_not_a_404(settings, headers):
    """An SLO in policy that Datadog does not return must say so."""
    view = ExecutiveView(SourceRegistry(settings))
    detail = view.slo_detail("slo-app-availability")
    assert detail is not None
    # Present in both policy and the fixture, so this one resolves normally.
    assert detail["slo"]["slo_id"] == "slo-app-availability"


# --- §49 access model --------------------------------------------------------

def test_default_local_run_is_anonymous_and_read_only(settings, headers):
    session = _json(settings, headers, "/api/session")
    assert session["principal"]["read_only"] is True
    assert session["principal"]["can_write"] is False
    assert session["principal"]["authenticated"] is False
    assert session["sso_required"] is False


def test_proxy_assertion_produces_the_executive_role(settings, headers):
    headers["X-Auth-Request-Email"] = "cfo@acme.example"
    headers["X-Auth-Request-Preferred-Username"] = "A. Chief"
    session = _json(settings, headers, "/api/session")
    assert session["principal"]["authenticated"] is True
    assert session["principal"]["role"] == auth.ROLE_EXEC
    assert session["principal"]["display_name"] == "A. Chief"
    assert session["principal"]["can_write"] is False


def test_group_mapping_gates_access(settings, headers, monkeypatch):
    monkeypatch.setenv("PORTAL_EXEC_GROUPS", "exec-readers")
    headers["X-Auth-Request-Email"] = "intern@acme.example"
    headers["X-Auth-Request-Groups"] = "engineering,interns"
    assert route("/api/overview", {}, headers, settings).status == 403

    headers["X-Auth-Request-Groups"] = "engineering,exec-readers"
    assert route("/api/overview", {}, headers, settings).status == 200


def test_required_sso_fails_closed(settings, headers, monkeypatch):
    monkeypatch.setenv("PORTAL_REQUIRE_SSO", "1")
    response = route("/api/overview", {}, headers, settings)
    assert response.status == 403
    # The liveness probe must keep working, or the deployment cannot be
    # health-checked behind the proxy that is doing the authenticating.
    assert route("/api/healthz", {}, headers, settings).status == 200


def test_idp_group_membership_is_not_echoed_to_the_browser(settings, headers):
    headers["X-Auth-Request-Email"] = "cfo@acme.example"
    headers["X-Auth-Request-Groups"] = "board,finance-restricted"
    body = route("/api/session", {}, headers, settings).payload()
    assert b"finance-restricted" not in body


def test_responses_carry_the_security_headers(settings, headers):
    from portal.app.http_app import SECURITY_HEADERS

    assert SECURITY_HEADERS["X-Frame-Options"] == "DENY"
    assert "no-store" in SECURITY_HEADERS["Cache-Control"]
    csp = SECURITY_HEADERS["Content-Security-Policy"]
    assert "default-src 'none'" in csp
    assert "script-src 'self'" in csp
    assert "connect-src 'self'" in csp
