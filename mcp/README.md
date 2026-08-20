# Observability MCP server

An MCP server over stdio that answers grounded questions about this monitoring
platform and proposes changes to it — **through pull requests, never through
the Datadog API**.

```
23 tools · 30 grounded questions · 3 planes · the platform's existing 4 roles
Every answer cites object ids, counts and a source.
Every change exits as a pull request. There is no other exit.
```

It reads the **same policy engine Terraform reads**. Coverage numbers here and
`make coverage` cannot disagree, because they are the same function call.

- Requirement: [`docs/requirement-traceability.md`](../docs/requirement-traceability.md)
  §42–§46
- Runs offline by default; live Datadog reads are opt-in via `DD_API_KEY` /
  `DD_APP_KEY`.
- **Independent of Bits AI** (§42). Nothing here calls Datadog's own MCP server
  or needs it installed. Both can be configured in the same client; they answer
  different questions. What this server knows that Bits AI cannot is *why* — the
  policy hierarchy that decided a monitor exists lives in this repository.

---

## Quick start

```bash
pip install -r mcp/requirements.txt

python3 mcp/server.py --list-tools           # the published tool surface
python3 mcp/server.py --list-questions       # the Ask catalog
python3 mcp/server.py --self-test            # exercise every read/plan tool
python3 mcp/server.py --call obs.ask \
  --args '{"question":"which SLOs are burning?"}'
python3 mcp/server.py                        # speak MCP on stdin/stdout
python3 -m pytest mcp/tests -q               # or: make test-mcp
```

Client configuration (any MCP client — Claude Desktop, Claude Code, an
in-house agent):

```json
{
  "mcpServers": {
    "enterprise-observability": {
      "command": "python3",
      "args": ["/path/to/enterprise-observability/mcp/server.py"],
      "env": {
        "OBS_MCP_TOKEN": "…",
        "OBS_MCP_PRINCIPALS": "/etc/observability/principals.yaml"
      }
    }
  }
}
```

With no `OBS_MCP_TOKEN` the server starts as the **anonymous, read-only**
principal (`viewer-auditor`) and says so on stderr. That is a deliberate
default: refusing to start would only teach people to export a powerful token
they do not need.

---

## Architecture (§46)

An **intent router** in front of three planes. The planes are not decoration —
they are how the security property fits in one sentence a reviewer can check:
*only the git-yaml plane can write, only the `propose` capability reaches it,
and only two of the four roles hold that capability.* Everything else in this
server is a pure function of state.

```
┌──────────────────────────────────────────────────────────────────────────┐
│  MCP client (any)                          stdio · JSON-RPC 2.0 · NDJSON │
└───────────────────────────────┬──────────────────────────────────────────┘
                                │  initialize · tools/list · tools/call
┌───────────────────────────────▼──────────────────────────────────────────┐
│  server.py            protocol only. No SDK dependency.                  │
├──────────────────────────────────────────────────────────────────────────┤
│  obs_router.py        INTENT ROUTER — one door, six steps, every call    │
│                                                                          │
│    1 resolve    tool name, or natural language → question id             │
│                 (deterministic: curated phrasings, then token overlap)   │
│    2 validate   the tool's published JSON Schema, before any handler      │
│    3 authorize  role → capability            ┐                           │
│    4 rate limit per principal, per capability│ obs_governance.py (§45)   │
│    5 dispatch   to exactly ONE plane         │                           │
│    6 audit      one JSON line, always        ┘                           │
└───────┬──────────────────────┬────────────────────────┬──────────────────┘
        │                      │                        │
┌───────▼────────┐   ┌─────────▼──────────┐   ┌─────────▼──────────────────┐
│  READ PLANE    │   │  OPERATIONS PLANE  │   │  GIT-YAML PLANE            │
│  capability:   │   │  capability:       │   │  capability: propose       │
│    read, admin │   │    plan, generate  │   │                            │
│                │   │                    │   │  obs_gitops.py             │
│  obs_ask.py    │   │  obs_act.py        │   │   • worktree (never your   │
│   30 questions │   │   • validate       │   │     checkout)              │
│   evidence-    │   │   • resolve        │   │   • write fence re-checked │
│   cited        │   │   • preview        │   │   • branch → commit        │
│                │   │   • generate       │   │   • push → gh pr create    │
│  MUTATES       │   │   • plan (+token)  │   │                            │
│  NOTHING       │   │  MUTATES NOTHING   │   │  THE ONLY WRITE PATH       │
└───────┬────────┘   └─────────┬──────────┘   └─────────┬──────────────────┘
        │                      │                        │
        └──────────┬───────────┘                        │
                   │                                    │
┌──────────────────▼─────────────────────┐              │
│  obs_state.py — ONE read surface       │              │
│                                        │              │
│   obs_common.load_policy()   ← policy  │              │
│   profile_engine.assign()    ← band    │              │
│   obs_common.expand_instances()        │              │
│   coverage_report.run_checks()  C1–C17 │              │
│   reconciliation_report.route_for()    │              │
│   correlate_events.correlate()         │              │
│                                        │              │
│   mode=fixtures  tests/fixtures/ +     │              │
│                  runtime_state.json    │              │
│   mode=live      Datadog — GET ONLY    │              │
└──────────┬─────────────────────────────┘              │
           │                                            │
   ┌───────▼────────────────┐                 ┌─────────▼──────────────────┐
   │ platform/policy/*.yaml │                 │  pull request              │
   │ (the same files        │                 │        ↓                   │
   │  Terraform reads)      │                 │  .github/workflows/ci.yml  │
   └────────────────────────┘                 │        ↓                   │
                                              │  Terraform (deploy.yml)    │
   ┌────────────────────────┐  ── read ──▶    │        ↓                   │
   │ Datadog API            │  ◀── NEVER ──   │  Datadog                   │
   └────────────────────────┘     written     └────────────────────────────┘
```

### Layout

| File | Role |
|---|---|
| `server.py` | MCP over stdio: JSON-RPC 2.0, NDJSON. Also a CLI (`--call`, `--self-test`). No SDK dependency. |
| `obs_router.py` | The intent router: resolve → validate → authorize → rate limit → dispatch → audit. |
| `obs_tools.py` | The tool registry. Plane, capability, JSON Schema and handler, declared once each. |
| `obs_state.py` | The single read surface. Reuses `tools/` for every structural fact; `_get` is the only HTTP verb. |
| `obs_ask.py` | Ask mode (§43) — 30 questions, each returning an evidence-cited `Answer`. |
| `obs_evidence.py` | `Evidence` / `Answer`. Refuses to serialize an answerable result that cites nothing. |
| `obs_act.py` | Act mode (§44) — validate, resolve, preview, generate, plan. **The write fence lives here.** |
| `obs_gitops.py` | The git-yaml plane: worktree → branch → commit → push → `gh pr create`. |
| `obs_governance.py` | §45 — authentication, RBAC, environments, rate limits, gates, redaction, audit. |
| `principals.example.yaml` | Template for the principal registry. The real file is gitignored. |
| `tests/` | Contracts, governance refusals, Ask grounding, Act/GitOps. 155 tests, all offline. |
| `tests/fixtures/runtime_state.json` | The offline runtime snapshot, derived from the plan fixtures by `build_runtime_state.py`. |

`mcp/` is a directory of flat modules, not a Python package — the same shape as
`tools/`. That is deliberate twice over: the modules import each other by bare
name like the rest of the repository's tooling, and a top-level package
literally named `mcp` would shadow the `mcp` PyPI SDK for anything else sharing
the interpreter.

---

## Tool surface

### Read plane — `read`

| Tool | |
|---|---|
| `obs.ask` | Ask a grounded question in natural language or by id; returns an evidence-cited answer or an explicit reason it cannot be answered. |
| `obs.list_questions` | Every answerable question, its parameters, and whether it is `state` / `runtime` / `partial` / `blocked`. |
| `obs.describe_platform` | The policy hierarchy and the estate it produces, in numbers. |
| `obs.get_entity` | One service, resource or monitor: owner, tier, profile, band, SLOs, monitors. |
| `obs.list_entities` | Registered services and discovered resources, filtered by env / team / tier / ownership. |
| `obs.list_monitors` | The managed estate filtered by env, band, team, priority, archetype, domain or paging. |
| `obs.get_monitor` | One monitor's full governance record: query, tags, route, runbook attachment, workflow, SLO, state. |
| `obs.list_slos` | The SLO catalog with targets, scope, burn windows and runtime status where it exists. |
| `obs.explain_inheritance` | Why a service inherits a monitor, or receives an SLO — the resolution chain, layer by layer. |
| `obs.coverage_report` | The seventeen governance checks (C1–C17), summary and findings. |
| `obs.reconciliation_report` | One row per managed monitor joining plan, runbook registry and routing policy. |
| `obs.oncall` | A team's schedules, escalation chain, channels and assignment group. |
| `obs.incidents` | Active and recent incidents, with MTTR over the resolved ones. |
| `obs.validate_yaml` | Validate a service or monitor manifest against the schema and the policy references. |
| `obs.audit_log` | *(`admin`)* This server's own audit log: every call, principal, decision and outcome. |

### Operations plane — `plan` / `generate`

| Tool | |
|---|---|
| `obs.preview_onboarding` | *(plan)* Dry-run onboarding: profile and band per env, monitors joined, SLO received, telemetry required, new objects created. |
| `obs.resolve_profile` | *(plan)* The applicable monitoring profile and alert band, via the platform's own resolver. |
| `obs.resolve_slo` | *(plan)* Which objective an entity receives — per-service or domain — with burn windows and budget policy. |
| `obs.missing_telemetry` | *(plan)* What an entity must emit for its monitors to be able to fire, and what is not observed. |
| `obs.plan` | *(plan)* Validate a change set, compute the estate delta against the monitor budget, run the policy lint, return a `plan_token`. |
| `obs.generate_yaml` | *(generate)* Produce a service registration, self-service monitor manifest, or SLO catalog entry. Writes nothing. |
| `obs.generate_runbook` | *(generate)* Produce a runbook using the platform's own generator — byte-identical to `make runbooks`. |

### Git-yaml plane — `propose`

| Tool | |
|---|---|
| `obs.propose_change` | Open a controlled pull request for a planned change set. Dry run by default. Requires a matching `plan_token`, an allowed environment, and a named second approver for production. |

There is **no apply tool**, and that is the design. Applies belong to
`deploy.yml`, behind the `datadog-production` approval environment. An agent
that can apply has quietly removed code review for everybody.

---

## Ask mode (§43) — what it can and cannot answer

Thirty questions. `obs.list_questions` returns the live catalog with an
`availability` marker:

| | Count | Meaning |
|---|---|---|
| `state` | 14 | Answerable from the repository alone — policy plus the plan-derived estate. |
| `runtime` | 5 | Needs the runtime snapshot (offline) or the Datadog API (live). |
| `partial` | 10 | Answerable, but a named part is not. Every caveat is returned with the answer. |
| `blocked` | 1 | Cannot be answered in this org today. The answer says why, and names the gap. |

Every answer carries `evidence[]` — a source locator, the object kind, the ids
(sampled, with the true count kept) and a note. `mcp/obs_evidence.py` **refuses
to serialize an answerable result with no citation**, and
`tests/test_ask_grounding.py` walks the whole catalog to prove the refusal
never has to fire.

### What it cannot answer, and why

These are real findings from the traceability audit, not placeholders. Each is
returned as a refusal or a disclosed caveat — never as a guess.

| Question | Status | Reason |
|---|---|---|
| **who is on call** | **blocked** | §28 — every on-call schedule position in this org is **unassigned**. The schedules, the four-step escalation policy and the routing all exist and are returned; no person can be named because no person is in them. Fabricating one would be the most dangerous answer this server could give. Fix: populate `oncall_members` from the IdP/SCIM sync. |
| **what changed** | partial | §8 — no pipeline sets `DD_VERSION` / `DD_GIT_COMMIT_SHA`, so deployment metadata largely does not reach Datadog. Change correlation works; its input is thin. An empty result means *not visible*, not *nothing changed*, and the answer says so. |
| **missing integrations** | partial | §38 — monitor archetypes declare no `telemetry:` requirement, so "required integration" is **inferred** from the metric namespace each query reads. Disclosed on every answer as a lead, not an inventory. The observed side comes from host `apps`, so account-level integrations may be present and invisible. |
| **broken agents** | partial | §36/§39 — agent health and version drift are observable; **fleet compliance percentage is not**, because nothing declares which hosts are *required* to run an agent. A host with no agent is invisible by construction. |
| **which SLO will breach first** | partial | Linear extrapolation of the instantaneous burn rate over the 30-day window. A triage ordering, not a forecast — Datadog's SLO history is the authority on trajectory. |
| **probable root cause** | partial | The correlation parent is chosen by signal rank, then priority, then time (`platform/events/correlation-rules.yaml`). A prioritized hypothesis, not a causal proof. |
| **MTTR** | partial | Datadog incident records only. A P3 raises a ServiceNow *task* and no Datadog incident, so lower-severity restore times live in ServiceNow and are not counted. |
| **noisy monitors** | partial | **No policy defines a noise threshold.** `platform/policy/` budgets the monitor *count* and the *paging* rule but says nothing about firing *rate*. The default is a server default, disclosed on every answer and overridable per call. If noise is to be governed it belongs in policy. |
| **monitors that never triggered** | partial | Bounded by the activity window, and — the dangerous case — a monitor that *cannot* fire looks identical to one that has not needed to. See §8: nothing emits the `alert_band` tag onto telemetry, so many correct queries currently select an empty set. |
| **top reliability risks** | partial | The findings are policy; the **severity weighting that ranks them is not**. Stated on every answer. |

One more constraint worth stating plainly, because it colours several answers:
**§8 — nothing emits `alert_band` onto telemetry today.** Every SLI and most
archetype queries filter on it. The objectives and monitors in this repository
are correctly defined and currently select an empty set. `telemetry_feeding_slo`
discloses it on every answer rather than reporting a healthy SLO.

---

## Act mode (§44) — how change stays inside GitOps

```
obs.generate_yaml / obs.generate_runbook     produce text
        ↓
obs.validate_yaml                            the CI validator, on that text
        ↓
obs.plan                                     delta + budget + policy lint → plan_token
        ↓
obs.propose_change (dry_run=true, default)   branch name, diff, PR body — writes nothing
        ↓
obs.propose_change (dry_run=false)           worktree → branch → commit → push → PR
        ↓
.github/workflows/ci.yml                     the full gate, unchanged
        ↓
deploy.yml                                   qa → stage automatic; production dispatched
        ↓                                    behind the datadog-production approval env
Datadog
```

**Five things make the shortcut impossible:**

1. **No Datadog write client exists.** `obs_state._get` is the only HTTP verb in
   the server, and `obs_act.py` has no Datadog client at all — asserted by a
   test that greps its own source for `POST`/`PUT`/`DELETE`.
2. **The write fence.** Act mode may only ever propose changes to
   `platform/services/*.yaml`, `platform/monitors/*.yaml`,
   `platform/runbooks/*.md`, and an *anchored insert* into
   `platform/policy/slos.yaml`. `platform/policy/archetypes/`, `stacks/`,
   `modules/`, `.github/`, `tests/`, `tools/`, `docs/`, `README.md` and `mcp/`
   itself are refused with a reason. Deny is evaluated before allow, and the
   fence is re-checked at write time as well as generation time.
3. **Plan before propose.** `obs.propose_change` requires a `plan_token` — the
   content hash of the exact files `obs.plan` evaluated. Editing a single byte
   changes the digest and the proposal is refused. You cannot propose what
   nobody planned, and you cannot plan one thing and propose another.
4. **Dry run is the default.** Omitting `dry_run` means *dry run*. A dry run
   creates no branch, no worktree, no commit and no remote reference — asserted
   by a test that snapshots the whole repository around the call.
5. **It never touches your checkout.** All git work happens in a dedicated
   `git worktree` under `generated/`, removed in a `finally`.

The SLO case is why the fence has two shapes. Adding an objective is a change to
a catalog every team shares, so it is an *anchored insert* into one named
section rather than a whole-file write: an agent cannot rewrite the other 22
objectives while adding one, and the file's comments — which are its design
rationale — survive, because the insert is textual rather than a PyYAML
round-trip.

---

## Governance (§45)

### The four roles — the platform's own, not a new set

Mirrored from `stacks/foundation/main.tf` → `module "rbac"`. That module
explains at length why the platform has four verbs and derives *scope* from
`team:` ownership tags rather than multiplying roles by team × environment.
This server inherits the decision: the **role** says which verbs you hold,
`environments` says **where**, and ownership stays in the tags.

| Role | `read` | `plan` | `generate` | `propose` | `admin` |
|---|:--:|:--:|:--:|:--:|:--:|
| `viewer-auditor` | ✓ | | | | |
| `incident-responder` | ✓ | ✓ | | | |
| `observability-engineer` | ✓ | ✓ | ✓ | ✓ | |
| `platform-admin` | ✓ | ✓ | ✓ | ✓ | ✓ |

The MCP grant is always a **subset** of what the same role already holds in
Datadog. `incident-responder` gets `plan` — dry-running "what would this change
do" mid-incident is exactly its job — but no `generate` or `propose`, because
the Datadog role's own boundary is *cannot author new detection*. And
`observability-engineer` holding `propose` never means write access to Datadog:
here it is only ever the right to open a pull request.

### Authentication

`OBS_MCP_TOKEN` is compared **by SHA-256 digest, in constant time** against
`principals.yaml` (template: `principals.example.yaml`; the real file is
gitignored). stdio has no per-request auth header — the transport *is* the trust
boundary — so the token is presented once at startup. What it buys is not
secrecy but **attribution**: the audit log names a principal instead of
"somebody's laptop". No token → anonymous `viewer-auditor`, read-only.

### The other five mechanisms

| | |
|---|---|
| **Read/write separation** | Enforced by plane, asserted by a contract test: exactly one tool sets `mutates=True`, and it is on the git-yaml plane. |
| **Environment restrictions** | A principal carries the environments it may propose changes for. `prod` is never granted by default. Target environments are read from the change itself (`service.envs` / `monitor.env`; an SLO is production by construction). |
| **Dry run / plan-before-apply** | Above. Both defaults fail closed. |
| **Approval gates** | Anything reaching production needs a *different*, registered `approver: true` principal and a change-record reference. Self-approval is refused explicitly — it is the failure mode the gate exists for. The approver and ticket go into the commit message, the PR body and the audit line. |
| **Rate limiting** | Fixed windows per principal per capability: 240 read/min, 30 plan/min, 30 generate/min, **10 propose/hour**. A read storm and a PR storm are not the same risk and do not share a bucket. |
| **Schema & input validation** | The published `inputSchema` is enforced before the handler exists. `additionalProperties: false` throughout. |
| **Secrets never logged** | Two-pass redaction — key names (`*token*`, `*key*`, `*secret*`, `authorization`, …) and value *shapes* (Datadog keys, 32/40-hex, `ghp_*`, `Bearer …`) — applied to every argument before it is audited **and** to every error string before it leaves the process, because a traceback can carry an argument. |
| **Clear errors** | Every refusal carries a machine-readable `code` and a `remedy` naming the next step: which roles hold the capability, how to widen an environment, how to re-plan. |

### Audit log

One JSON line per call, appended to `generated/mcp/audit.jsonl`
(`OBS_MCP_AUDIT_LOG` to relocate) — written in a `finally`, so a handler that
raises still leaves a record. Each line carries call id, timestamp, principal,
role, whether they authenticated, tool, plane, capability, mode, **redacted**
arguments, the routing decision for a natural-language call, the decision
(`allow` / `deny` / `error`) with its code, the duration, and a **shape summary
of the result — never the payload**. A log that copies its payload stops being
readable and starts retaining data it was never meant to hold.

Refused calls are the ones worth having: *who tried to open a production PR
without an approver* is the question an audit actually asks.

---

## Modes and configuration

| Variable | Default | |
|---|---|---|
| `OBS_MCP_TOKEN` | — | Bearer token. Absent → anonymous read-only. |
| `OBS_MCP_PRINCIPALS` | `mcp/principals.yaml` | Principal registry (digests only). |
| `OBS_MCP_AUDIT_LOG` | `generated/mcp/audit.jsonl` | Audit destination. |
| `OBS_MCP_MODE` | `fixtures` | `fixtures` or `live`. |
| `OBS_MCP_LIVE` | — | `1` **plus** `DD_API_KEY`/`DD_APP_KEY` selects live mode by default. |
| `OBS_MCP_ESTATE_SIZE` | `2000` | Synthetic estate size in fixtures mode. |
| `OBS_MCP_TERRAFORM` | — | `1` allows `obs.plan(terraform=true)` to shell out to an **offline** plan. |
| `DD_API_KEY` / `DD_APP_KEY` | — | Live reads. Use the read-only `svc-observability-coverage` service account, never personal keys. |
| `DD_SITE` | `https://api.datadoghq.com` | |

Live mode is **read-only by construction**, not by convention: `obs_state._get`
hard-codes the verb, and `obs.plan(terraform=true)` forces `DD_API_KEY=offline`
and `-var datadog_validate=false` even when real credentials are exported — so
a local plan cannot reach the org whatever the environment says.

---

## Tests

```bash
python3 -m pytest mcp/tests -q      # 155 tests, fully offline
make test-mcp
```

| File | Asserts |
|---|---|
| `test_tool_contracts.py` | Every tool declares a plane, a capability and a valid schema; the schema is enforced; only the git plane mutates; the MCP handshake, `tools/list`, `tools/call`, `isError`, parse errors and unknown methods. |
| `test_governance.py` | An unauthorized write is refused (every write tool, for a read-only principal); wrong tokens are refused rather than downgraded; plan-before-propose, including tampered and expired tokens; environment denial; production approval including self-approval; the write fence; per-capability rate limits; secret redaction; and that the audit log records **every** call — allowed, refused, and one whose handler raised. |
| `test_ask_grounding.py` | Every question either answers **with evidence** or refuses **with a reason**; every cited source resolves to a real file, route or fixture; the coverage answer equals the platform's own report; the inheritance explanation matches `expand_instances`; the routing table; and that an unknown subject is a refusal, not an invention. |
| `test_act_gitops.py` | Validation accepts the repository's own manifests and rejects the mistakes CI rejects; resolution matches the profile engine (including the qa/dev clamp and the compliance overlay); a **dry run changes nothing** (the repository is snapshotted around the call); the real path commits to a branch and leaves the base untouched; the SLO insert is anchored and preserves the catalog; terraform planning is opt-in and forced offline; and `obs_act.py` contains no write verb. |

The offline runtime snapshot (`tests/fixtures/runtime_state.json`) is
*derived from* `tests/fixtures/monitors_planned.json` — every monitor id,
correlation key, service and priority in it is copied from a real planned
monitor — so an answer grounded in it is grounded in the real estate's shape.
Regenerate deterministically with:

```bash
cd mcp/tests/fixtures && python3 build_runtime_state.py
```

It never touches `tests/fixtures/monitors_planned.json`, which is the Terraform
plan's own output and is regenerated only by `make fixtures`.

---

## What this does not do

- **No apply.** By design. See Act mode above.
- **No writes outside the fence.** Adding a monitor *pattern* for everyone
  (`platform/policy/archetypes/`) is a human-authored pull request, because it
  changes monitoring for every team at once.
- **No entity kinds beyond Service.** §5 is still `PARTIAL`: the catalog has no
  System / Datastore / Queue / API kinds yet, so `obs.get_entity` resolves
  services, discovered resources and monitors — not a full entity graph.
- **No fleet compliance, no Control-M, no executive portal.** Phases 3, 5 and 8
  of the traceability sequence. Where a question touches them, Ask says so.
