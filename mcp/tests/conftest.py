"""Shared fixtures for the MCP server tests.

Everything here runs OFFLINE. The platform state comes from the repository's own
plan-derived fixtures plus `runtime_state.json`; no test needs DD_API_KEY, and a
test that reached the network would be a defect in the server, not in the test.

`mcp/` is put on sys.path the same way `tests/conftest.py` puts `tools/` on it:
both directories hold flat modules that import each other by bare name, and
`mcp` deliberately is not a Python package (a top-level package with that name
would shadow the `mcp` PyPI SDK).
"""
import hashlib
import sys
from pathlib import Path

import pytest
import yaml

MCP_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = MCP_DIR.parent
sys.path.insert(0, str(MCP_DIR))

import obs_governance as gov          # noqa: E402
import obs_router                     # noqa: E402
import obs_state                      # noqa: E402

# Tokens exist only inside the test process. The registry stores digests, so
# even here the plaintext never lands in a file.
TOKENS = {
    "auditor": "test-token-auditor",
    "responder": "test-token-responder",
    "engineer": "test-token-engineer",
    "lead": "test-token-lead",
}
ROLES = {
    "auditor": ("viewer-auditor", [], False),
    "responder": ("incident-responder", [], False),
    "engineer": ("observability-engineer", ["dev", "qa", "stage"], False),
    "lead": ("platform-admin", ["dev", "qa", "stage", "prod"], True),
}


@pytest.fixture(scope="session")
def principals_file(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("mcp") / "principals.yaml"
    doc = {"version": 1, "principals": {
        pid: {"display": pid, "role": role, "environments": envs, "approver": approver,
              "token_sha256": hashlib.sha256(TOKENS[pid].encode()).hexdigest()}
        for pid, (role, envs, approver) in ROLES.items()}}
    path.write_text(yaml.safe_dump(doc))
    return path


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, principals_file, tmp_path):
    monkeypatch.setenv("OBS_MCP_PRINCIPALS", str(principals_file))
    monkeypatch.setenv("OBS_MCP_AUDIT_LOG", str(tmp_path / "audit.jsonl"))
    monkeypatch.delenv("OBS_MCP_TOKEN", raising=False)
    monkeypatch.delenv("OBS_MCP_TERRAFORM", raising=False)


@pytest.fixture(scope="session")
def state():
    # Session-scoped: loading policy, synthesizing the estate and running the
    # seventeen coverage checks takes seconds, and none of it is mutated.
    return obs_state.get_state("fixtures")


@pytest.fixture
def make_ctx(state, tmp_path):
    def _make(who: str = "auditor", **config):
        principal = gov.authenticate(TOKENS[who]) if who else gov.authenticate(None)
        return obs_router.Context(
            state=state, principal=principal,
            audit=gov.AuditLog(tmp_path / "audit.jsonl"),
            limiter=gov.RateLimiter(config.pop("rate_limits", None)),
            ledger=gov.PlanLedger(config.pop("plan_ttl_seconds", 3600)),
            config=config)
    return _make


@pytest.fixture
def auditor(make_ctx):
    return make_ctx("auditor")


@pytest.fixture
def engineer(make_ctx):
    return make_ctx("engineer")


@pytest.fixture
def lead(make_ctx):
    return make_ctx("lead")


@pytest.fixture
def scratch_repo(tmp_path):
    """A throwaway git repository with the paths the write fence allows.

    The GitOps tests must never run against the real checkout: a test that
    creates branches in the repository it is testing is how a suite starts
    failing for reasons nobody can reproduce.
    """
    import subprocess

    repo = tmp_path / "scratch-repo"
    (repo / "platform" / "services").mkdir(parents=True)
    (repo / "platform" / "monitors").mkdir(parents=True)
    (repo / "platform" / "policy").mkdir(parents=True)
    (repo / "platform" / "policy" / "slos.yaml").write_text(
        (REPO_ROOT / "platform" / "policy" / "slos.yaml").read_text())
    (repo / "platform" / "services" / "existing.yaml").write_text("service:\n  name: existing\n")

    def git(*args):
        subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True)

    git("init", "-b", "main")
    git("config", "user.email", "test@example.invalid")
    git("config", "user.name", "test")
    git("add", "-A")
    git("commit", "-m", "initial")
    return repo
