"""ASK MODE — every answer is grounded, or it is an explicit refusal.

The property under test is not "the answers are right" — the underlying engines
have their own suite in tests/. It is that no answer can be UNGROUNDED: the
evidence points at real ids in the fixture data, the numbers match what the
platform's own report says, and a question whose data does not exist returns a
reason instead of a number.
"""
import json

import pytest

import obs_ask
import obs_router
import obs_state

# Parameters for the questions that need one. Deliberately real values from the
# repository, so a citation can be checked by opening the file it names.
PARAMS = {
    "why_unhealthy": {"service": "api-services"},
    "telemetry_feeding_slo": {"slo_id": "slo-api-availability"},
    "why_service_received_slo": {"service": "identity-api"},
    "why_service_inherited_monitor": {"service": "identity-api",
                                      "archetype": "api-availability"},
    "owner_of": {"entity": "identity-api"},
    "route_for": {"monitor_id": "1"},
    "what_if_merged": {"yaml": "service:\n  name: probe-svc\n  team: sre\n  tier: tier2\n"
                               "  service_archetype: api\n"
                               "  description: A probe service for the tests.\n"
                               "  envs: [qa]\n"},
}


@pytest.mark.parametrize("qid", sorted(obs_ask.QUESTIONS))
def test_every_question_answers_or_explains_itself(state, qid):
    a = obs_ask.answer(state, qid, PARAMS.get(qid, {}))
    assert a["question"] == qid
    if a["answerable"]:
        assert a["evidence"], f"{qid} answered with no evidence"
        assert a["summary"].strip(), f"{qid} answered with no summary"
        for ev in a["evidence"]:
            assert ev["source"], f"{qid}: an evidence entry with no source"
            assert ev["kind"]
            assert ev["count"] is not None
    else:
        # A refusal must say WHY, and the reason must be substantive enough to
        # act on — "unknown" is not an answer.
        assert len(a["unanswerable_reason"]) > 30, f"{qid}: thin refusal"


def test_the_envelope_refuses_to_serialize_an_uncited_answer():
    """The guard rail itself, not just the questions that respect it."""
    from obs_evidence import Answer
    with pytest.raises(ValueError, match="must cite its source"):
        Answer(question="fabricated", summary="trust me").to_dict()
    # ...and an honest refusal is allowed to carry no evidence at all.
    a = Answer(question="fabricated").unanswerable("the data does not exist here")
    assert a.to_dict()["answerable"] is False


def test_evidence_sources_are_resolvable(state):
    """Every citation names a real file, a real API route, or a named fixture."""
    from obs_state import REPO_ROOT
    for qid in sorted(obs_ask.QUESTIONS):
        for ev in obs_ask.answer(state, qid, PARAMS.get(qid, {}))["evidence"]:
            src = ev["source"]
            if src.startswith(("datadog:", "fixture:", "synthetic-inventory:")):
                if src.startswith("fixture:"):
                    assert (REPO_ROOT / src.split(":", 1)[1]).exists(), src
                continue
            path = REPO_ROOT / src.rstrip("/")
            assert path.exists(), f"{qid} cites {src!r}, which does not exist"


# --- grounding in the fixture data ------------------------------------------

def test_unhealthy_now_cites_monitor_ids_that_exist_in_the_fixture(state):
    a = obs_ask.answer(state, "unhealthy_now", {})
    ids = [str(m["id"]) for m in a["data"]["monitors"]]
    assert ids, "the runtime fixture should contain some non-OK monitors"
    for mid in ids:
        assert mid in state.monitors_by_id, f"{mid} is not a monitor in the estate"
        assert state.runtime["monitor_states"][mid]["overall_state"] != "OK"
    # The claim and the citation must agree.
    cited = next(e for e in a["evidence"] if e["kind"] == "monitor_state")
    assert cited["count"] == len(ids)
    assert cited["source"].startswith("fixture:")


def test_coverage_answer_equals_the_platforms_own_report(state):
    a = obs_ask.answer(state, "coverage_percentage", {})
    assert a["data"]["coverage_pct"] == state.coverage["summary"]["coverage_pct"]
    assert a["data"]["monitors_managed"] == len(state.managed_monitors)
    # It cites the checks, not a number it computed itself.
    assert any(e["kind"] == "check" and "C17" in e["ids"] for e in a["evidence"])


def test_inheritance_explanation_matches_the_expansion_terraform_performs(state):
    a = obs_ask.answer(state, "why_service_inherited_monitor",
                       {"service": "identity-api", "archetype": "api-availability"})
    assert a["data"]["inherited"] is True
    assert "api-core" in a["data"]["via_packs"]
    prod = next(e for e in a["data"]["per_environment"] if e["env"] == "prod")
    assert prod["effective_band"] == "critical"
    # The same (archetype, env, band) triple must exist in obs_common's expansion.
    assert any(i["archetype"] == "api-availability" and i["env"] == "prod"
               and i["band"] == "critical" and i["priority"] == prod["priority"]
               for i in state.instances)
    # ...and the chain names the file that decided each step.
    steps = {s["step"]: s["source"] for s in a["data"]["resolution_chain"]}
    assert steps[1] == "platform/services/identity-api.yaml"
    assert steps[4] == "platform/policy/tiers.yaml"


def test_a_service_that_does_not_inherit_is_reported_as_not_inheriting(state):
    a = obs_ask.answer(state, "why_service_inherited_monitor",
                       {"service": "identity-api", "archetype": "cosmos-ru-throttling"})
    assert a["data"]["inherited"] is False
    assert a["data"]["via_packs"] == []


def test_slo_explanation_uses_the_tier_policy(state):
    a = obs_ask.answer(state, "why_service_received_slo", {"service": "identity-api"})
    assert a["data"]["tier"] == "tier0"
    assert a["data"]["slo_scope"] == state.policy["tiers"]["tier0"]["slo"]["scope"]
    assert any(e["source"] == "platform/policy/tiers.yaml" for e in a["evidence"])


def test_telemetry_answer_extracts_the_real_sli_metrics(state):
    a = obs_ask.answer(state, "telemetry_feeding_slo", {"slo_id": "slo-api-availability"})
    spec = state.policy["slos"]["slo-api-availability"]
    for metric in a["data"]["metrics"]:
        assert metric in spec["query"]["numerator"] + spec["query"]["denominator"]
    # The §8 alert_band gap must be disclosed on every SLI answer, because a
    # correctly-defined SLO over telemetry nobody emits reads as 100%.
    assert any("alert_band" in c for c in a["caveats"])


def test_route_answer_matches_the_reconciliation_report(state):
    a = obs_ask.answer(state, "route_for", {"monitor_id": "1"})
    row = next(r for r in state.reconciliation if str(r["id"]) == "1")
    assert a["data"]["route"] == row["route"]
    assert a["data"]["escalation_policy"] == row["escalation_policy"]


# --- the honest refusals ----------------------------------------------------

def test_who_is_on_call_refuses_to_name_a_person(state):
    a = obs_ask.answer(state, "who_is_on_call", {})
    assert a["answerable"] is False
    assert "§28" in a["unanswerable_reason"]
    assert "ROSTERS" in a["unanswerable_reason"]
    # The STRUCTURE is still returned and still cited — the gap is the people.
    assert a["data"]["escalation_structure"]
    assert all(t["current_responder"] is None for t in a["data"]["escalation_structure"])
    assert any(e["source"] == "platform/policy/teams.yaml" for e in a["evidence"])


def test_what_changed_discloses_the_missing_deployment_metadata(state):
    a = obs_ask.answer(state, "what_changed", {"window_hours": 24})
    assert any("DD_VERSION" in c for c in a["caveats"])


def test_missing_integrations_declares_itself_an_inference(state):
    a = obs_ask.answer(state, "missing_integrations", {})
    assert a["data"]["inference"]
    assert any("§38" in c for c in a["caveats"])


def test_noisy_monitors_declares_that_the_threshold_is_not_policy(state):
    a = obs_ask.answer(state, "noisy_monitors", {"min_triggers": 5})
    assert a["data"]["threshold"] == 5
    assert any("NOT POLICY" in c for c in a["caveats"])


def test_broken_agents_declares_that_fleet_compliance_is_unavailable(state):
    a = obs_ask.answer(state, "broken_agents", {})
    assert any("FLEET COMPLIANCE" in c for c in a["caveats"])


def test_an_unknown_subject_is_a_refusal_not_an_invention(state):
    for qid, params in [("owner_of", {"entity": "no-such-service"}),
                        ("why_service_received_slo", {"service": "no-such-service"}),
                        ("telemetry_feeding_slo", {"slo_id": "slo-does-not-exist"}),
                        ("why_service_inherited_monitor",
                         {"service": "identity-api", "archetype": "no-such-archetype"})]:
        a = obs_ask.answer(state, qid, params)
        assert a["answerable"] is False, f"{qid} invented an answer for {params}"


# --- routing ----------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("what is unhealthy right now?", "unhealthy_now"),
    ("which SLOs are burning error budget?", "slos_burning"),
    ("which SLO will breach first?", "slo_breach_first"),
    ("who is on call?", "who_is_on_call"),
    ("what changed recently?", "what_changed"),
    ("what is the probable root cause?", "probable_root_cause"),
    ("which services are affected?", "affected_entities"),
    ("what are the active incidents?", "active_incidents"),
    ("what is our MTTR?", "mttr"),
    ("which services have no SLO?", "services_without_slos"),
    ("which entities have no owner?", "entities_without_owners"),
    ("which agents are broken?", "broken_agents"),
    ("which integrations are missing?", "missing_integrations"),
    ("which monitors are noisy?", "noisy_monitors"),
    ("which monitors never triggered?", "never_triggered_monitors"),
    ("which services lack monitoring?", "services_lacking_monitoring"),
    ("what is our coverage percentage?", "coverage_percentage"),
    ("what are the top reliability risks?", "top_reliability_risks"),
    ("why did this service inherit this monitor?", "why_service_inherited_monitor"),
    ("why did this service receive this SLO?", "why_service_received_slo"),
    ("which telemetry feeds this SLO?", "telemetry_feeding_slo"),
    ("what would happen if this YAML were merged?", "what_if_merged"),
    ("where does this alert go?", "route_for"),
    ("show me correlated signals", "correlated_signals"),
])
def test_the_intent_router_is_deterministic_and_lands_on_the_right_question(text, expected):
    qid, routing = obs_router.resolve_intent(text)
    assert qid == expected, f"{text!r} routed to {qid} ({routing['candidates']})"
    assert obs_router.resolve_intent(text)[0] == qid, "routing must be reproducible"


def test_an_unroutable_question_says_so_rather_than_guessing(auditor):
    out = obs_router.dispatch(auditor, "obs.ask",
                              {"question": "zzzz qqqq wwww vvvv"})
    assert out["ok"] is True
    assert out["result"]["routed"] is False
    assert "obs.list_questions" in out["result"]["remedy"]


def test_a_question_id_bypasses_the_router(auditor):
    out = obs_router.dispatch(auditor, "obs.ask", {"question": "coverage_percentage"})
    assert out["result"]["routing"]["match"] == "exact_id"


def test_the_router_lifts_known_identifiers_out_of_the_phrasing(auditor):
    out = obs_router.dispatch(auditor, "obs.ask",
                              {"question": "who owns identity-api?"})
    assert out["ok"] is True
    assert out["result"]["answer"]["data"]["entity"] == "identity-api"


def test_the_router_never_invents_an_identifier(auditor):
    out = obs_router.dispatch(auditor, "obs.ask",
                              {"question": "who owns the-service-that-does-not-exist?"})
    # Nothing matched the catalog, so no `entity` was lifted and the question
    # refuses rather than answering about a service nobody registered.
    assert out["result"]["answer"]["answerable"] is False


def test_error_budget_is_read_from_both_api_shapes():
    """The offline shape and Datadog's own shape must both be understood.

    Reading only `error_budget_remaining_pct` would report every LIVE SLO as
    healthy, because the API returns `error_budget_remaining` as a map keyed by
    timeframe. For this question that failure mode is the worst possible one,
    so an unreadable status is None — excluded and counted — never 100.
    """
    assert obs_ask._budget_pct({"error_budget_remaining_pct": 12.5}) == 12.5
    assert obs_ask._budget_pct({"error_budget_remaining": {"30d": 42.0}}) == 42.0
    assert obs_ask._budget_pct({"error_budget_remaining": 7}) == 7.0
    assert obs_ask._budget_pct({}) is None
    assert obs_ask._budget_pct({"sli_value": 99.99}) is None


def test_unreadable_slo_status_is_excluded_not_counted_as_healthy(state, monkeypatch):
    monkeypatch.setattr(obs_ask, "_slo_rows", lambda s: [
        {"datadog_id": "slo1", "slo_id": "slo-a", "name": "A", "team": "sre",
         "status": {"sli_value": 99.9}, "budget_pct": None, "burn_rate_1h": None,
         "target": 99.9},
        {"datadog_id": "slo2", "slo_id": "slo-b", "name": "B", "team": "sre",
         "status": {"error_budget_remaining_pct": 3.0}, "budget_pct": 3.0,
         "burn_rate_1h": 9.6, "target": 99.9},
    ])
    a = obs_ask.answer(state, "slos_burning", {})
    assert a["data"]["evaluated"] == 1
    assert a["data"]["status_unreadable"] == 1
    assert any("EXCLUDED" in c for c in a["caveats"])


def test_live_mode_is_opt_in_and_fails_closed(monkeypatch):
    monkeypatch.delenv("DD_API_KEY", raising=False)
    monkeypatch.delenv("DD_APP_KEY", raising=False)
    with pytest.raises(obs_state.DatadogUnavailable):
        obs_state.PlatformState("live")


def test_answers_serialize_to_json(state):
    for qid in sorted(obs_ask.QUESTIONS):
        json.dumps(obs_ask.answer(state, qid, PARAMS.get(qid, {})), default=str)
