#!/usr/bin/env python3
"""OBSERVABILITY MCP SERVER — Model Context Protocol over stdio.

    python3 mcp/server.py                       # speak MCP on stdin/stdout
    python3 mcp/server.py --list-tools          # the tool surface, as JSON
    python3 mcp/server.py --call obs.ask --args '{"question":"what is unhealthy now"}'
    python3 mcp/server.py --self-test           # exercise every tool offline

INDEPENDENT OF BITS AI (§42). Nothing here calls Datadog's own MCP server or
requires it to be installed. Bits AI can sit beside this one in a client's
config — they answer different questions, and a client that has both simply
sees both tool sets. What this server knows that Bits AI cannot is WHY: the
policy hierarchy that decided a monitor exists, which is in this repository and
nowhere else.

NO MCP SDK DEPENDENCY. The wire format is JSON-RPC 2.0 in newline-delimited
JSON, which is ~80 lines of stdlib. The alternative is a new runtime dependency
in a repository whose entire Python surface is PyYAML + requests, for a protocol
this file already implements completely. If the SDK becomes a hard requirement
for a feature we need (sampling, resources, prompts), that is the moment to add
it — not before.

Transport note: MCP stdio requires that NOTHING but protocol frames reach
stdout. Every diagnostic in this file goes to stderr, and the tools underneath
never print.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import obs_ask                                     # noqa: E402
import obs_governance as gov                       # noqa: E402
import obs_router                                  # noqa: E402
import obs_state                                   # noqa: E402
from obs_tools import TOOLS, mcp_tool_list         # noqa: E402

SERVER_NAME = "enterprise-observability"
SERVER_VERSION = "1.0.0"
# The revisions this server implements. An older client that asks for one of
# these gets it back; anything else is answered with our newest, which is what
# the specification says to do rather than failing the handshake.
SUPPORTED_PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")

INSTRUCTIONS = """\
Grounded question answering and governed change proposal for the enterprise
Datadog monitoring platform.

ASK (obs.ask, obs.list_questions): 30 questions answered from the platform's
own policy engine and the Datadog API. Every answer cites object ids, counts
and a source. Where the data does not exist in this org the answer says so and
names the gap — it never estimates.

ACT (obs.validate_yaml, obs.preview_onboarding, obs.resolve_*, obs.generate_*,
obs.plan, obs.propose_change): changes flow MCP -> YAML -> git branch -> pull
request -> CI -> Terraform -> Datadog. There is no path from this server to the
Datadog configuration API. obs.propose_change is a DRY RUN unless dry_run is
explicitly false, requires a plan_token from obs.plan for the identical files,
and requires a named second approver for anything reaching production.
"""


def _err(code: int, message: str, data=None) -> dict:
    out = {"code": code, "message": message}
    if data is not None:
        out["data"] = data
    return out


class Server:
    def __init__(self, ctx: obs_router.Context):
        self.ctx = ctx
        self.initialized = False

    # -- JSON-RPC ----------------------------------------------------------
    def handle(self, msg: dict):
        method = msg.get("method")
        mid = msg.get("id")
        params = msg.get("params") or {}

        if method == "initialize":
            requested = params.get("protocolVersion")
            version = requested if requested in SUPPORTED_PROTOCOLS else SUPPORTED_PROTOCOLS[0]
            self.initialized = True
            return self._ok(mid, {
                "protocolVersion": version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                "instructions": INSTRUCTIONS,
            })

        if method in ("notifications/initialized", "notifications/cancelled"):
            return None                      # notifications take no response

        if method == "ping":
            return self._ok(mid, {})

        if method == "tools/list":
            return self._ok(mid, {"tools": mcp_tool_list()})

        if method == "tools/call":
            name = params.get("name")
            args = params.get("arguments") or {}
            envelope = obs_router.dispatch(self.ctx, name, args)
            # MCP reports a TOOL failure inside the result with isError, not as
            # a protocol error: a refused call is a normal outcome the model has
            # to be able to read and act on.
            payload = envelope.get("result") if envelope["ok"] else envelope["error"]
            return self._ok(mid, {
                "content": [{"type": "text",
                             "text": json.dumps(payload, indent=2, default=str)}],
                "isError": not envelope["ok"],
            })

        if method in ("resources/list", "prompts/list"):
            # Declared unsupported rather than erroring: clients probe for these.
            return self._ok(mid, {"resources": []} if method.startswith("resources")
                            else {"prompts": []})

        if mid is None:
            return None
        return self._error(mid, _err(-32601, f"method not found: {method}"))

    def _ok(self, mid, result):
        return None if mid is None else {"jsonrpc": "2.0", "id": mid, "result": result}

    def _error(self, mid, error):
        return {"jsonrpc": "2.0", "id": mid, "error": error}

    # -- stdio loop --------------------------------------------------------
    def serve(self, stdin=None, stdout=None) -> int:
        stdin = stdin or sys.stdin
        stdout = stdout or sys.stdout
        for line in stdin:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError as exc:
                self._write(stdout, {"jsonrpc": "2.0", "id": None,
                                     "error": _err(-32700, f"parse error: {exc}")})
                continue
            try:
                response = self.handle(msg)
            except Exception as exc:                   # noqa: BLE001
                response = self._error(msg.get("id"),
                                       _err(-32603, "internal error",
                                            gov.redact(str(exc))))
            if response is not None:
                self._write(stdout, response)
        return 0

    @staticmethod
    def _write(stdout, obj) -> None:
        stdout.write(json.dumps(obj, default=str) + "\n")
        stdout.flush()


# ---------------------------------------------------------------------------
def build(mode: str | None = None) -> obs_router.Context:
    mode = mode or os.environ.get("OBS_MCP_MODE") or (
        "live" if os.environ.get("DD_API_KEY") and os.environ.get("DD_APP_KEY")
        and os.environ.get("OBS_MCP_LIVE") == "1" else "fixtures")
    ctx = obs_router.build_context(mode=mode)
    print(f"[{SERVER_NAME}] mode={mode} principal={ctx.principal.id} "
          f"role={ctx.principal.role} caps={','.join(ctx.principal.capabilities)} "
          f"audit={ctx.audit.path}", file=sys.stderr)
    if not ctx.principal.authenticated:
        print(f"[{SERVER_NAME}] WARNING: no OBS_MCP_TOKEN presented — running as the "
              "anonymous READ-ONLY principal. Act mode is unavailable.", file=sys.stderr)
    return ctx


def self_test(ctx) -> int:
    """Call every read/plan tool once, offline. A smoke test for operators."""
    failures = 0
    for name in sorted(TOOLS):
        tool = TOOLS[name]
        if tool.capability not in ("read", "plan"):
            continue
        args = {"obs.ask": {"question": "coverage_percentage"},
                "obs.get_entity": {"entity": "identity-api"},
                "obs.get_monitor": {"monitor_id": "1"},
                "obs.explain_inheritance": {"service": "identity-api",
                                            "archetype": "api-availability",
                                            "what": "monitor"},
                "obs.validate_yaml": {"yaml": "service:\n  name: x\n"},
                "obs.resolve_profile": {"service_archetype": "api", "tier": "tier0",
                                        "env": "prod"},
                "obs.resolve_slo": {"tier": "tier0", "service_archetype": "api"},
                "obs.missing_telemetry": {"service_archetype": "api"},
                "obs.preview_onboarding": {"service": {
                    "name": "probe-service", "team": "sre", "tier": "tier2",
                    "service_archetype": "api", "description": "a probe service",
                    "envs": ["prod"]}},
                "obs.plan": {"files": {}},
                }.get(name, {})
        env = obs_router.dispatch(ctx, name, args)
        if env["ok"]:
            status, detail = "ok  ", ""
        elif env["error"].get("code") == "forbidden":
            # Not a failure: the current principal legitimately lacks the
            # capability. Reporting it as one would train an operator to ignore
            # the self-test.
            status, detail = "skip", f"({ctx.principal.role} holds no {tool.capability})"
        else:
            failures += 1
            status, detail = "FAIL", env["error"].get("code", "")
        print(f"  {status} {name} {detail}", file=sys.stderr)
    print(f"self-test: {failures} failure(s) as principal {ctx.principal.id} "
          f"({ctx.principal.role})", file=sys.stderr)
    return 1 if failures else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--mode", choices=["fixtures", "live"],
                    help="default: fixtures, unless OBS_MCP_LIVE=1 with DD keys")
    ap.add_argument("--list-tools", action="store_true")
    ap.add_argument("--list-questions", action="store_true")
    ap.add_argument("--call", metavar="TOOL")
    ap.add_argument("--args", default="{}", metavar="JSON")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)

    if a.list_tools:
        print(json.dumps([{
            "name": t.name, "plane": t.plane, "capability": t.capability,
            "mutates": t.mutates, "description": t.description,
            "inputSchema": t.input_schema,
        } for t in (TOOLS[n] for n in sorted(TOOLS))], indent=2))
        return 0
    if a.list_questions:
        print(json.dumps(obs_ask.catalog(), indent=2))
        return 0

    ctx = build(a.mode)
    if a.self_test:
        return self_test(ctx)
    if a.call:
        env = obs_router.dispatch(ctx, a.call, json.loads(a.args))
        print(json.dumps(env, indent=2, default=str))
        return 0 if env["ok"] else 1
    return Server(ctx).serve()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (KeyboardInterrupt, BrokenPipeError):
        sys.exit(0)
    except obs_state.DatadogUnavailable as exc:
        print(f"[{SERVER_NAME}] {exc}", file=sys.stderr)
        sys.exit(2)
