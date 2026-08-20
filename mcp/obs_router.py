"""INTENT ROUTER (§46) — one door in front of three planes.

Every call, whatever its shape, goes through exactly this sequence:

    request
       │
       ├─ 1. resolve      tool name, or natural language → question id
       ├─ 2. validate     the tool's own JSON Schema, before the handler exists
       ├─ 3. authorize    role → capability (mcp/obs_governance.py)
       ├─ 4. rate limit   per principal, per capability
       ├─ 5. dispatch     to ONE plane
       │        read plane        state + Datadog GET; mutates nothing
       │        operations plane  validate / resolve / preview / plan / generate
       │        git-yaml plane    branch → commit → pull request
       └─ 6. audit        one JSON line, allowed or refused, always

The planes are not decoration. They are how the security property is stated in
one sentence a reviewer can check: only the git-yaml plane can write, only the
`propose` capability reaches it, and only `observability-engineer` and
`platform-admin` hold that capability. Everything else in this server is a
pure function of state.
"""
from __future__ import annotations

import dataclasses
import re
import time
import uuid

import obs_ask
import obs_governance as gov
import obs_state
from obs_tools import PLANE_CAPABILITIES, TOOLS

STOPWORDS = {"what", "which", "who", "why", "how", "is", "are", "the", "a", "an", "of",
             "in", "on", "to", "for", "do", "does", "we", "our", "my", "me", "and",
             "right", "now", "currently", "please", "show", "list", "tell", "give"}


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", str(text).lower()).strip()


def _tokens(text: str) -> set[str]:
    return {t for t in _normalize(text).split() if t and t not in STOPWORDS}


def resolve_intent(text: str) -> tuple[str | None, dict]:
    """Natural language → question id, deterministically.

    Substring match on the curated phrasings first (a phrase match is a strong,
    explainable signal), then token overlap with the question title and id as a
    tie-break. No model, no embedding: the routing decision has to be
    reproducible in a test and explainable in an audit line, and "the router
    felt like it" is neither.
    """
    norm = _normalize(text)
    toks = _tokens(text)
    scored = []
    for qid, spec in obs_ask.QUESTIONS.items():
        # Three signals, strongest first. The subset test is what catches the
        # normal case — "which SLOs are burning" does not CONTAIN the phrase
        # "slos burning", but every content word of the phrase is present.
        phrase = max((len(_normalize(p)) for p in spec.patterns
                      if _normalize(p) and _normalize(p) in norm), default=0)
        subset = max((len(_tokens(p)) for p in spec.patterns
                      if _tokens(p) and _tokens(p) <= toks), default=0)
        overlap = len(toks & (_tokens(spec.title) | _tokens(qid.replace("_", " "))))
        score = phrase * 10 + subset * 6 + overlap
        if score:
            scored.append((score, qid))
    if not scored:
        return None, {"match": "none", "confidence": 0.0, "candidates": []}
    scored.sort(key=lambda s: (-s[0], s[1]))
    best, runner = scored[0], (scored[1] if len(scored) > 1 else None)
    margin = best[0] - (runner[0] if runner else 0)
    confidence = round(min(1.0, best[0] / (best[0] + (runner[0] if runner else 0) + 1e-9)), 3)
    return best[1], {
        "match": "phrase" if best[0] >= 10 else "tokens",
        "confidence": confidence,
        "margin": margin,
        "candidates": [{"question": q, "score": s} for s, q in scored[:5]],
        "note": ("routing is deterministic: curated phrasings first, then token overlap. "
                 "Pass a question id from obs.list_questions to bypass it."),
    }


def enrich_params(state, qid: str, text: str, params: dict) -> dict:
    """Lift obvious entities out of the phrasing — never over the caller's own.

    Only exact identifiers that already exist in the platform are lifted (a
    registered service, a team handle, an archetype id, an SLO id, a monitor
    id). Guessing a value that is not in the catalog would produce a confident
    answer about something that does not exist.
    """
    out = dict(params or {})
    words = set(_normalize(text).split()) | set(re.findall(r"[a-z0-9][a-z0-9._-]+", str(text).lower()))
    spec = obs_ask.QUESTIONS[qid]

    def take(key, candidates):
        if key in spec.params and key not in out:
            hit = sorted((c for c in candidates if c and c.lower() in words), key=len)
            if hit:
                out[key] = hit[-1]

    take("service", list(state.services))
    take("team", list(state.policy["teams"]))
    take("archetype", list(state.policy["archetypes"]))
    take("slo_id", list(state.policy["slos"]))
    if "monitor_id" in spec.params and "monitor_id" not in out:
        for m in re.findall(r"\b\d{1,8}\b", str(text)):
            if m in state.monitors_by_id:
                out["monitor_id"] = m
                break
    if "entity" in spec.params and "entity" not in out:
        for name in state.services:
            if name.lower() in words:
                out["entity"] = name
                break
    return out


# ---------------------------------------------------------------------------
def validate_input(args: dict, schema: dict, tool_name: str) -> None:
    """Enforce the same schema `tools/list` advertises.

    A published contract that is not enforced is a lie with documentation.
    """
    try:
        import jsonschema
    except ImportError as exc:                        # pragma: no cover
        raise gov.InputInvalid(
            "jsonschema is required to enforce tool input contracts",
            remedy="pip install -r mcp/requirements.txt") from exc
    errors = sorted(jsonschema.Draft202012Validator(schema).iter_errors(args or {}),
                    key=lambda e: list(e.path))
    if errors:
        raise gov.InputInvalid(
            f"{tool_name}: " + "; ".join(
                f"{'/'.join(str(p) for p in e.path) or '(root)'}: {e.message}"
                for e in errors[:5]),
            remedy="see the tool's inputSchema in tools/list")


@dataclasses.dataclass
class Context:
    """Everything one call is allowed to touch."""
    state: obs_state.PlatformState
    principal: gov.Principal
    audit: gov.AuditLog
    limiter: gov.RateLimiter
    ledger: gov.PlanLedger
    config: dict = dataclasses.field(default_factory=dict)

    def reload(self) -> None:
        obs_state.reset_state()
        self.state = obs_state.get_state(self.state.mode,
                                         estate_size=self.state.estate_size,
                                         runtime_fixture=self.state.runtime_fixture)


def dispatch(ctx: Context, name: str, args: dict | None = None) -> dict:
    """Run one tool call through the whole pipeline. Never raises for policy.

    A refusal is a RESULT, not an exception: an MCP client shows the user what
    came back, and "forbidden, here is who holds that capability" is far more
    useful to them than a transport-level error.
    """
    args = args or {}
    call_id = uuid.uuid4().hex[:12]
    started = time.monotonic()
    tool = TOOLS.get(name)
    record = {
        "call_id": call_id,
        "ts": obs_state.oc.utcnow().isoformat(),
        "principal": ctx.principal.id, "role": ctx.principal.role,
        "authenticated": ctx.principal.authenticated,
        "tool": name,
        "plane": tool.plane if tool else None,
        "capability": tool.capability if tool else None,
        "mode": ctx.state.mode,
        "args": gov.redact(args),
        "decision": "allow",
    }
    try:
        if tool is None:
            raise gov.InputInvalid(
                f"unknown tool {name!r}",
                remedy=f"known tools: {', '.join(sorted(TOOLS))}")
        if tool.capability not in PLANE_CAPABILITIES[tool.plane]:   # pragma: no cover
            raise gov.InputInvalid(
                f"{name} declares capability {tool.capability!r} on plane {tool.plane!r}")

        validate_input(args, tool.input_schema, name)
        gov.authorize(ctx.principal, name, tool.capability)
        ctx.limiter.check(ctx.principal.id, tool.capability)

        # Natural-language calls get their parameters enriched here, in the
        # router, so the enrichment is audited alongside the routing decision.
        if name == "obs.ask" and args["question"] not in obs_ask.QUESTIONS:
            qid, routing = resolve_intent(args["question"])
            record["routed_to"] = qid
            record["routing_confidence"] = routing.get("confidence")
            if qid:
                args = {**args, "params": enrich_params(ctx.state, qid,
                                                        args["question"],
                                                        args.get("params"))}

        result = tool.handler(ctx, args)
        record["result_summary"] = _summarize(result)
        return {"ok": True, "call_id": call_id, "tool": name, "plane": tool.plane,
                "principal": ctx.principal.id, "result": result}

    except gov.GovernanceError as exc:
        record["decision"] = "deny"
        record["error"] = exc.to_dict()
        return {"ok": False, "call_id": call_id, "tool": name,
                "principal": ctx.principal.id, "error": exc.to_dict()}
    except obs_state.DatadogUnavailable as exc:
        record["decision"] = "error"
        record["error"] = {"code": "datadog_unavailable", "error": str(exc)}
        return {"ok": False, "call_id": call_id, "tool": name,
                "error": {"code": "datadog_unavailable", "error": gov.redact(str(exc)),
                          "remedy": "run in fixtures mode, or export DD_API_KEY/DD_APP_KEY"}}
    except Exception as exc:                          # noqa: BLE001
        record["decision"] = "error"
        # The message is redacted before it is logged AND before it is returned:
        # a stack-trace string can carry a token that was passed as an argument.
        record["error"] = {"code": "tool_error", "error": gov.redact(str(exc)),
                           "type": type(exc).__name__}
        return {"ok": False, "call_id": call_id, "tool": name,
                "error": {"code": "tool_error", "type": type(exc).__name__,
                          "error": gov.redact(str(exc))}}
    finally:
        record["duration_ms"] = round((time.monotonic() - started) * 1000, 2)
        # In a `finally` on purpose: a handler that blows up must still leave a
        # record that it was called.
        ctx.audit.write(record)


def _summarize(result) -> dict:
    """A shape, not the payload. The audit log records THAT a call returned a
    coverage report, never the report — logs that copy their payload become
    unreadable and start carrying data they were never meant to retain."""
    if isinstance(result, dict):
        return {"keys": sorted(result)[:15],
                "answerable": result.get("answer", {}).get("answerable")
                if isinstance(result.get("answer"), dict) else result.get("answerable"),
                "dry_run": result.get("dry_run"),
                "pull_request_url": result.get("pull_request_url")}
    return {"type": type(result).__name__}


def build_context(*, mode: str = "fixtures", token: str | None = None,
                  config: dict | None = None) -> Context:
    config = dict(config or {})
    principal = gov.authenticate(token)
    return Context(
        state=obs_state.get_state(mode, estate_size=config.get("estate_size")),
        principal=principal,
        audit=gov.AuditLog(config.get("audit_log")),
        limiter=gov.RateLimiter(config.get("rate_limits")),
        ledger=gov.PlanLedger(config.get("plan_ttl_seconds", 3600)),
        config=config,
    )
