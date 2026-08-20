"""TOOL REGISTRY — the server's contract, declared once.

Every tool declares four things and nothing else:

  plane        read | operations | git-yaml   (§46 — see mcp/README.md)
  capability   read | plan | generate | propose | admin  (§45 — RBAC)
  inputSchema  JSON Schema, returned verbatim by MCP `tools/list` AND enforced
               before the handler runs. One declaration, not two.
  handler      (ctx, args) -> dict

Keeping the schema, the RBAC grant and the plane in ONE place is what makes
`mcp/tests/test_tool_contracts.py` able to assert the whole surface: no tool
can exist without a capability, no capability can be unknown, and no write tool
can sit on the read plane.
"""
from __future__ import annotations

import dataclasses
from typing import Callable

import obs_ask
import obs_act
import obs_gitops
import obs_governance as gov

PLANES = ("read", "operations", "git-yaml")

# Which plane a capability may act on. A write capability on the read plane is
# a contradiction the contract test rejects.
PLANE_CAPABILITIES = {
    "read": {"read", "admin"},
    "operations": {"plan", "generate"},
    "git-yaml": {"propose"},
}


@dataclasses.dataclass
class Tool:
    name: str
    plane: str
    capability: str
    description: str
    input_schema: dict
    handler: Callable
    mutates: bool = False
    idempotent: bool = True

    def to_mcp(self) -> dict:
        return {"name": self.name, "description": self.description,
                "inputSchema": self.input_schema}


TOOLS: dict[str, Tool] = {}


def tool(name, plane, capability, description, schema, mutates=False):
    def deco(fn):
        TOOLS[name] = Tool(name, plane, capability, description, schema, fn, mutates)
        return fn
    return deco


def _obj(props: dict, required=(), extra=False) -> dict:
    return {"type": "object", "properties": props, "required": list(required),
            "additionalProperties": bool(extra)}


STR = {"type": "string"}
BOOL = {"type": "boolean"}
INT = {"type": "integer"}


# ===========================================================================
# READ PLANE
# ===========================================================================
@tool("obs.ask", "read", "read",
      "Ask a grounded question about the platform in natural language or by question id. "
      "Returns an evidence-cited answer, or an explicit reason the data does not exist.",
      _obj({"question": {**STR, "minLength": 2,
                         "description": "natural language, or a question id from "
                                        "obs.list_questions"},
            "params": {"type": "object", "additionalProperties": True,
                       "description": "question-specific parameters"}},
           required=["question"]))
def t_ask(ctx, args):
    from obs_router import resolve_intent
    q = args["question"]
    if q in obs_ask.QUESTIONS:
        qid, routing = q, {"match": "exact_id", "confidence": 1.0}
    else:
        qid, routing = resolve_intent(q)
        if qid is None:
            return {"routed": False, "routing": routing,
                    "error": "no question in the catalog matches that phrasing",
                    "remedy": "call obs.list_questions, or pass a question id directly"}
    answer = obs_ask.answer(ctx.state, qid, args.get("params") or {})
    return {"routed": True, "routing": routing, "answer": answer}


@tool("obs.list_questions", "read", "read",
      "List every question Ask mode can answer, with its parameters and whether it is "
      "answerable from platform state, needs runtime data, is partial, or is blocked.",
      _obj({"availability": {**STR, "enum": list(obs_ask.AVAILABILITY)}}))
def t_list_questions(ctx, args):
    rows = obs_ask.catalog()
    if args.get("availability"):
        rows = [r for r in rows if r["availability"] == args["availability"]]
    return {"questions": rows, "count": len(rows),
            "availability_vocabulary": {
                "state": "answerable from the repository alone",
                "runtime": "needs the runtime snapshot (offline) or the Datadog API (live)",
                "partial": "answerable, but a named part of it is not — see caveats",
                "blocked": "cannot be answered in this org today; the answer says why"}}


@tool("obs.describe_platform", "read", "read",
      "Summarize the policy hierarchy and the estate it produces: archetypes, monitors, "
      "SLOs, teams, environments, tiers, runbooks, coverage.",
      _obj({"refresh": {**BOOL, "description": "drop the cached state and reload"}}))
def t_describe(ctx, args):
    if args.get("refresh"):
        import obs_state
        obs_state.reset_state()
        ctx.reload()
    return obs_ask.answer(ctx.state, "estate_summary", {})


@tool("obs.get_entity", "read", "read",
      "One entity — a registered service, a discovered resource, or a monitor — with its "
      "resolved owner, tier, monitoring profile, alert band, SLOs and monitors.",
      _obj({"entity": STR}, required=["entity"]))
def t_get_entity(ctx, args):
    ent = args["entity"]
    state = ctx.state
    owner = obs_ask.answer(state, "owner_of", {"entity": ent})
    out = {"entity": ent, "ownership": owner}
    svc = state.services.get(ent)
    if svc:
        out["registration"] = svc
        out["onboarding"] = obs_act.preview_onboarding(state, svc)
        out["slo"] = obs_ask.answer(state, "why_service_received_slo", {"service": ent})
    monitors = [{"id": m["id"], "name": m.get("name"),
                 "priority": (state.monitor_tags(m).get("priority") or "").upper(),
                 "env": state.monitor_tags(m).get("env"),
                 "archetype": state.monitor_tags(m).get("archetype")}
                for m in state.managed_monitors
                if state.monitor_tags(m).get("service") == ent]
    out["monitors_scoped_to_this_service_tag"] = monitors
    return out


@tool("obs.list_entities", "read", "read",
      "List registered services and, optionally, discovered resources with their resolved "
      "profile, band and owner.",
      _obj({"kind": {**STR, "enum": ["service", "resource", "all"]},
            "env": STR, "team": STR, "tier": STR, "unowned_only": BOOL,
            "limit": {**INT, "minimum": 1, "maximum": 500}}))
def t_list_entities(ctx, args):
    state = ctx.state
    kind = args.get("kind", "service")
    limit = int(args.get("limit") or 100)
    out = {"registered_services": [], "discovered_resources": [], "truncated": False}
    if kind in ("service", "all"):
        for name, svc in sorted(state.services.items()):
            if args.get("team") and svc["team"] != args["team"]:
                continue
            if args.get("tier") and svc["tier"] != args["tier"]:
                continue
            if args.get("env") and args["env"] not in svc["envs"]:
                continue
            out["registered_services"].append(svc)
    if kind in ("resource", "all"):
        rows = state.assignments["assignments"]
        for a in rows:
            if args.get("env") and a["env"] != args["env"]:
                continue
            if args.get("team") and a["team"] != args["team"]:
                continue
            if args.get("tier") and a["tier"] != args["tier"]:
                continue
            if args.get("unowned_only") and a["owner_source"] != "unowned_pool":
                continue
            out["discovered_resources"].append(a)
        out["discovered_total"] = len(out["discovered_resources"])
        if len(out["discovered_resources"]) > limit:
            out["discovered_resources"] = out["discovered_resources"][:limit]
            out["truncated"] = True
        out["source"] = state.estate_source
    return out


@tool("obs.list_monitors", "read", "read",
      "Filter the managed monitor estate by environment, band, team, priority, archetype "
      "or paging behaviour.",
      _obj({"env": STR, "band": STR, "team": STR, "priority": STR, "archetype": STR,
            "domain": STR, "pages_only": BOOL,
            "limit": {**INT, "minimum": 1, "maximum": 500}}))
def t_list_monitors(ctx, args):
    state = ctx.state
    limit = int(args.get("limit") or 100)
    rows = []
    for m in state.managed_monitors:
        t = state.monitor_tags(m)
        if args.get("env") and t.get("env") != args["env"]:
            continue
        if args.get("band") and t.get("alert_band") != args["band"]:
            continue
        if args.get("team") and t.get("team") != args["team"]:
            continue
        if args.get("domain") and t.get("domain") != args["domain"]:
            continue
        if args.get("archetype") and t.get("archetype") != args["archetype"]:
            continue
        if args.get("priority") and (t.get("priority") or "").upper() != args["priority"].upper():
            continue
        if args.get("pages_only") and t.get("pages") != "true":
            continue
        rows.append({"id": m["id"], "name": m.get("name"), "type": m.get("type"),
                     "priority": (t.get("priority") or "").upper(), "env": t.get("env"),
                     "band": t.get("alert_band"), "team": t.get("team"),
                     "archetype": t.get("archetype"), "domain": t.get("domain"),
                     "pages": t.get("pages") == "true", "slo_id": t.get("slo_id"),
                     "runbook": t.get("runbook")})
    return {"count": len(rows), "monitors": rows[:limit],
            "truncated": len(rows) > limit, "source": state.monitor_source}


@tool("obs.get_monitor", "read", "read",
      "One monitor with its full governance record: query, tags, route, escalation policy, "
      "runbook attachment, workflow, SLO and current state.",
      _obj({"monitor_id": STR}, required=["monitor_id"]))
def t_get_monitor(ctx, args):
    state = ctx.state
    mid = str(args["monitor_id"])
    m = state.monitors_by_id.get(mid)
    if not m:
        return {"error": f"no monitor with id {mid!r} in the current estate",
                "source": state.monitor_source}
    t = state.monitor_tags(m)
    arch = state.policy["archetypes"].get(t.get("archetype", ""), {})
    runtime = (state.runtime.get("monitor_states") or {}).get(mid, {})
    activity = (state.runtime.get("monitor_activity") or {}).get(mid, {})
    return {
        "id": m["id"], "name": m.get("name"), "type": m.get("type"),
        "query": m.get("query"), "options": m.get("options"),
        "tags": t,
        "archetype": {"id": t.get("archetype"), "title": arch.get("title"),
                      "signal": arch.get("signal"), "detection": arch.get("detection"),
                      "impact_class": arch.get("impact_class"),
                      "rationale_fixed_threshold":
                          (arch.get("rationale_fixed_threshold") or "").strip() or None},
        "routing": obs_ask.answer(state, "route_for", {"monitor_id": mid}),
        "state": runtime, "activity": activity,
        "reconciliation": next((r for r in state.reconciliation if str(r["id"]) == mid), None),
        "source": state.monitor_source,
    }


@tool("obs.list_slos", "read", "read",
      "The SLO catalog with targets, scope, burn windows and runtime status where it exists.",
      _obj({"domain": STR, "team": STR, "burning_only": BOOL}))
def t_list_slos(ctx, args):
    state = ctx.state
    rows = obs_ask._slo_rows(state)
    catalog = state.policy["slos"]
    out = []
    for r in rows:
        spec = catalog.get(r["slo_id"]) or {}
        if args.get("domain") and spec.get("domain") != args["domain"]:
            continue
        if args.get("team") and spec.get("team") != args["team"]:
            continue
        budget = r["budget_pct"]
        if args.get("burning_only") and (budget is None or budget >= 25):
            continue
        out.append({**r, "definition": spec})
    return {"count": len(out), "slos": out, "source": state.slo_source}


@tool("obs.explain_inheritance", "read", "read",
      "Why a service inherits a monitor, or receives an SLO — the full resolution chain "
      "through the policy hierarchy, with the layer and file that decided each step.",
      _obj({"service": STR, "archetype": STR,
            "what": {**STR, "enum": ["monitor", "slo"]}},
           required=["service", "what"]))
def t_explain(ctx, args):
    if args["what"] == "slo":
        return obs_ask.answer(ctx.state, "why_service_received_slo",
                              {"service": args["service"]})
    if not args.get("archetype"):
        return {"error": "what=monitor needs an archetype id"}
    return obs_ask.answer(ctx.state, "why_service_inherited_monitor",
                          {"service": args["service"], "archetype": args["archetype"]})


@tool("obs.coverage_report", "read", "read",
      "Run the seventeen governance checks (C1-C17) and return the summary plus findings — "
      "the same report the nightly governance loop gates on.",
      _obj({"check": {**STR, "description": "e.g. C1; omit for all"},
            "include_findings": BOOL}))
def t_coverage(ctx, args):
    report = ctx.state.coverage
    out = {"summary": report["summary"], "titles": {}}
    import coverage_report as cr
    out["titles"] = cr.CHECK_TITLES
    if args.get("include_findings", True):
        checks = report["checks"]
        if args.get("check"):
            cid = args["check"].upper()
            out["findings"] = {cid: checks.get(cid, [])}
        else:
            out["findings"] = {k: v[:25] for k, v in checks.items() if v}
    out["accepted_findings"] = report.get("accepted_findings", [])
    out["source"] = {"monitors": ctx.state.monitor_source,
                     "estate": ctx.state.estate_source}
    return out


@tool("obs.reconciliation_report", "read", "read",
      "One row per managed monitor joining plan, runbook registry and routing policy — "
      "owner, route, escalation policy, notebook attachment, auto-resolve, SLO, workflow.",
      _obj({"status": {**STR, "enum": ["PASS", "FAIL", "all"]},
            "limit": {**INT, "minimum": 1, "maximum": 500}}))
def t_reconciliation(ctx, args):
    rows = ctx.state.reconciliation
    want = args.get("status", "all")
    if want == "PASS":
        rows = [r for r in rows if r["status"] == "PASS"]
    elif want == "FAIL":
        rows = [r for r in rows if r["status"] != "PASS"]
    limit = int(args.get("limit") or 100)
    return {"count": len(rows), "rows": rows[:limit], "truncated": len(rows) > limit,
            "pass": sum(1 for r in ctx.state.reconciliation if r["status"] == "PASS"),
            "total": len(ctx.state.reconciliation),
            "source": ctx.state.monitor_source}


@tool("obs.oncall", "read", "read",
      "On-call structure for a team: schedules, escalation chain, channels and assignment "
      "group. Reports honestly that rosters are unassigned in this org.",
      _obj({"team": STR}))
def t_oncall(ctx, args):
    return obs_ask.answer(ctx.state, "who_is_on_call",
                          {"team": args.get("team")} if args.get("team") else {})


@tool("obs.incidents", "read", "read",
      "Active and recent incidents, with MTTR over the resolved ones.",
      _obj({"include_mttr": BOOL}))
def t_incidents(ctx, args):
    out = {"incidents": obs_ask.answer(ctx.state, "active_incidents", {})}
    if args.get("include_mttr", True):
        out["mttr"] = obs_ask.answer(ctx.state, "mttr", {})
    return out


@tool("obs.validate_yaml", "read", "read",
      "Validate a service registration or self-service monitor manifest against the JSON "
      "schema and the policy references — the same validation the CI gate runs.",
      _obj({"yaml": {**STR, "minLength": 2},
            "kind": {**STR, "enum": ["service", "monitor"]}},
           required=["yaml"]))
def t_validate(ctx, args):
    result = obs_act.validate_manifest(ctx.state, args["yaml"], args.get("kind"))
    result.pop("doc", None)
    result["validator"] = ("tools/validate_monitors.py" if result["kind"] == "monitor"
                           else "platform/schemas/service.schema.json + policy references")
    return result


@tool("obs.audit_log", "read", "admin",
      "Read this server's own audit log: every call, its principal, its decision and its "
      "outcome.",
      _obj({"limit": {**INT, "minimum": 1, "maximum": 500}, "tool": STR, "principal": STR}))
def t_audit(ctx, args):
    rows = ctx.audit.tail(limit=int(args.get("limit") or 50),
                          tool=args.get("tool"), principal=args.get("principal"))
    return {"path": str(ctx.audit.path), "count": len(rows), "records": rows}


# ===========================================================================
# OPERATIONS PLANE — computes, returns artifacts, persists nothing
# ===========================================================================
@tool("obs.preview_onboarding", "operations", "plan",
      "Dry-run onboarding a service: resolved profile and alert band per environment, which "
      "existing monitors it joins, which SLO it receives, what telemetry it must emit, and "
      "how many new Datadog objects it creates.",
      _obj({"service": _obj({"name": STR, "team": STR,
                             "tier": {**STR, "enum": ["tier0", "tier1", "tier2", "tier3"]},
                             "service_archetype": STR, "description": STR,
                             "envs": {"type": "array", "items": STR},
                             "compliance_scope": STR,
                             "dependencies": {"type": "array", "items": STR}},
                            required=["name", "team", "tier", "service_archetype",
                                      "description", "envs"], extra=True)},
           required=["service"]))
def t_preview_onboarding(ctx, args):
    return obs_act.preview_onboarding(ctx.state, args["service"])


@tool("obs.resolve_profile", "operations", "plan",
      "Resolve the applicable monitoring profile and alert band for an entity, through the "
      "same resolver the profile engine applies to the real estate.",
      _obj({"service_archetype": STR,
            "tier": {**STR, "enum": ["tier0", "tier1", "tier2", "tier3"]},
            "env": {**STR, "enum": ["dev", "qa", "stage", "prod"]},
            "compliance_scope": STR},
           required=["service_archetype", "tier", "env"]))
def t_resolve_profile(ctx, args):
    return obs_act.resolve_monitoring_profile(
        ctx.state, service_archetype=args["service_archetype"], tier=args["tier"],
        env=args["env"], compliance_scope=args.get("compliance_scope"))


@tool("obs.resolve_slo", "operations", "plan",
      "Resolve which SLO an entity receives — per-service or domain — with the objectives, "
      "burn windows and error-budget policy that come with it.",
      _obj({"service": STR,
            "tier": {**STR, "enum": ["tier0", "tier1", "tier2", "tier3"]},
            "service_archetype": STR},
           required=["tier", "service_archetype"]))
def t_resolve_slo(ctx, args):
    return obs_act.resolve_slo_profile(ctx.state, service=args.get("service"),
                                       tier=args["tier"],
                                       service_archetype=args["service_archetype"])


@tool("obs.missing_telemetry", "operations", "plan",
      "What an entity must emit for its monitors to be able to fire, and which of it is "
      "not observed. Discloses that per-monitor requirements are derived, not declared.",
      _obj({"service_archetype": STR,
            "observed": {"type": "array", "items": STR}},
           required=["service_archetype"]))
def t_missing_telemetry(ctx, args):
    return obs_act.missing_telemetry(ctx.state, service_archetype=args["service_archetype"],
                                     observed=args.get("observed"))


@tool("obs.plan", "operations", "plan",
      "Plan a change set: validate every file, compute the estate delta against the monitor "
      "budget, run the policy lint, and return a plan_token that obs.propose_change requires.",
      _obj({"files": {"type": "object", "additionalProperties": {"type": "string"},
                      "description": "repo-relative path -> file content"},
            "terraform": {**BOOL, "description": "also run an OFFLINE terraform plan "
                                                 "(needs OBS_MCP_TERRAFORM=1)"}},
           required=["files"]))
def t_plan(ctx, args):
    files = args["files"]
    plan = obs_act.policy_plan(ctx.state, files)
    if args.get("terraform"):
        plan["terraform"] = obs_act.terraform_plan(ctx.state)
    plan["plan_token"] = ctx.ledger.record(files, ctx.principal.id,
                                           {"files": sorted(files),
                                            "errors": len(plan["errors"])})
    plan["next_step"] = ("pass this plan_token to obs.propose_change with the identical "
                         "files to open a pull request")
    return plan


@tool("obs.generate_yaml", "operations", "generate",
      "Generate a service registration, self-service monitor manifest, or SLO catalog entry "
      "from an intent. Returns the file path and content; writes nothing.",
      _obj({"kind": {**STR, "enum": ["service", "monitor", "slo"]},
            "spec": {"type": "object", "additionalProperties": True}},
           required=["kind", "spec"]))
def t_generate(ctx, args):
    out = obs_act.generate(ctx.state, args["kind"], args["spec"])
    # Generation is not validation. Run the real validator over what was just
    # produced so a caller never proposes a generated file that CI will reject.
    if out["kind"] in ("service", "monitor"):
        out["validation"] = obs_act.validate_manifest(ctx.state, out["content"], out["kind"])
        out["validation"].pop("doc", None)
    return out


@tool("obs.generate_runbook", "operations", "generate",
      "Generate the runbook for an archetype using the platform's own generator, so the "
      "output is byte-identical to `make runbooks`.",
      _obj({"archetype": STR}, required=["archetype"]))
def t_generate_runbook(ctx, args):
    return obs_act.generate_runbook(ctx.state, args["archetype"])


# ===========================================================================
# GIT-YAML PLANE — the only write path
# ===========================================================================
@tool("obs.propose_change", "git-yaml", "propose",
      "Open a controlled pull request for a planned change set. Dry run by default. "
      "Requires a matching plan_token, an allowed environment, and — for production — a "
      "named second approver. Never writes to Datadog.",
      _obj({"files": {"type": "object", "additionalProperties": {"type": "string"}},
            "plan_token": STR,
            "subject": {**STR, "minLength": 5, "maxLength": 100},
            "rationale": {**STR, "minLength": 20},
            "dry_run": {**BOOL, "description": "default true"},
            "push": {**BOOL, "description": "push the branch and open the PR"},
            "base": STR,
            "approval": _obj({"approver": STR, "ticket": STR}, extra=True)},
           required=["files", "plan_token", "subject", "rationale"]),
      mutates=True)
def t_propose(ctx, args):
    files = args["files"]
    # 1. plan-before-apply — refuses content nobody planned, and content that
    #    drifted by a single byte from what WAS planned.
    planned = ctx.ledger.verify(args["plan_token"], files)
    # 2. environment restriction
    envs = obs_act.target_environments(files)
    gov.authorize_environments(ctx.principal, envs)
    # 3. approval gate for production
    approval = gov.require_approval(ctx.principal, envs, args.get("approval"))
    # 4. dry run by default
    dry_run = args.get("dry_run", True)
    result = obs_gitops.propose(
        files=files, subject=args["subject"], body=args["rationale"],
        principal_id=ctx.principal.id, apply=not dry_run,
        push=bool(args.get("push")) and not dry_run, base=args.get("base"),
        repo_root=ctx.config.get("repo_root"), approval=approval)
    result["gates"] = {"plan_token": args["plan_token"],
                       "planned_by": planned["principal"],
                       "environments": sorted(envs), "approval": approval,
                       "write_fence": list(obs_act.ALLOWED_WRITE_PATTERNS)}
    result["datadog_writes"] = 0
    result["change_path"] = ("MCP -> YAML -> branch -> pull request -> ci.yml -> "
                             "Terraform -> Datadog")
    return result


def mcp_tool_list() -> list[dict]:
    return [TOOLS[n].to_mcp() for n in sorted(TOOLS)]
