"""GOVERNANCE — who is calling, what they may do, and the record that they did.

§45. Six mechanisms, in the order a call passes through them:

  1. AUTHENTICATION   a bearer token, compared by digest in constant time
                      against `principals.yaml`. No token → the anonymous
                      principal, which is `viewer-auditor` and read-only.
  2. RBAC             the platform's EXISTING four roles from
                      stacks/foundation/main.tf → module "rbac". Not a parallel
                      permission universe: `viewer-auditor`,
                      `incident-responder`, `observability-engineer`,
                      `platform-admin`, mapped onto five capabilities.
  3. ENVIRONMENT      a principal carries the environments it may propose
                      changes for. `prod` is not granted by default.
  4. RATE LIMIT       per principal, per capability class. A read storm and a
                      PR storm are not the same risk and do not share a bucket.
  5. GATES            dry-run by default; plan-before-propose (you cannot open
                      a PR for content you have not planned); a second-person
                      approval for anything touching production.
  6. AUDIT            every call — allowed, refused, or failed — appended as
                      one JSON line, with arguments redacted.

WHY ROLES AND NOT SCOPES. stacks/foundation/main.tf explains at length why the
platform has four verbs and derives SCOPE from `team:` ownership tags rather
than multiplying roles by team × environment. This server inherits that
decision: the role says which VERBS you hold, `environments` says where, and
ownership stays where it already lives — in the tags on the objects.
"""
from __future__ import annotations

import dataclasses
import fnmatch
import hashlib
import hmac
import json
import os
import re
import time
from pathlib import Path

import yaml

MCP_DIR = Path(__file__).resolve().parent
REPO_ROOT = MCP_DIR.parent

# ---------------------------------------------------------------------------
# THE FOUR ROLES. Mirrored from stacks/foundation/main.tf → module "rbac". The
# Datadog permission list is quoted so a reviewer can see, in one place, that
# the MCP capability grant is a SUBSET of what the same role already holds in
# Datadog — this server can never let somebody do more here than there.
# ---------------------------------------------------------------------------
CAPABILITIES = ("read", "plan", "generate", "propose", "admin")

ROLES: dict[str, dict] = {
    "viewer-auditor": {
        "display": "Viewer / Auditor",
        "datadog_permissions": [],          # baseline org read, nothing else
        "capabilities": ["read"],
        "why": "Sees everything, changes nothing. Ask mode in full; no Act.",
    },
    "incident-responder": {
        "display": "Incident Responder",
        "datadog_permissions": ["monitors_downtime", "incident_write",
                                "incident_settings_write", "workflows_run",
                                "notebooks_write", "security_monitoring_signals_write"],
        "capabilities": ["read", "plan"],
        "why": ("Investigates and can dry-run 'what would this change do' during an "
                "incident. Cannot author new detection — which is exactly the Datadog "
                "role's own boundary — so it holds no `generate` or `propose`."),
    },
    "observability-engineer": {
        "display": "Observability Engineer",
        "datadog_permissions": ["monitors_write", "monitors_downtime", "slos_write",
                                "slos_corrections", "dashboards_write", "notebooks_write",
                                "workflows_write", "monitor_config_policy_write"],
        "capabilities": ["read", "plan", "generate", "propose"],
        "why": ("Authors monitoring change. In Datadog that is a write permission; "
                "HERE it is only ever the right to open a pull request — the apply "
                "still belongs to CI."),
    },
    "platform-admin": {
        "display": "Platform Admin",
        "datadog_permissions": ["org_management", "api_keys_write", "user_access_manage",
                                "monitors_write", "monitors_downtime", "slos_write",
                                "dashboards_write", "notebooks_write", "workflows_write",
                                "monitor_config_policy_write", "incident_settings_write",
                                "security_monitoring_rules_write"],
        "capabilities": ["read", "plan", "generate", "propose", "admin"],
        "why": "Everything above, plus reading this server's own audit log.",
    },
}

WRITE_CAPABILITIES = frozenset({"generate", "propose"})

# Rate limits: (max calls, window seconds). Reads are cheap and a chat client
# makes many; proposals open pull requests other humans must review, so the
# budget there is a working day's worth of genuine changes, not a burst.
RATE_LIMITS = {
    "read": (240, 60),
    "plan": (30, 60),
    "generate": (30, 60),
    "propose": (10, 3600),
    "admin": (30, 60),
}

# Which environments need a second person. Production changes to a monitoring
# platform are how an org goes blind; `deploy.yml` already puts production
# behind the `datadog-production` approval environment, and this is the same
# gate one step earlier.
APPROVAL_REQUIRED_ENVS = frozenset({"prod"})

ANONYMOUS = "anonymous"

# ---------------------------------------------------------------------------
# Redaction. Applied to every argument before it is written to the audit log
# and to every error string before it leaves the process. Two passes because
# secrets arrive both as named fields and as bare strings pasted into a YAML
# body: a value under `api_key:` and a 40-hex blob in a query both have to go.
# ---------------------------------------------------------------------------
SECRET_KEY_RE = re.compile(
    r"(?i)(token|api[_-]?key|app[_-]?key|secret|password|passwd|credential|"
    r"authorization|private[_-]?key|dd_api|dd_app)")
SECRET_VALUE_RES = (
    re.compile(r"(?i)\bdd[a-z]{0,4}_[A-Za-z0-9]{20,}\b"),     # Datadog-style keys
    re.compile(r"\b[0-9a-f]{32}\b"),                          # 32-hex API keys
    re.compile(r"\b[0-9a-f]{40}\b"),                          # 40-hex app keys
    re.compile(r"(?i)\bgh[pousr]_[A-Za-z0-9]{20,}\b"),        # GitHub tokens
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-]{10,}"),
)
REDACTED = "***redacted***"


def redact(value):
    """Recursively strip anything that looks like a credential."""
    if isinstance(value, dict):
        return {k: (REDACTED if SECRET_KEY_RE.search(str(k)) else redact(v))
                for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    if isinstance(value, str):
        out = value
        for rx in SECRET_VALUE_RES:
            out = rx.sub(REDACTED, out)
        return out
    return value


# ---------------------------------------------------------------------------
# Errors. Each carries a machine-readable code so a client can branch on the
# reason instead of parsing prose, and a message that says what to do next —
# "denied" with no remedy just produces a support ticket.
# ---------------------------------------------------------------------------
class GovernanceError(Exception):
    code = "governance_error"

    def __init__(self, message: str, remedy: str = ""):
        super().__init__(message)
        self.message = message
        self.remedy = remedy

    def to_dict(self) -> dict:
        return {"code": self.code, "error": redact(self.message),
                "remedy": redact(self.remedy)}


class AuthenticationError(GovernanceError):
    code = "unauthenticated"


class AuthorizationError(GovernanceError):
    code = "forbidden"


class EnvironmentDenied(GovernanceError):
    code = "environment_denied"


class RateLimited(GovernanceError):
    code = "rate_limited"


class InputInvalid(GovernanceError):
    code = "invalid_input"


class ApprovalRequired(GovernanceError):
    code = "approval_required"


class PlanRequired(GovernanceError):
    code = "plan_required"


# ---------------------------------------------------------------------------
@dataclasses.dataclass(frozen=True)
class Principal:
    id: str
    role: str
    display: str = ""
    environments: tuple[str, ...] = ()
    approver: bool = False
    authenticated: bool = False

    @property
    def capabilities(self) -> tuple[str, ...]:
        return tuple(ROLES[self.role]["capabilities"])

    def holds(self, capability: str) -> bool:
        return capability in self.capabilities

    def to_dict(self) -> dict:
        return {"id": self.id, "role": self.role, "display": self.display,
                "capabilities": list(self.capabilities),
                "environments": list(self.environments),
                "approver": self.approver, "authenticated": self.authenticated}


def principals_path() -> Path:
    return Path(os.environ.get("OBS_MCP_PRINCIPALS", MCP_DIR / "principals.yaml"))


def load_principals(path: Path | None = None) -> dict:
    path = path or principals_path()
    if not path.exists():
        return {}
    doc = yaml.safe_load(path.read_text()) or {}
    return doc.get("principals", {}) or {}


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def authenticate(token: str | None = None, *, path: Path | None = None) -> Principal:
    """Resolve the bearer token to a principal.

    stdio has no per-request auth header — the transport IS the trust boundary,
    so the token is presented once, at startup, in OBS_MCP_TOKEN. What that
    buys is not secrecy (the parent process already trusts us) but ATTRIBUTION:
    the audit log names a principal instead of "somebody's laptop".

    No token is a legitimate state — a developer exploring the platform
    offline. It resolves to the anonymous READ-ONLY principal rather than
    failing, because refusing to start would only teach people to export a
    powerful token they do not need.
    """
    token = token if token is not None else os.environ.get("OBS_MCP_TOKEN")
    if not token:
        return Principal(id=ANONYMOUS, role="viewer-auditor",
                         display="Anonymous (unauthenticated, read-only)",
                         environments=(), approver=False, authenticated=False)

    presented = _digest(token)
    for pid, spec in sorted(load_principals(path).items()):
        stored = str(spec.get("token_sha256", ""))
        # compare_digest, not ==, so a wrong token cannot be discovered one
        # character at a time by timing the rejection.
        if stored and hmac.compare_digest(stored, presented):
            role = spec.get("role")
            if role not in ROLES:
                raise AuthenticationError(
                    f"principal {pid!r} names role {role!r}, which is not one of the "
                    f"platform's four roles ({', '.join(sorted(ROLES))})",
                    remedy="fix the role in the principals file")
            return Principal(
                id=pid, role=role, display=spec.get("display", pid),
                environments=tuple(spec.get("environments", []) or []),
                approver=bool(spec.get("approver", False)), authenticated=True)

    raise AuthenticationError(
        "the presented OBS_MCP_TOKEN matches no principal",
        remedy="check OBS_MCP_PRINCIPALS points at the right file and the token is current")


# ---------------------------------------------------------------------------
class RateLimiter:
    """Fixed-window counters, per (principal, capability).

    A token bucket would be smoother; a fixed window is auditable — the log can
    state exactly which window rejected the call, which is what an operator
    asks after being throttled.
    """

    def __init__(self, limits: dict | None = None, clock=time.monotonic):
        self.limits = dict(limits or RATE_LIMITS)
        self.clock = clock
        self._windows: dict[tuple[str, str], list] = {}

    def check(self, principal_id: str, capability: str) -> None:
        limit, window = self.limits.get(capability, (60, 60))
        now = self.clock()
        key = (principal_id, capability)
        start, count = self._windows.get(key, (now, 0))
        if now - start >= window:
            start, count = now, 0
        if count >= limit:
            raise RateLimited(
                f"{principal_id} exceeded the {capability} budget of {limit} calls "
                f"per {window}s",
                remedy=f"retry in {int(window - (now - start)) + 1}s")
        self._windows[key] = (start, count + 1)


# ---------------------------------------------------------------------------
class AuditLog:
    """Append-only JSONL. One line per call, written whatever the outcome.

    Refused calls are the ones worth having: "who tried to open a production PR
    without an approver" is the question an audit actually asks. The line is
    written in a `finally`, so a handler that raises still leaves a record.
    """

    def __init__(self, path: Path | None = None):
        self.path = Path(path or os.environ.get(
            "OBS_MCP_AUDIT_LOG", REPO_ROOT / "generated" / "mcp" / "audit.jsonl"))
        self.records: list[dict] = []

    def write(self, record: dict) -> dict:
        record = redact(record)
        self.records.append(record)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, sort_keys=True, default=str) + "\n")
        except OSError as exc:
            # A read-only filesystem must not silently disable auditing, and
            # must not take the server down either. Surface it on the record so
            # the gap is visible in the returned envelope.
            record["audit_write_error"] = str(exc)
        return record

    def tail(self, limit: int = 50, tool: str | None = None,
             principal: str | None = None) -> list[dict]:
        rows = self.records
        if not rows and self.path.exists():
            rows = [json.loads(line) for line in self.path.read_text().splitlines() if line]
        if tool:
            rows = [r for r in rows if fnmatch.fnmatch(r.get("tool", ""), tool)]
        if principal:
            rows = [r for r in rows if r.get("principal") == principal]
        return rows[-limit:]


# ---------------------------------------------------------------------------
class PlanLedger:
    """Plan-before-apply, enforced by content hash.

    `obs.plan` and `obs.preview_onboarding` return a `plan_token` — the digest
    of the exact file set they evaluated. `obs.propose_change` will not open a
    pull request without one that matches the files it was handed. So a caller
    physically cannot propose content nobody has planned, and cannot plan one
    thing and propose another: editing a single byte changes the digest.
    """

    def __init__(self, ttl_seconds: int = 3600, clock=time.monotonic):
        self.ttl = ttl_seconds
        self.clock = clock
        self._tokens: dict[str, dict] = {}

    @staticmethod
    def content_hash(files: dict[str, str]) -> str:
        # `plan-` prefix and 24 hex digits, deliberately: a bare 32- or 40-hex
        # string matches the secret-shape redactor above, and a plan token that
        # gets redacted out of its own mismatch error is useless to debug.
        canonical = json.dumps({k: files[k] for k in sorted(files)}, sort_keys=True)
        return "plan-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]

    def record(self, files: dict[str, str], principal_id: str, summary: dict) -> str:
        token = self.content_hash(files)
        self._tokens[token] = {"at": self.clock(), "principal": principal_id,
                               "summary": summary}
        return token

    def verify(self, token: str, files: dict[str, str]) -> dict:
        expected = self.content_hash(files)
        entry = self._tokens.get(token)
        if entry is None:
            raise PlanRequired(
                "no plan has been run for this change in this session",
                remedy="call obs.plan with the same files and pass the plan_token it returns")
        if self.clock() - entry["at"] > self.ttl:
            self._tokens.pop(token, None)
            raise PlanRequired(f"plan_token expired after {self.ttl}s",
                               remedy="re-run obs.plan")
        if token != expected:
            raise PlanRequired(
                "the files differ from the ones that were planned "
                f"(planned {token}, supplied {expected})",
                remedy="re-run obs.plan on the exact content you intend to propose")
        return entry


# ---------------------------------------------------------------------------
def authorize(principal: Principal, tool: str, capability: str) -> None:
    if capability not in CAPABILITIES:
        raise InputInvalid(f"tool {tool!r} declares unknown capability {capability!r}")
    if principal.holds(capability):
        return
    holders = sorted(r for r, spec in ROLES.items() if capability in spec["capabilities"])
    raise AuthorizationError(
        f"{principal.id} holds role {principal.role!r} "
        f"({', '.join(principal.capabilities)}) and {tool} needs {capability!r}",
        remedy=f"{capability!r} is held by: {', '.join(holders)}")


def authorize_environments(principal: Principal, envs) -> None:
    """A change may only target environments the principal was granted."""
    envs = sorted(set(envs or []))
    if not envs:
        return
    missing = [e for e in envs if e not in principal.environments]
    if missing:
        raise EnvironmentDenied(
            f"{principal.id} may propose changes for "
            f"{', '.join(principal.environments) or '(none)'} but this change targets "
            f"{', '.join(missing)}",
            remedy="widen `environments` for the principal, or narrow the change")


def require_approval(principal: Principal, envs, approval: dict | None,
                     *, path: Path | None = None) -> dict:
    """Second-person approval for anything that reaches production.

    Deliberately structural, not advisory: the approver must be a DIFFERENT,
    authenticated principal that carries `approver: true`, and the record of
    who approved goes into the audit line and the pull-request body. Self
    approval is the failure mode this exists to stop.
    """
    envs = sorted(set(envs or []))
    needs = sorted(set(envs) & APPROVAL_REQUIRED_ENVS)
    if not needs:
        return {"required": False, "environments": envs}
    if not approval or not approval.get("approver"):
        raise ApprovalRequired(
            f"changes targeting {', '.join(needs)} need a named approver",
            remedy="pass approval={approver: <principal id>, ticket: <change record>}")
    approver_id = str(approval["approver"])
    if approver_id == principal.id:
        raise ApprovalRequired(
            f"{principal.id} cannot approve their own production change",
            remedy="name a second principal that carries `approver: true`")
    spec = load_principals(path).get(approver_id)
    if not spec or not spec.get("approver"):
        raise ApprovalRequired(
            f"{approver_id!r} is not a registered approver",
            remedy="approvers carry `approver: true` in the principals file")
    if not approval.get("ticket"):
        raise ApprovalRequired(
            "production changes need a change record reference",
            remedy="pass approval.ticket, e.g. the ServiceNow change number")
    return {"required": True, "environments": needs, "approver": approver_id,
            "approver_role": spec.get("role"), "ticket": str(approval["ticket"])}
