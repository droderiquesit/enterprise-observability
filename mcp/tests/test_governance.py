"""GOVERNANCE (§45) — the negative tests.

A permission model is only real if the refusals are tested. Each test below is
a specific way somebody could get a change into Datadog without review, and the
assertion is that they cannot.
"""
import json
import time

import pytest

import obs_act
import obs_governance as gov
import obs_router
from conftest import TOKENS
from obs_tools import TOOLS

SERVICE_YAML = (
    "entity:\n"
    "  kind: service\n"
    "  name: probe-api\n"
    "  team: sre\n"
    "  criticality: tier2\n"
    "  service_archetype: api\n"
    "  description: A probe service used by the governance tests.\n"
    "  envs: [qa]\n"
)


# --- authentication ---------------------------------------------------------

def test_no_token_is_anonymous_read_only():
    p = gov.authenticate(None)
    assert p.id == gov.ANONYMOUS
    assert p.role == "viewer-auditor"
    assert p.authenticated is False
    assert p.capabilities == ("read",)
    for cap in ("plan", "generate", "propose", "admin"):
        assert not p.holds(cap)


def test_a_wrong_token_is_refused_not_downgraded():
    with pytest.raises(gov.AuthenticationError):
        gov.authenticate("definitely-not-a-real-token")


def test_a_valid_token_resolves_to_its_declared_role():
    p = gov.authenticate(TOKENS["engineer"])
    assert (p.id, p.role, p.authenticated) == ("engineer", "observability-engineer", True)
    assert p.environments == ("dev", "qa", "stage")


def test_the_role_model_is_the_platforms_four_roles():
    """§45 says map onto the EXISTING roles. Not five, not a parallel universe."""
    assert set(gov.ROLES) == {"viewer-auditor", "incident-responder",
                              "observability-engineer", "platform-admin"}
    # And the capability grant must be monotonic along that ladder.
    ladder = ["viewer-auditor", "incident-responder", "observability-engineer",
              "platform-admin"]
    for lower, higher in zip(ladder, ladder[1:]):
        assert set(gov.ROLES[lower]["capabilities"]) < set(gov.ROLES[higher]["capabilities"])


# --- the headline refusal ---------------------------------------------------

def test_an_unauthorized_write_is_refused(auditor):
    """A read-only principal cannot generate, plan, or propose. Anything."""
    for name, args in [
        ("obs.generate_yaml", {"kind": "service", "spec": {}}),
        ("obs.generate_runbook", {"archetype": "api-availability"}),
        ("obs.plan", {"files": {}}),
        ("obs.preview_onboarding", {"service": {
            "name": "x", "team": "sre", "tier": "tier2", "service_archetype": "api",
            "description": "a description", "envs": ["qa"]}}),
        ("obs.propose_change", {"files": {"platform/entities/x.yaml": SERVICE_YAML},
                                "plan_token": "plan-whatever", "subject": "a subject",
                                "rationale": "a rationale long enough to pass the schema"}),
    ]:
        out = obs_router.dispatch(auditor, name, args)
        assert out["ok"] is False, f"{name} was allowed for a viewer-auditor"
        assert out["error"]["code"] == "forbidden"
        assert "held by" in out["error"]["remedy"]


def test_an_incident_responder_can_plan_but_never_propose(make_ctx):
    ctx = make_ctx("responder")
    assert obs_router.dispatch(ctx, "obs.resolve_profile", {
        "service_archetype": "api", "tier": "tier0", "env": "prod"})["ok"] is True
    out = obs_router.dispatch(ctx, "obs.propose_change", {
        "files": {"platform/entities/x.yaml": SERVICE_YAML},
        "plan_token": "plan-x", "subject": "a subject",
        "rationale": "long enough rationale for the schema"})
    assert out["ok"] is False and out["error"]["code"] == "forbidden"


# --- plan-before-apply ------------------------------------------------------

def _plan(ctx, files):
    out = obs_router.dispatch(ctx, "obs.plan", {"files": files})
    assert out["ok"], out.get("error")
    return out["result"]["plan_token"]


def test_propose_without_a_plan_is_refused(engineer):
    out = obs_router.dispatch(engineer, "obs.propose_change", {
        "files": {"platform/entities/probe-api.yaml": SERVICE_YAML},
        "plan_token": "plan-never-issued", "subject": "Onboard probe-api",
        "rationale": "a rationale that is comfortably long enough"})
    assert out["ok"] is False and out["error"]["code"] == "plan_required"


def test_a_plan_token_does_not_transfer_to_different_content(engineer):
    files = {"platform/entities/probe-api.yaml": SERVICE_YAML}
    token = _plan(engineer, files)
    tampered = {"platform/entities/probe-api.yaml": SERVICE_YAML + "# one extra byte\n"}
    out = obs_router.dispatch(engineer, "obs.propose_change", {
        "files": tampered, "plan_token": token, "subject": "Onboard probe-api",
        "rationale": "a rationale that is comfortably long enough"})
    assert out["ok"] is False and out["error"]["code"] == "plan_required"
    assert "differ" in out["error"]["error"]


def test_an_expired_plan_token_is_refused(make_ctx):
    ctx = make_ctx("engineer", plan_ttl_seconds=0)
    files = {"platform/entities/probe-api.yaml": SERVICE_YAML}
    token = _plan(ctx, files)
    time.sleep(0.01)
    out = obs_router.dispatch(ctx, "obs.propose_change", {
        "files": files, "plan_token": token, "subject": "Onboard probe-api",
        "rationale": "a rationale that is comfortably long enough"})
    assert out["ok"] is False and out["error"]["code"] == "plan_required"


# --- environment restriction and approval ----------------------------------

PROD_YAML = SERVICE_YAML.replace("envs: [qa]", "envs: [prod]")


def test_an_environment_the_principal_does_not_hold_is_refused(engineer):
    files = {"platform/entities/probe-api.yaml": PROD_YAML}
    token = _plan(engineer, files)
    out = obs_router.dispatch(engineer, "obs.propose_change", {
        "files": files, "plan_token": token, "subject": "Onboard probe-api to prod",
        "rationale": "a rationale that is comfortably long enough"})
    assert out["ok"] is False and out["error"]["code"] == "environment_denied"


def test_production_needs_a_named_second_approver(lead):
    files = {"platform/entities/probe-api.yaml": PROD_YAML}
    token = _plan(lead, files)
    base = {"files": files, "plan_token": token, "subject": "Onboard probe-api to prod",
            "rationale": "a rationale that is comfortably long enough"}

    out = obs_router.dispatch(lead, "obs.propose_change", base)
    assert out["ok"] is False and out["error"]["code"] == "approval_required"

    # self-approval is the failure mode the gate exists for
    out = obs_router.dispatch(lead, "obs.propose_change",
                              {**base, "approval": {"approver": "lead", "ticket": "CHG1"}})
    assert out["ok"] is False and out["error"]["code"] == "approval_required"
    assert "own production change" in out["error"]["error"]

    # a principal that is not registered as an approver
    out = obs_router.dispatch(lead, "obs.propose_change",
                              {**base, "approval": {"approver": "engineer", "ticket": "CHG1"}})
    assert out["ok"] is False and out["error"]["code"] == "approval_required"

    # and a change record is mandatory
    out = obs_router.dispatch(lead, "obs.propose_change",
                              {**base, "approval": {"approver": "lead"}})
    assert out["ok"] is False and out["error"]["code"] == "approval_required"


def test_a_qa_change_needs_no_approver(engineer):
    files = {"platform/entities/probe-api.yaml": SERVICE_YAML}
    token = _plan(engineer, files)
    out = obs_router.dispatch(engineer, "obs.propose_change", {
        "files": files, "plan_token": token, "subject": "Onboard probe-api",
        "rationale": "a rationale that is comfortably long enough"})
    assert out["ok"] is True
    assert out["result"]["gates"]["approval"]["required"] is False


# --- the write fence --------------------------------------------------------

@pytest.mark.parametrize("path", [
    "platform/policy/archetypes/api.yaml",
    "stacks/coverage/monitors.tf",
    "modules/monitor_factory/main.tf",
    ".github/workflows/ci.yml",
    "tests/fixtures/monitors_planned.json",
    "tools/coverage_report.py",
    "README.md",
    "mcp/obs_governance.py",
    "../../etc/passwd",
    "platform/entities/../../secrets.yaml",
])
def test_the_write_fence_refuses_everything_outside_team_owned_yaml(path):
    with pytest.raises(obs_act.WriteFenceError):
        obs_act.assert_writable(path)


@pytest.mark.parametrize("path", [
    "platform/entities/orders-api.yaml",
    "platform/monitors/orders-latency.yaml",
    "platform/runbooks/api-availability.md",
    "platform/policy/slos.yaml",
])
def test_the_write_fence_allows_the_team_owned_surface(path):
    obs_act.assert_writable(path)


def test_a_fenced_path_is_refused_at_plan_time_as_a_policy_denial(engineer):
    out = obs_router.dispatch(engineer, "obs.plan",
                              {"files": {"stacks/coverage/monitors.tf": "resource {}"}})
    assert out["ok"] is False
    assert out["error"]["code"] == "write_fence_denied"


# --- rate limiting ----------------------------------------------------------

def test_rate_limits_are_per_principal_and_per_capability(make_ctx):
    ctx = make_ctx("engineer", rate_limits={"read": (2, 60), "plan": (1, 60),
                                            "generate": (5, 60), "propose": (5, 60),
                                            "admin": (5, 60)})
    assert obs_router.dispatch(ctx, "obs.list_questions", {})["ok"]
    assert obs_router.dispatch(ctx, "obs.list_questions", {})["ok"]
    out = obs_router.dispatch(ctx, "obs.list_questions", {})
    assert out["ok"] is False and out["error"]["code"] == "rate_limited"

    # a different capability has its own budget and is untouched
    assert obs_router.dispatch(ctx, "obs.resolve_slo",
                               {"tier": "tier0", "service_archetype": "api"})["ok"]


# --- secrets ----------------------------------------------------------------

@pytest.mark.parametrize("payload,leaked", [
    ({"api_key": "0123456789abcdef0123456789abcdef"}, "0123456789abcdef"),
    ({"nested": {"DD_APP_KEY": "abc"}}, "abc"),
    ({"body": "export DD_API_KEY=0123456789abcdef0123456789abcdef"}, "0123456789abcdef"),
    ({"body": "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload"}, "eyJhbGciOiJIUzI1NiJ9"),
    ({"body": "token ghp_abcdefghijklmnopqrstuvwxyz0123"}, "ghp_abcdefghij"),
])
def test_secrets_are_redacted_before_anything_is_recorded(payload, leaked):
    assert leaked not in json.dumps(gov.redact(payload))


def test_a_secret_passed_as_an_argument_never_reaches_the_audit_log(engineer):
    secret = "0123456789abcdef0123456789abcdef"
    obs_router.dispatch(engineer, "obs.validate_yaml",
                        {"yaml": f"service:\n  name: x\n  # DD_API_KEY={secret}\n"})
    written = engineer.audit.path.read_text()
    assert secret not in written
    assert "***redacted***" in written


# --- audit ------------------------------------------------------------------

def test_the_audit_log_records_every_call_including_refusals(engineer, auditor):
    calls = [
        (engineer, "obs.list_questions", {}),
        (engineer, "obs.resolve_slo", {"tier": "tier0", "service_archetype": "api"}),
        (auditor, "obs.generate_runbook", {"archetype": "api-availability"}),   # denied
        (engineer, "obs.does_not_exist", {}),                                   # denied
        (engineer, "obs.get_monitor", {"monitor_id": "999999999"}),             # empty result
    ]
    # Both contexts share one audit path (the fixture), which is what a real
    # deployment looks like: one log, many principals.
    for ctx, name, args in calls:
        obs_router.dispatch(ctx, name, args)

    lines = [json.loads(x) for x in engineer.audit.path.read_text().splitlines()]
    assert len(lines) == len(calls), "every call must leave exactly one record"
    for rec, (ctx, name, _) in zip(lines, calls):
        assert rec["tool"] == name
        assert rec["principal"] == ctx.principal.id
        assert rec["role"] == ctx.principal.role
        assert rec["decision"] in ("allow", "deny", "error")
        assert "duration_ms" in rec and "call_id" in rec and "ts" in rec
    assert [r["decision"] for r in lines] == ["allow", "allow", "deny", "deny", "allow"]
    assert lines[2]["error"]["code"] == "forbidden"


def test_the_audit_log_survives_a_handler_that_raises(engineer, monkeypatch):
    def boom(ctx, args):
        raise RuntimeError("handler exploded")

    monkeypatch.setattr(TOOLS["obs.list_questions"], "handler", boom)
    out = obs_router.dispatch(engineer, "obs.list_questions", {})
    assert out["ok"] is False and out["error"]["code"] == "tool_error"
    rec = json.loads(engineer.audit.path.read_text().splitlines()[-1])
    assert rec["decision"] == "error" and rec["tool"] == "obs.list_questions"


def test_the_audit_log_records_the_shape_of_a_result_not_its_payload(engineer):
    obs_router.dispatch(engineer, "obs.coverage_report", {})
    rec = json.loads(engineer.audit.path.read_text().splitlines()[-1])
    assert "keys" in rec["result_summary"]
    # The coverage report is tens of kilobytes; the audit line records that one
    # was produced, never the report itself. A log that copies its payload stops
    # being readable and starts retaining data it was never meant to hold.
    assert "C1" not in json.dumps(rec["result_summary"])
    assert len(json.dumps(rec)) < 4000, "an audit line must not carry the report"


def test_only_an_admin_can_read_the_audit_log(engineer, lead):
    assert obs_router.dispatch(engineer, "obs.audit_log", {})["ok"] is False
    out = obs_router.dispatch(lead, "obs.audit_log", {"limit": 5})
    assert out["ok"] is True and "records" in out["result"]
