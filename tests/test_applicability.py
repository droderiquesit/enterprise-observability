"""TELEMETRY REQUIREMENTS AND MONITOR APPLICABILITY (§16, §38, §39).

The failure this file exists to prevent: a monitor deployed where its telemetry
source is absent reports OK forever. It does not error, it does not go no-data
in any way anyone notices, and the estate looks covered. Every assertion here
is about keeping that difference computable — that a blocked monitor is
REPORTED as blocked, with the missing source named, rather than counted as
coverage.
"""
import json
from pathlib import Path

import applicability
import obs_common as oc
import profile_engine
import validate_policy as vp

POLICY = oc.load_policy()
FIXTURES = Path(__file__).parent / "fixtures"
ESTATE = json.loads((FIXTURES / "telemetry_estate.json").read_text())


# --- the catalog declares its telemetry -------------------------------------

def test_every_archetype_declares_telemetry():
    """§38. No exceptions, including the transitional PostgreSQL file — an
    archetype that cannot say what it reads cannot be reasoned about at all."""
    undeclared = [aid for aid, a in POLICY["archetypes"].items() if not a.get("telemetry")]
    assert undeclared == [], f"archetypes with no telemetry declaration: {undeclared}"


def test_every_declared_source_is_in_the_vocabulary():
    vocab = set(oc.telemetry_sources(POLICY))
    for aid, a in POLICY["archetypes"].items():
        unknown = [t for t in a["telemetry"] if t not in vocab]
        assert unknown == [], f"{aid} declares unknown telemetry {unknown}"


def test_declaration_matches_the_query_it_describes():
    """A declaration that names the wrong producer is worse than a missing one:
    it makes the applicability report confidently wrong."""
    for aid, a in POLICY["archetypes"].items():
        assert sorted(a["telemetry"]) == oc.derive_telemetry(POLICY, a["query"]), aid


def test_every_vocabulary_entry_is_actually_used():
    """A source nobody reads is either a dead entry or a monitor that was never
    written; both are worth noticing while the vocabulary is small."""
    used = {t for a in POLICY["archetypes"].values() for t in a["telemetry"]}
    assert set(oc.telemetry_sources(POLICY)) - used == set()


def test_the_custom_emitters_in_the_gap_register_are_distinguishable():
    """docs/telemetry-gaps.md documents each acme.* emitter as a separate thing
    someone must build, so each has to be separately absent."""
    for aid, source in (
        ("sqlserver-restore-verification-stale", "custom_restore_verification"),
        ("snowflake-task-failure", "custom_snowflake_exporter"),
        ("servicebus-message-age", "custom_messaging_client_metrics"),
        ("nsg-denied-flow-anomaly", "log_derived_nsg_flows"),
        ("azure-budget-breach", "custom_finops_exporter"),
        ("app-connection-pool-saturation", "custom_app_pool_metrics"),
        ("hardware-thermal-trend", "ipmi_hardware_check"),
        ("os-end-of-life", "cmdb_compliance_export"),
    ):
        assert POLICY["archetypes"][aid]["telemetry"] == [source]


def test_runtime_metrics_are_not_the_same_source_as_apm():
    """A traced service emits no jvm.*/runtime.* unless DD_RUNTIME_METRICS_ENABLED
    is set, so treating them as one source would report GC coverage the estate
    does not have."""
    assert POLICY["archetypes"]["api-latency-p99"]["telemetry"] == ["apm"]
    assert POLICY["archetypes"]["app-jvm-heap-pressure"]["telemetry"] == ["apm_runtime_metrics"]


# --- lint -------------------------------------------------------------------

def test_a_fabricated_telemetry_value_fails_lint(monkeypatch):
    """The vocabulary is closed. An invented source id would pass review as
    plausible prose and then silently match nothing in the applicability
    engine."""
    poisoned = {k: dict(v) for k, v in POLICY["archetypes"].items()}
    poisoned["host-memory-pressure"]["telemetry"] = ["node_exporter_metrics"]
    monkeypatch.setattr(oc, "load_policy", lambda: dict(POLICY, archetypes=poisoned))

    errors = vp.lint()
    assert any("[TELEMETRY]" in e and "host-memory-pressure" in e
               and "node_exporter_metrics" in e for e in errors), errors


def test_a_missing_telemetry_declaration_fails_lint(monkeypatch):
    stripped = {k: dict(v) for k, v in POLICY["archetypes"].items()}
    stripped["host-memory-pressure"].pop("telemetry")
    monkeypatch.setattr(oc, "load_policy", lambda: dict(POLICY, archetypes=stripped))

    errors = vp.lint()
    assert any("[TELEMETRY]" in e and "missing required field `telemetry`" in e
               for e in errors), errors


def test_a_declaration_that_contradicts_the_query_fails_lint(monkeypatch):
    """In the vocabulary, spelled correctly, and wrong: `sqlserver.*` does not
    come from the Azure integration."""
    swapped = {k: dict(v) for k, v in POLICY["archetypes"].items()}
    swapped["sqlserver-deadlock-anomaly"]["telemetry"] = ["azure_integration"]
    monkeypatch.setattr(oc, "load_policy", lambda: dict(POLICY, archetypes=swapped))

    errors = vp.lint()
    assert any("[TELEMETRY]" in e and "sqlserver-deadlock-anomaly" in e
               and "sqlserver_integration" in e for e in errors), errors


# --- the applicability engine -----------------------------------------------

def test_an_archetype_whose_telemetry_is_absent_is_blocked_with_the_reason():
    """The core §38 assertion, stated as a difference between two estates that
    differ only in whether one exporter exists."""
    without = applicability.evaluate_archetypes(
        POLICY, ["snowflake-task-failure"], {"snowflake_integration"})
    assert without["applicable"] == []
    blocked = without["blocked_by_missing_telemetry"][0]
    assert blocked["archetype"] == "snowflake-task-failure"
    assert blocked["missing"] == ["custom_snowflake_exporter"]
    # The reason has to name the source, not just say "telemetry missing" —
    # a gap without a named producer has no owner and becomes no ticket.
    assert "custom_snowflake_exporter" in blocked["reason"]
    assert blocked["remediation"][0]["provided_by"].startswith("Scheduled TASK_HISTORY")

    with_it = applicability.evaluate_archetypes(
        POLICY, ["snowflake-task-failure"],
        {"snowflake_integration", "custom_snowflake_exporter"})
    assert [r["archetype"] for r in with_it["applicable"]] == ["snowflake-task-failure"]
    assert with_it["blocked_by_missing_telemetry"] == []


def test_a_partially_instrumented_entity_reports_both_halves():
    """A frontend with APM but no RUM: the traces work, Core Web Vitals cannot."""
    entity = {"id": "service:portal", "service_archetype": "web", "telemetry": ["apm"]}
    result = applicability.evaluate_entity(POLICY, {"telemetry": []}, entity)
    assert result["applicable_count"] > 0
    assert result["blocked_count"] > 0
    blocked = {r["archetype"] for r in result["blocked_by_missing_telemetry"]}
    assert "web-js-error-anomaly" in blocked
    assert 0 < result["coverage_pct"] < 100


def test_coverage_is_the_ratio_of_what_can_fire():
    report = applicability.evaluate(POLICY, ESTATE)
    s = report["summary"]
    total = s["archetype_instances_applicable"] + s["archetype_instances_blocked"]
    assert s["coverage_pct"] == round(100.0 * s["archetype_instances_applicable"] / total, 1)
    assert 0 < s["coverage_pct"] < 100, "the fixture estate has real gaps on purpose"


def test_an_entity_with_no_telemetry_at_all_is_entirely_blocked():
    entity = {"id": "pipeline:orphan", "service_archetype": "batch_job", "telemetry": []}
    result = applicability.evaluate_entity(POLICY, {"telemetry": []}, entity)
    assert result["applicable_count"] == 0
    assert result["blocked_count"] > 0
    # Zero, not 100. An entity nothing can watch must never score as covered.
    assert result["coverage_pct"] == 0.0


def test_missing_sources_are_ranked_by_what_they_cost():
    """The report has to point at the one piece of work that buys the most, or
    it is a list of complaints rather than a plan."""
    report = applicability.evaluate(POLICY, ESTATE)
    counts = [row["blocked_instances"] for row in report["blocked_by_source"]]
    assert counts == sorted(counts, reverse=True)
    for row in report["blocked_by_source"]:
        assert row["source"] in oc.telemetry_sources(POLICY)
        assert row["blocked_archetypes"]


def test_the_catalog_view_covers_the_whole_catalog():
    report = applicability.evaluate(POLICY, ESTATE)
    s = report["summary"]
    assert s["catalog_applicable"] + s["catalog_blocked"] == len(POLICY["archetypes"])
    assert s["catalog_blocked"] > 0


def test_the_postgres_retirement_is_complete():
    """Phase B of the two-phase retirement: the three PostgreSQL-era archetypes
    are gone from the catalog, and so is the integration that fed them.

    They could not be deleted in the same apply that moved the composite and the
    SLO off them — Datadog refuses to delete a monitor a composite or an SLO
    still references, and Terraform sequences those updates after the monitor
    map. The transitional file held them at exactly their production instance
    until the references moved; this asserts the second phase actually happened,
    rather than the file being deleted while something still pointed at them."""
    for aid in ("db-query-latency-anomaly", "db-connection-saturation",
                "db-replication-lag"):
        assert aid not in POLICY["archetypes"], f"{aid} survived the retirement"
    assert "postgresql_integration" not in oc.telemetry_sources(POLICY)
    assert not [a for a, v in POLICY["archetypes"].items()
                if "postgresql." in (v.get("query") or "")]
    assert not [s for s in POLICY["slos"].values()
                if "postgresql." in json.dumps(s.get("query") or {})]


def test_an_unknown_source_in_the_inventory_is_reported_not_ignored():
    entity = {"id": "host:x", "service_archetype": "infrastructure_resource",
              "telemetry": ["agent", "prometheus_scrape"]}
    result = applicability.evaluate_entity(POLICY, {"telemetry": []}, entity)
    assert result["telemetry_unknown"] == ["prometheus_scrape"]


def test_the_markdown_report_renders_and_names_the_gaps():
    md = applicability.to_markdown(applicability.evaluate(POLICY, ESTATE))
    assert "Monitor applicability" in md
    assert "custom_messaging_client_metrics" in md


# --- profile resolution consumes telemetry (§16) -----------------------------

def _inventory(*resources):
    return {"resources": list(resources)}


def _resource(rid, service, sa, tier="tier1"):
    return {"id": rid, "kind": "service", "service": service, "env": "prod",
            "tags": {"env": "prod", "service": service, "team": "sre",
                     "tier": tier, "service_archetype": sa}}


def test_a_profile_does_not_claim_coverage_it_cannot_deliver():
    """§16. A tier1 batch job with no batch emitter resolved to `critical` and a
    full monitor pack that could never evaluate. It now resolves to the only
    profile that states the truth, with the missing sources recorded."""
    inv = _inventory(_resource("pipeline:nightly", "nightly-settlement", "batch_job"))
    a = profile_engine.assign(inv, POLICY, {}, ESTATE)["assignments"][0]
    assert a["monitoring_profile"] == "observe_only"
    assert a["alert_band"] == "none"
    assert a["telemetry_coverage_pct"] == 0.0
    assert "custom_batch_job_metrics" in a["observe_only_reason"]
    assert any(v.startswith("telemetry_missing:") for v in a["violations"])


def test_a_partial_gap_keeps_the_profile_and_records_the_shortfall():
    """Three working monitors out of eight is real coverage; demoting would
    throw away the three that work."""
    inv = _inventory(_resource("service:identity-api", "identity-api", "api", "tier0"))
    a = profile_engine.assign(inv, POLICY, {}, ESTATE)["assignments"][0]
    assert a["monitoring_profile"] == "critical"
    assert 0 < a["telemetry_coverage_pct"] < 100
    assert a["telemetry_missing"]


def test_no_telemetry_survey_changes_nothing_and_asserts_nothing():
    """Absence of a survey is not evidence of absent telemetry. Without one the
    resolution is identical to before and coverage is null, never 0 or 100."""
    inv = _inventory(_resource("pipeline:nightly", "nightly-settlement", "batch_job"))
    a = profile_engine.assign(inv, POLICY, {})["assignments"][0]
    assert a["monitoring_profile"] == "critical"
    assert a["telemetry_coverage_pct"] is None
    assert a["telemetry_missing"] == []


def test_the_summary_counts_the_estate_the_survey_covered():
    inv = _inventory(
        _resource("service:identity-api", "identity-api", "api", "tier0"),
        _resource("pipeline:nightly", "nightly-settlement", "batch_job"),
    )
    s = profile_engine.assign(inv, POLICY, {}, ESTATE)["summary"]
    assert s["telemetry_surveyed"] == 2
    assert s["telemetry_blocked"] == 2
    assert s["telemetry_demoted_to_observe_only"] == 1
