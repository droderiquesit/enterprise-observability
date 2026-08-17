"""Event correlation: many alerts for one problem become ONE incident.

The storm test is the executable version of the framework's noise promise.
"""
import correlate_events as ce


def _e(ts, ck, dk, priority="P2", signal="error_rate", domain="application",
       env="prod", region="eastus2", kind="alert", title="", service=None, **kw):
    e = {"ts": ts, "correlation_key": ck, "dedup_key": dk, "priority": priority,
         "signal": signal, "domain": domain, "env": env, "region": region,
         "kind": kind, "title": title or dk, "service": service or "svc"}
    e.update(kw)
    return e


def test_database_failure_storm_collapses_to_one_incident():
    """A DB failure cascades into six alerts. Expect one page, one incident."""
    storm = [
        _e(0, "databases.prod.database-platform", "database-platform.prod.db-availability",
           priority="P1", signal="availability", domain="database", title="db unavailable"),
        _e(30, "databases.prod.database-platform", "database-platform.prod.db-connection-saturation",
           signal="saturation", domain="database", title="connection saturation"),
        _e(60, "application-platform.prod.application-platform",
           "application-platform.prod.dependency-error-anomaly", title="app dependency errors"),
        _e(90, "application-platform.prod.application-platform",
           "application-platform.prod.api-latency-p99", signal="latency", title="api latency"),
        _e(120, "application-platform.prod.application-platform",
           "application-platform.prod.slo-burn.fast", priority="P1", signal="error_budget",
           title="error budget burn"),
        # duplicate inside the dedup window — must be discarded entirely
        _e(45, "databases.prod.database-platform", "database-platform.prod.db-availability",
           priority="P1", signal="availability", domain="database", title="duplicate"),
    ]
    groups = ce.correlate(storm)
    assert len(groups) == 1, [g["correlation_key"] for g in groups]
    g = groups[0]
    assert g["parent"]["title"] == "db unavailable", "availability outranks every symptom"
    assert g["suppressed"] == 4
    assert sum(x["pages"] for x in groups) == 1, "six raw alerts, one page"
    assert g["creates_incident"]


def test_deployment_is_attached_as_context_and_never_pages():
    events = [
        _e(0, "application-platform.prod.application-platform",
           "application-platform.prod.deployment-regression", title="error spike"),
        _e(-300, "application-platform.prod.application-platform", "deploy-4471",
           kind="change", title="deployment v4471"),
    ]
    groups = ce.correlate(events)
    assert len(groups) == 1
    assert [c["title"] for c in groups[0]["context"]] == ["deployment v4471"]
    assert groups[0]["parent"]["title"] == "error spike"


def test_vendor_outage_absorbs_downstream_integration_alerts():
    events = [
        _e(0, "saas-dependency.prod.salesforce", "salesforce.prod.saas-availability",
           priority="P1", signal="availability", domain="saas", title="salesforce down",
           archetype="saas-availability"),
        _e(60, "integration-platform.prod.crm-sync", "crm-sync.prod.integration-flow-failure",
           domain="integration", title="crm sync failing"),
        _e(90, "integration-platform.prod.order-sync", "order-sync.prod.integration-flow-failure",
           domain="integration", title="order sync failing"),
    ]
    groups = ce.correlate(events)
    assert len(groups) == 1
    assert groups[0]["parent"]["title"] == "salesforce down"
    assert groups[0]["suppressed"] == 2


def test_unrelated_failures_stay_separate():
    events = [
        _e(0, "databases.prod.database-platform", "a", domain="database", region="eastus2"),
        _e(5, "security-telemetry.prod.security-telemetry", "b", domain="security",
           region="westeurope"),
    ]
    assert len(ce.correlate(events)) == 2


def test_recovery_closes_the_group_and_stops_paging():
    events = [
        _e(0, "databases.prod.db", "db.prod.availability", priority="P1", signal="availability",
           domain="database"),
        _e(100, "databases.prod.db", "db.prod.availability", kind="recovery"),
    ]
    g = ce.correlate(events)[0]
    assert g["closed"] and g["pages"] == 0 and not g["creates_incident"]


def test_group_stays_open_while_a_child_is_still_alerting():
    events = [
        _e(0, "databases.prod.db", "db.prod.availability", priority="P1", signal="availability",
           domain="database"),
        _e(30, "databases.prod.db", "db.prod.saturation", signal="saturation", domain="database"),
        _e(100, "databases.prod.db", "db.prod.availability", kind="recovery"),
    ]
    assert not ce.correlate(events)[0]["closed"]


def test_p3_never_pages_and_creates_no_incident():
    g = ce.correlate([_e(0, "x.prod.x", "x.prod.ticket", priority="P3", signal="capacity")])[0]
    assert g["pages"] == 0 and not g["creates_incident"]


def test_maintenance_window_events_are_dropped_entirely():
    events = [_e(0, "x.prod.x", "x.prod.a", priority="P1", signal="availability",
                 maintenance=True)]
    assert ce.correlate(events) == []


def test_broad_scope_raises_priority():
    """Breadth is business impact: a failure across a quarter of a pack escalates."""
    events = [
        _e(0, "api-services.prod.api", f"svc{i}.prod.api-5xx-anomaly", priority="P2",
           service=f"svc{i}", pack="api-core")
        for i in range(5)
    ]
    groups = ce.correlate(events, pack_service_counts={"api-core": 10})
    assert groups[0]["priority"] == "P1"
    assert groups[0].get("uplifted")


def test_narrow_scope_does_not_escalate():
    events = [_e(0, "api-services.prod.api", "svc1.prod.api-5xx-anomaly",
                 priority="P2", service="svc1", pack="api-core")]
    groups = ce.correlate(events, pack_service_counts={"api-core": 100})
    assert groups[0]["priority"] == "P2"
