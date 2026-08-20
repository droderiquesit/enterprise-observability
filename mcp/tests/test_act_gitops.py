"""ACT MODE (§44) — the change path, and the proof it has no shortcut.

Two things are asserted here that matter more than the happy path:

  * A DRY RUN CHANGES NOTHING. Not the repository, not a branch, not a remote.
  * THERE IS NO WRITE TO DATADOG. The state layer can only issue GET, and the
    act layer has no Datadog client at all.
"""
import subprocess
from pathlib import Path

import pytest
import yaml

import obs_act
import obs_gitops
import obs_router

SERVICE_SPEC = {
    "name": "orders-api", "team": "application-development", "tier": "tier2",
    "service_archetype": "api", "description": "Order capture and lookup API.",
    "envs": ["qa", "stage"],
}

# The same registration in the ENTITY shape the registry actually stores:
# `kind` explicit, `tier` under its §10 name. Built from SERVICE_SPEC so the
# two cannot drift apart.
ENTITY_SPEC = {k: v for k, v in SERVICE_SPEC.items() if k != "tier"}
ENTITY_SPEC.update(kind="service", criticality=SERVICE_SPEC["tier"])


def entity_doc(**over):
    return yaml.safe_dump({"entity": {**ENTITY_SPEC, **over}})


def _git(repo: Path, *args) -> str:
    return subprocess.run(["git", *args], cwd=str(repo), capture_output=True,
                          text=True, check=True).stdout


def _plan(ctx, files):
    out = obs_router.dispatch(ctx, "obs.plan", {"files": files})
    assert out["ok"], out.get("error")
    return out["result"]


# --- inspect / validate -----------------------------------------------------

def test_validate_accepts_the_repositorys_own_entity_registration(state):
    """The MCP must accept the registry's OWN files.

    Reading a real committed entity rather than a fixture is the point: it is
    what catches the MCP validating against a shape the repository stopped
    using. It did exactly that once — the registry moved to platform/entities/
    and this read a path that no longer existed.
    """
    text = (Path(obs_act.REPO_ROOT) / "platform" / "entities" / "identity-api.yaml").read_text()
    v = obs_act.validate_manifest(state, text)
    assert v["kind"] == "entity" and v["subject"] == "identity-api"
    # It is already registered, so the ONLY complaint should be exactly that.
    assert all("already registered" in e for e in v["errors"]), v["errors"]


def test_generated_entity_yaml_is_accepted_by_the_validator(state):
    """Act mode must not be able to propose a file its own gate rejects."""
    spec = {"name": "billing-api", "team": "sre", "tier": "tier1",
            "service_archetype": "api", "envs": ["prod"],
            "description": "Invoice issuance and payment status lookup."}
    out = obs_act.generate_entity_yaml(state, spec)
    assert out["path"] == "platform/entities/billing-api.yaml"
    v = obs_act.validate_manifest(state, out["content"])
    assert v["valid"], v["errors"]
    # `kind` is written explicitly, never left to a downstream default.
    assert yaml.safe_load(out["content"])["entity"]["kind"] == "service"


def test_generated_entity_is_written_inside_the_write_fence(state):
    out = obs_act.generate_entity_yaml(
        state, {"name": "billing-api", "team": "sre", "tier": "tier1",
                "service_archetype": "api", "envs": ["prod"],
                "description": "Invoice issuance and payment status lookup."})
    obs_act.assert_writable(out["path"])      # raises if the fence refuses it


def test_validate_accepts_the_reference_self_service_manifest(state):
    text = (Path(obs_act.REPO_ROOT) / "tests" / "fixtures"
            / "self_service_example.yaml").read_text()
    v = obs_act.validate_manifest(state, text)
    assert v["kind"] == "monitor"
    assert v["valid"], v["errors"]


def test_validate_rejects_the_mistakes_the_ci_gate_rejects(state):
    bad = yaml.safe_dump({"monitor": {
        "name": "bad-monitor", "archetype": "does-not-exist", "service": "nope",
        "team": "not-a-team", "env": ["prod"], "slo": "slo-nope",
        "runbook": "nope", "workflow": "nope"}})
    v = obs_act.validate_manifest(state, bad)
    assert not v["valid"]
    joined = " ".join(v["errors"])
    for expected in ("team", "slo", "runbook", "workflow", "archetype"):
        assert expected in joined, f"the validator said nothing about {expected}"


def test_validate_reports_unparseable_yaml_instead_of_raising(state):
    v = obs_act.validate_manifest(state, "service:\n  name: [unclosed\n")
    assert not v["valid"] and "unparseable" in v["errors"][0]


# --- resolution -------------------------------------------------------------

def test_profile_resolution_matches_the_profile_engine(state):
    r = obs_act.resolve_monitoring_profile(state, service_archetype="api",
                                           tier="tier0", env="prod")
    assert (r["monitoring_profile"], r["alert_band"]) == ("critical", "critical")
    assert "api-core" in r["packs"]

    # The qa/dev clamp is policy, and the resolver must honour it rather than
    # reporting the tier's headline profile.
    qa = obs_act.resolve_monitoring_profile(state, service_archetype="api",
                                            tier="tier0", env="qa")
    assert (qa["monitoring_profile"], qa["alert_band"]) == ("baseline", "baseline")

    # tier3 is observe_only WITH A RECORDED REASON — never a silent gap.
    t3 = obs_act.resolve_monitoring_profile(state, service_archetype="api",
                                            tier="tier3", env="prod")
    assert t3["alert_band"] == "none" and t3["observe_only_reason"]


def test_compliance_scope_promotes_to_the_regulated_profile(state):
    r = obs_act.resolve_monitoring_profile(state, service_archetype="api", tier="tier2",
                                           env="prod", compliance_scope="sox")
    assert r["monitoring_profile"] == "regulated"
    assert r["alert_band"] == "critical"


def test_slo_resolution_distinguishes_per_service_from_domain(state):
    t0 = obs_act.resolve_slo_profile(state, service="identity-api", tier="tier0",
                                     service_archetype="api")
    assert t0["scope"] == "per_service" and t0["per_service_slo_id"]
    t2 = obs_act.resolve_slo_profile(state, service="reporting-portal", tier="tier2",
                                     service_archetype="api")
    assert t2["scope"] == "domain" and t2["domain_slos"]
    assert t2["per_service_slo_id"] is None
    # The known limits are stated, not implied. A domain-scoped entity shares
    # its domain's targets — that is the limit that still applies. (The former
    # "cannot declare multiple objectives" limit is gone: the layered chain
    # resolves several, as the tier0 assertion below shows.)
    assert any("domain-scoped" in x for x in t2["limits"])
    assert len(t0["objectives"]) > 1


def test_missing_telemetry_lists_the_metrics_and_labels_the_derivation(state):
    t = obs_act.missing_telemetry(state, service_archetype="api",
                                  observed=["trace.http.request.hits"])
    assert "apm_traces" in t["declared_required_telemetry"]
    assert "trace.http.request.hits" not in t["derived_metrics_missing"]
    assert t["derived_metrics_missing"], "an api service needs more than one metric"
    assert any("§38" in g for g in t["known_gaps"])


# --- onboarding preview -----------------------------------------------------

def test_preview_onboarding_reports_zero_new_objects_for_a_normal_service(state):
    p = obs_act.preview_onboarding(state, SERVICE_SPEC)
    assert p["valid"], p["errors"]
    assert p["new_datadog_objects_created"] == 0
    assert sum(e["monitors_joined_count"] for e in p["per_environment"]) > 0
    assert p["runbooks_reachable"]
    # The invariant, restated where somebody onboarding will actually read it.
    assert "joins existing grouped monitors" in p["objects_note"]


def test_preview_onboarding_for_tier0_reports_the_slo_it_creates(state):
    p = obs_act.preview_onboarding(state, {**SERVICE_SPEC, "name": "checkout-api",
                                           "tier": "tier0", "envs": ["prod"]})
    assert p["slo"]["scope"] == "per_service"
    assert p["new_datadog_objects_created"] == len(p["slo"]["burn_windows"])


def test_what_if_merged_is_the_same_computation(state):
    text = entity_doc(name="orders-api-2")
    import obs_ask
    a = obs_ask.answer(state, "what_if_merged", {"yaml": text})
    assert a["data"]["valid"]
    assert a["data"]["delta"]["monitors_created"] == 0
    assert a["data"]["delta"]["monitors_joined"] > 0


# --- generation -------------------------------------------------------------

def test_generated_entity_yaml_validates(state, engineer):
    out = obs_router.dispatch(engineer, "obs.generate_yaml",
                              {"kind": "entity", "spec": ENTITY_SPEC})["result"]
    assert out["path"] == "platform/entities/orders-api.yaml"
    assert out["validation"]["valid"], out["validation"]["errors"]
    doc = yaml.safe_load(out["content"])
    assert doc["entity"]["name"] == "orders-api"


def test_generate_yaml_still_accepts_the_legacy_service_kind(state, engineer):
    """`kind: service` is the name callers already use; it must keep working.

    It now produces an ENTITY file — same registration, correct shape — rather
    than silently writing the superseded format to a directory nothing reads.
    """
    out = obs_router.dispatch(engineer, "obs.generate_yaml",
                              {"kind": "service", "spec": SERVICE_SPEC})["result"]
    assert out["path"] == "platform/entities/orders-api.yaml"
    assert out["validation"]["valid"], out["validation"]["errors"]
    assert yaml.safe_load(out["content"])["entity"]["criticality"] == "tier2"


def test_generated_monitor_yaml_validates(state, engineer):
    spec = {"name": "orders-latency-guard", "archetype": "api-latency-p99",
            "service": "identity-api", "team": "security", "env": ["prod"],
            "slo": "slo-api-latency", "runbook": "api-latency-p99",
            "workflow": "diag-api-health",
            "justification": "The pack monitor is rate-of-change; this service has a "
                             "strong weekly shape and needs the seasonal variant."}
    out = obs_router.dispatch(engineer, "obs.generate_yaml",
                              {"kind": "monitor", "spec": spec})["result"]
    assert out["path"] == "platform/monitors/orders-latency-guard.yaml"
    assert out["validation"]["valid"], out["validation"]["errors"]


def test_generated_slo_block_is_an_insert_not_a_file_rewrite(state, engineer):
    out = obs_router.dispatch(engineer, "obs.generate_yaml", {"kind": "slo", "spec": {
        "slo_id": "slo-orders-availability", "name": "Orders availability",
        "domain": "api", "service": "orders-api", "team": "application-development",
        "target": 99.9,
        "query": {"numerator": "sum:a{x}.as_count()", "denominator": "sum:b{x}.as_count()"},
    }})["result"]
    assert out["path"] == "platform/policy/slos.yaml"
    assert out["insert_under"] == "slos"
    assert "slo-orders-availability" in out["content"]


def test_generated_runbook_is_byte_identical_to_the_platform_generator(state, engineer):
    out = obs_router.dispatch(engineer, "obs.generate_runbook",
                              {"archetype": "api-availability"})["result"]
    import generate_runbooks
    expected = generate_runbooks.render(state.policy, "api-availability",
                                        state.policy["archetypes"]["api-availability"])
    assert out["content"] == expected
    assert out["path"] == "platform/runbooks/api-availability.md"


# --- planning ---------------------------------------------------------------

def test_plan_reports_the_delta_the_budget_and_a_token(state, engineer):
    files = {"platform/entities/orders-api.yaml":
             entity_doc()}
    plan = _plan(engineer, files)
    assert plan["errors"] == []
    assert plan["policy_lint_errors"] == [], "the repository's own lint must be clean"
    assert plan["estate"]["monitors_created_by_this_change"] == 0
    assert plan["estate"]["within_budget"] is True
    assert plan["environments_targeted"] == ["qa", "stage"]
    assert plan["plan_token"].startswith("plan-")


def test_plan_surfaces_a_manifest_that_ci_would_reject(state, engineer):
    files = {"platform/entities/broken.yaml": yaml.safe_dump({"entity": {"name": "x"}})}
    plan = _plan(engineer, files)
    assert plan["errors"], "an incomplete registration must not plan clean"


def test_terraform_planning_is_opt_in_and_never_reaches_datadog(state, monkeypatch):
    out = obs_act.terraform_plan(state)
    assert out["ran"] is False and "opt-in" in out["reason"]

    monkeypatch.setenv("OBS_MCP_TERRAFORM", "1")
    monkeypatch.setenv("DD_API_KEY", "a-real-looking-key")
    calls = {}

    def fake_run(cmd, cwd=None, env=None, **kw):
        calls["env"] = env
        calls["cmd"] = cmd
        raise OSError("not actually running terraform in a test")

    monkeypatch.setattr(obs_act.shutil, "which", lambda b: "/usr/bin/terraform")
    monkeypatch.setattr(obs_act.subprocess, "run", fake_run)
    obs_act.terraform_plan(state)
    # The credentials are FORCED to `offline` even though a real key is exported.
    assert calls["env"]["DD_API_KEY"] == "offline"
    assert calls["env"]["DD_APP_KEY"] == "offline"
    assert "datadog_validate=false" in calls["cmd"]
    assert "apply" not in calls["cmd"]


# --- the dry run ------------------------------------------------------------

def test_a_dry_run_makes_no_changes(state, engineer, scratch_repo):
    files = {"platform/entities/orders-api.yaml":
             entity_doc()}
    token = _plan(engineer, files)["plan_token"]
    engineer.config["repo_root"] = scratch_repo

    before_head = _git(scratch_repo, "rev-parse", "HEAD").strip()
    before_branches = _git(scratch_repo, "branch", "--list")
    before_tree = sorted(p.relative_to(scratch_repo).as_posix()
                         for p in scratch_repo.rglob("*") if p.is_file()
                         and ".git" not in p.parts)
    before_status = _git(scratch_repo, "status", "--porcelain")

    out = obs_router.dispatch(engineer, "obs.propose_change", {
        "files": files, "plan_token": token, "subject": "Onboard orders-api",
        "rationale": "Registers the order capture API so it joins the api-core pack."})
    assert out["ok"] is True
    result = out["result"]
    assert result["dry_run"] is True
    assert result["pushed"] is False and result["pull_request_url"] is None
    assert "DRY RUN" in result["note"]
    # ...and it still tells the reviewer everything they need to decide.
    assert result["branch"].startswith("mcp/")
    assert result["commit_message"] and result["pull_request_body"]

    assert _git(scratch_repo, "rev-parse", "HEAD").strip() == before_head
    assert _git(scratch_repo, "branch", "--list") == before_branches
    assert _git(scratch_repo, "status", "--porcelain") == before_status
    assert sorted(p.relative_to(scratch_repo).as_posix()
                  for p in scratch_repo.rglob("*") if p.is_file()
                  and ".git" not in p.parts) == before_tree
    assert "commit" not in result


def test_dry_run_is_the_default_when_the_flag_is_absent(state, engineer, scratch_repo):
    files = {"platform/entities/orders-api.yaml":
             entity_doc()}
    token = _plan(engineer, files)["plan_token"]
    engineer.config["repo_root"] = scratch_repo
    out = obs_router.dispatch(engineer, "obs.propose_change", {
        "files": files, "plan_token": token, "subject": "Onboard orders-api",
        "rationale": "Registers the order capture API so it joins the api-core pack."})
    assert out["result"]["dry_run"] is True, "omitting dry_run must not mean apply"


# --- the real change path ---------------------------------------------------

def test_propose_commits_to_a_branch_and_leaves_the_base_untouched(
        state, engineer, scratch_repo, tmp_path):
    files = {"platform/entities/orders-api.yaml":
             entity_doc()}
    token = _plan(engineer, files)["plan_token"]
    engineer.config["repo_root"] = scratch_repo
    base_head = _git(scratch_repo, "rev-parse", "main").strip()

    out = obs_router.dispatch(engineer, "obs.propose_change", {
        "files": files, "plan_token": token, "subject": "Onboard orders-api",
        "rationale": "Registers the order capture API so it joins the api-core pack.",
        "dry_run": False})
    assert out["ok"] is True, out.get("error")
    r = out["result"]
    assert r["dry_run"] is False and r["commit"]
    assert r["pushed"] is False, "push must be opt-in on top of dry_run=false"
    assert r["datadog_writes"] == 0

    assert _git(scratch_repo, "rev-parse", "main").strip() == base_head
    assert r["branch"] in _git(scratch_repo, "branch", "--list")
    shown = _git(scratch_repo, "show", "--stat", r["branch"])
    assert "platform/entities/orders-api.yaml" in shown
    assert "orders-api" in _git(scratch_repo, "show",
                                f"{r['branch']}:platform/entities/orders-api.yaml")
    # The worktree is scratch space and must not survive the call.
    assert not any((obs_gitops.DEFAULT_WORKTREE_ROOT / r["branch"].replace("/", "__")
                    ).glob("*")) if obs_gitops.DEFAULT_WORKTREE_ROOT.exists() else True


def test_the_slo_insert_lands_inside_the_slos_section(state, engineer, scratch_repo):
    block = "\n  slo-orders-availability:\n    name: Orders availability\n"
    files = {"platform/policy/slos.yaml": block}
    token = _plan(engineer, files)["plan_token"]
    engineer.config["repo_root"] = scratch_repo
    out = obs_router.dispatch(engineer, "obs.propose_change", {
        "files": files, "plan_token": token, "subject": "Add the orders availability SLO",
        "rationale": "Adds an availability objective for the order capture API.",
        "approval": {"approver": "lead", "ticket": "CHG0001"}, "dry_run": False})
    # An SLO reaches production by construction, and `engineer` holds no prod.
    assert out["ok"] is False and out["error"]["code"] == "environment_denied"


def test_the_slo_insert_preserves_the_rest_of_the_catalog(state, lead, scratch_repo):
    block = "\n  slo-orders-availability:\n    name: Orders availability\n"
    files = {"platform/policy/slos.yaml": block}
    token = _plan(lead, files)["plan_token"]
    lead.config["repo_root"] = scratch_repo
    out = obs_router.dispatch(lead, "obs.propose_change", {
        "files": files, "plan_token": token, "subject": "Add the orders availability SLO",
        "rationale": "Adds an availability objective for the order capture API.",
        "approval": {"approver": "lead", "ticket": "CHG0001"}, "dry_run": False})
    # lead cannot approve their own change, so this is still refused — which is
    # the gate working. Prove the INSERT mechanics separately, below.
    assert out["ok"] is False and out["error"]["code"] == "approval_required"


def test_insert_yaml_block_is_anchored_to_the_named_section():
    original = (Path(obs_act.REPO_ROOT) / "platform" / "policy" / "slos.yaml").read_text()
    block = "\n  slo-orders-availability:\n    name: Orders availability\n"
    merged = obs_gitops.insert_yaml_block(original, "slos", block)
    doc = yaml.safe_load(merged)
    assert "slo-orders-availability" in doc["slos"]
    # Nothing else moved: no key gained, no key lost.
    assert set(doc) == set(yaml.safe_load(original))
    # The insert lands INSIDE `slos:` and does not drift past the end of the
    # section. slos.yaml carries no sibling key after `slos:` to anchor on, so
    # the anchor is the trailing comment block that documents why per-service
    # SLOs are NOT defined in this file — text that must stay below the insert.
    tail = "# PER-SERVICE SLOs — NOT DEFINED HERE"
    assert tail in merged
    assert merged.index("slo-orders-availability") < merged.index(tail)
    # Every comment in the original survives — the file's comments ARE the
    # design rationale, which is why the insert is textual and not a re-dump.
    assert merged.count("# ") >= original.count("# ")


def test_the_pull_request_body_states_the_change_path(state, engineer, scratch_repo):
    files = {"platform/entities/orders-api.yaml":
             entity_doc()}
    token = _plan(engineer, files)["plan_token"]
    engineer.config["repo_root"] = scratch_repo
    body = obs_router.dispatch(engineer, "obs.propose_change", {
        "files": files, "plan_token": token, "subject": "Onboard orders-api",
        "rationale": "Registers the order capture API so it joins the api-core pack."
    })["result"]["pull_request_body"]
    assert "cannot write to Datadog" in body
    assert "ci.yml" in body
    assert "datadog-production" in body
    assert "platform/entities/orders-api.yaml" in body


def test_a_generated_branch_name_is_never_the_base_or_a_protected_branch(
        scratch_repo, monkeypatch):
    """The guard, exercised directly.

    Normal inputs cannot produce `main` — every branch is `mcp/<date>-...` — so
    the only honest way to test the refusal is to force the collision.
    """
    for collision in ("main", "tfstate"):
        monkeypatch.setattr(obs_gitops, "branch_name", lambda *a, **k: collision)
        with pytest.raises(obs_gitops.GitOpsError, match="protected branch"):
            obs_gitops.propose(files={"platform/entities/x.yaml": "service: {}\n"},
                               subject="a subject", body="body", principal_id="p",
                               repo_root=scratch_repo, base="main", apply=True)


def test_generated_branch_names_are_namespaced_and_attributable():
    name = obs_gitops.branch_name("Onboard orders-api", "o11y-engineer")
    assert name.startswith("mcp/")
    assert "onboard-orders-api" in name and "o11y-engineer" in name
    assert name not in obs_gitops.PROTECTED_BRANCHES


# --- no Datadog write path exists ------------------------------------------

def test_the_state_layer_can_only_issue_get(state, monkeypatch):
    """`_get` hard-codes the verb, so a write cannot be added by accident."""
    seen = []
    monkeypatch.setattr(obs_act.oc, "dd_request",
                        lambda method, url, **kw: seen.append(method))
    monkeypatch.setenv("DD_API_KEY", "x")
    monkeypatch.setenv("DD_APP_KEY", "y")
    with pytest.raises(AttributeError):     # the stub returns None; that is fine
        state._get("/api/v1/monitor")
    assert seen == ["GET"]

    import obs_state
    source = Path(obs_state.__file__).read_text()
    assert source.count("dd_request(") == 1, (
        "obs_state must reach Datadog through exactly one call site")
    for verb in ('"POST"', "'POST'", '"PUT"', '"PATCH"', '"DELETE"'):
        assert verb not in source, f"obs_state.py contains {verb}"


def test_no_module_in_act_mode_imports_a_datadog_write_client():
    """A structural check: the act layer must have no way to reach the API.

    Cheap and blunt on purpose — it fails the moment somebody adds `requests`
    or a POST to obs_act.py, which is exactly when a reviewer should be asked.
    """
    source = (Path(obs_act.__file__)).read_text()
    for forbidden in ("requests.", "dd_request(\"POST", "dd_request('POST",
                      "\"POST\"", "'POST'", "\"PUT\"", "\"DELETE\""):
        assert forbidden not in source, f"obs_act.py contains {forbidden!r}"
