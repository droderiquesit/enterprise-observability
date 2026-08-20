"""TOOL CONTRACTS — the surface this server publishes is the surface it enforces.

The failure this file exists to prevent: a tool whose advertised `inputSchema`
and actual behaviour drift apart, so a client builds a valid call the server
rejects — or worse, builds an invalid call the server accepts.
"""
import io
import json

import jsonschema
import pytest

import obs_ask
import obs_router
import server as mcp_server
from obs_tools import PLANE_CAPABILITIES, PLANES, TOOLS, mcp_tool_list

import obs_governance as gov


def test_every_tool_declares_a_plane_and_a_capability():
    assert TOOLS, "the registry is empty"
    for name, tool in TOOLS.items():
        assert name.startswith("obs."), f"{name} is outside the obs.* namespace"
        assert tool.plane in PLANES, f"{name}: unknown plane {tool.plane!r}"
        assert tool.capability in gov.CAPABILITIES, f"{name}: unknown capability"
        assert tool.capability in PLANE_CAPABILITIES[tool.plane], (
            f"{name}: capability {tool.capability!r} may not act on the "
            f"{tool.plane!r} plane")
        assert tool.description.strip(), f"{name} has no description"


def test_only_the_git_yaml_plane_mutates():
    """The security property, asserted rather than described.

    If a future tool sets mutates=True on the read or operations plane this
    fails, which is the point: those planes are pure by construction.
    """
    for name, tool in TOOLS.items():
        if tool.mutates:
            assert tool.plane == "git-yaml", f"{name} mutates but is not on the git plane"
            assert tool.capability == "propose"
    assert [n for n, t in TOOLS.items() if t.mutates] == ["obs.propose_change"]


def test_every_input_schema_is_a_valid_json_schema():
    for name, tool in TOOLS.items():
        jsonschema.Draft202012Validator.check_schema(tool.input_schema)
        assert tool.input_schema["type"] == "object", name
        for req in tool.input_schema.get("required", []):
            assert req in tool.input_schema["properties"], f"{name}: required {req!r} undeclared"


def test_mcp_tool_list_is_the_wire_shape():
    listed = mcp_tool_list()
    assert len(listed) == len(TOOLS)
    for entry in listed:
        assert set(entry) == {"name", "description", "inputSchema"}
        assert entry["name"] in TOOLS


def test_input_validation_rejects_a_call_that_violates_the_published_schema(auditor):
    # `question` is required and must be a string; the schema is what says so,
    # and the router is what enforces it.
    out = obs_router.dispatch(auditor, "obs.ask", {})
    assert out["ok"] is False
    assert out["error"]["code"] == "invalid_input"

    out = obs_router.dispatch(auditor, "obs.ask", {"question": 7})
    assert out["ok"] is False and out["error"]["code"] == "invalid_input"

    out = obs_router.dispatch(auditor, "obs.ask", {"question": "coverage_percentage",
                                                   "unexpected": 1})
    assert out["ok"] is False, "additionalProperties is false and must be enforced"


def test_unknown_tool_is_refused_with_the_known_list(auditor):
    out = obs_router.dispatch(auditor, "obs.does_not_exist", {})
    assert out["ok"] is False
    assert out["error"]["code"] == "invalid_input"
    assert "obs.ask" in out["error"]["remedy"]


def test_every_read_tool_answers_for_a_read_only_principal(auditor):
    for name, tool in sorted(TOOLS.items()):
        if tool.capability != "read":
            continue
        args = {
            "obs.ask": {"question": "coverage_percentage"},
            "obs.get_entity": {"entity": "identity-api"},
            "obs.get_monitor": {"monitor_id": "1"},
            "obs.explain_inheritance": {"service": "identity-api", "what": "slo"},
            "obs.validate_yaml": {"yaml": "service:\n  name: x\n"},
        }.get(name, {})
        out = obs_router.dispatch(auditor, name, args)
        assert out["ok"] is True, f"{name} failed for a viewer-auditor: {out.get('error')}"


def test_question_catalog_is_complete_and_well_formed():
    catalog = obs_ask.catalog()
    assert len(catalog) >= 30, "§43 asks for a broad question set"
    ids = {q["id"] for q in catalog}
    # The questions §43 names explicitly must all be present.
    required = {
        "unhealthy_now", "why_unhealthy", "what_changed", "affected_entities",
        "probable_root_cause", "correlated_signals", "active_incidents",
        "who_is_on_call", "slos_burning", "slo_breach_first", "services_without_slos",
        "entities_without_owners", "broken_agents", "missing_integrations",
        "noisy_monitors", "never_triggered_monitors", "services_lacking_monitoring",
        "coverage_percentage", "mttr", "top_reliability_risks",
        "why_service_inherited_monitor", "why_service_received_slo",
        "telemetry_feeding_slo", "what_if_merged",
    }
    assert required <= ids, f"missing §43 questions: {sorted(required - ids)}"
    for q in catalog:
        assert q["availability"] in obs_ask.AVAILABILITY
        assert q["title"].strip()


# --- the MCP protocol itself -----------------------------------------------

def _rpc(srv, messages):
    out = io.StringIO()
    srv.serve(stdin=io.StringIO("\n".join(json.dumps(m) for m in messages) + "\n"),
              stdout=out)
    return [json.loads(line) for line in out.getvalue().splitlines()]


@pytest.fixture
def srv(auditor):
    return mcp_server.Server(auditor)


def test_initialize_handshake_and_tools_list(srv):
    responses = _rpc(srv, [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                    "clientInfo": {"name": "test", "version": "0"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ])
    # The notification produces no response — that is protocol, not an omission.
    assert [r["id"] for r in responses] == [1, 2]
    init = responses[0]["result"]
    assert init["protocolVersion"] == "2025-06-18"
    assert init["capabilities"]["tools"] is not None
    assert init["serverInfo"]["name"] == mcp_server.SERVER_NAME
    assert len(responses[1]["result"]["tools"]) == len(TOOLS)


def test_unknown_protocol_version_still_completes_the_handshake(srv):
    r = _rpc(srv, [{"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": "1999-01-01"}}])
    assert r[0]["result"]["protocolVersion"] in mcp_server.SUPPORTED_PROTOCOLS


def test_tools_call_returns_content_and_reports_refusal_as_iserror(srv):
    r = _rpc(srv, [
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": "obs.ask", "arguments": {"question": "coverage_percentage"}}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "obs.generate_runbook",
                    "arguments": {"archetype": "api-availability"}}},
    ])
    ok = r[0]["result"]
    assert ok["isError"] is False
    body = json.loads(ok["content"][0]["text"])
    assert body["answer"]["question"] == "coverage_percentage"

    refused = r[1]["result"]
    assert refused["isError"] is True, "a viewer-auditor must not be able to generate"
    assert json.loads(refused["content"][0]["text"])["code"] == "forbidden"


def test_malformed_json_gets_a_parse_error_not_a_crash(srv):
    out = io.StringIO()
    srv.serve(stdin=io.StringIO("{not json}\n"), stdout=out)
    assert json.loads(out.getvalue())["error"]["code"] == -32700


def test_unknown_method_is_a_jsonrpc_method_not_found(srv):
    r = _rpc(srv, [{"jsonrpc": "2.0", "id": 9, "method": "does/not/exist"}])
    assert r[0]["error"]["code"] == -32601
