"""Event correlation: a storm of related failures becomes ONE actionable
incident; unrelated groups stay independent; recovery closes the group."""
import correlate_events as ce


def _e(ts, ck, dk, sev="sev2", cls="errors", domain="application", env="prod",
       region="eastus2", kind="alert", title=""):
    return {"ts": ts, "correlation_key": ck, "dedup_key": dk, "severity": sev,
            "archetype_class": cls, "domain": domain, "env": env,
            "region": region, "kind": kind, "title": title or dk}


def test_storm_collapses_to_one_incident():
    """DB failure cascades: replication lag + connection saturation + app
    errors + app latency + burn alert. Expect ONE page, one incident."""
    storm = [
        _e(0,   "databases.prod.database-platform", "database-platform.prod.db-replication-lag",
           cls="availability", domain="data", title="replication lag"),
        _e(30,  "databases.prod.database-platform", "database-platform.prod.db-connection-saturation",
           cls="saturation", domain="data", title="conn saturation"),
        _e(60,  "application-platform.prod.application-platform", "application-platform.prod.app-error-rate-anomaly",
           cls="errors", title="app errors"),
        _e(90,  "application-platform.prod.application-platform", "application-platform.prod.app-latency-degradation",
           cls="latency", title="app latency"),
        _e(120, "application-platform.prod.application-platform", "application-platform.prod.slo-burn.slo-app-availability.fast",
           cls="burn_rate", title="burn fast"),
        _e(45,  "databases.prod.database-platform", "database-platform.prod.db-replication-lag",
           cls="availability", domain="data", title="dup within window"),  # dedup
    ]
    groups = ce.correlate(storm)
    assert len(groups) == 1, [g["correlation_key"] for g in groups]
    g = groups[0]
    assert g["parent"]["title"] == "replication lag"      # availability ranks first
    assert g["suppressed"] == 4                            # everything else is a child
    assert g["pages"] == 1 and g["creates_incident"]
    total_pages = sum(x["pages"] for x in groups)
    assert total_pages == 1                                # 6 raw events → 1 page


def test_change_context_attached_not_paged():
    events = [
        _e(0, "application-platform.prod.application-platform",
           "application-platform.prod.app-error-rate-anomaly", title="errors"),
        _e(10, "application-platform.prod.application-platform",
           "deploy-123", kind="change", title="deployment v42"),
    ]
    groups = ce.correlate(events)
    assert len(groups) == 1
    assert [c["title"] for c in groups[0]["context"]] == ["deployment v42"]


def test_unrelated_failures_stay_separate():
    events = [
        _e(0, "databases.prod.database-platform", "a", domain="data", region="eastus2"),
        _e(5, "security-telemetry.prod.security-telemetry", "b", domain="security", region="westeurope"),
    ]
    assert len(ce.correlate(events)) == 2


def test_recovery_closes_group_and_stops_paging():
    events = [
        _e(0, "databases.prod.database-platform", "db.prod.lag", cls="availability", domain="data"),
        _e(100, "databases.prod.database-platform", "db.prod.lag", kind="recovery"),
    ]
    groups = ce.correlate(events)
    assert groups[0]["closed"] and groups[0]["pages"] == 0


def test_sev3_never_pages():
    events = [_e(0, "x.prod.x", "x.prod.ticket", sev="sev3")]
    g = ce.correlate(events)[0]
    assert g["pages"] == 0 and not g["creates_incident"]
