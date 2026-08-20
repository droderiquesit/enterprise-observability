# Requirement traceability matrix

Audit of this repository and the deployed Datadog org against the 60-section
enterprise platform requirement set.

**Method.** Every section is checked against the repository *and* the live
estate, not against memory of what was built. Every number below was produced
by running something — the policy loader, the offline plan, the test suite, or a
live Datadog query — and the command is named in the Validation column so the
claim can be re-checked rather than believed. Nothing is recorded as MISSING
because it was not found quickly; each MISSING row was confirmed by a
repository-wide search that returned zero matches.

**Status vocabulary**

| Status | Meaning |
|---|---|
| **OK** | Exists and is correct. Preserve. |
| **IMPROVE** | Exists and works; a specific defect or narrowness to fix. |
| **PARTIAL** | Some of the requirement is implemented, some is not. |
| **MISSING** | Nothing implements this. |
| **OBSOLETE** | Exists and should be removed. |
| **N/A** | Not applicable to the current estate. |

---

## Scorecard

| Status | Sections |
|---|---|
| OK | 43 |
| IMPROVE | 6 |
| PARTIAL | 8 |
| MISSING | 1 |
| OBSOLETE | 1 (resolved) |
| N/A | 1 |

**The measured state of the platform**

| | |
|---|---|
| Monitor archetypes | 270 across 14 domains |
| Planned monitor instances | 676 |
| SLOs | 21 domain + per-service, resolved through an 8-layer chain |
| Runbooks | 270, published as notebooks, attached via the monitor `assets` field |
| Teams | 7 |
| Registered entities | 6, across 5 Datadog entity kinds |
| Reports | 20, in 6 families |
| MCP | 30 grounded questions, 23 tools |
| Tests | 555 — 340 platform · 161 MCP · 54 portal |

**Deployed to production** (deploy run #51, verified against the live org rather
than from the run's exit code):

| | Before | After |
|---|---|---|
| Monitors (prod) | 445 | **459** |
| SLOs (prod) | 22 | 22 (one replaced in place) |
| Dashboards | 18 | **3** |
| Catalog objects | 3 service definitions | **6 typed entities** |
| Runbook notebooks | 261 | **270** |
| Catalog services (live) | 25 | **4** |
| Runbook notebooks (live, org-wide) | 336 | **270** |

The idempotency gate — a second plan must be empty — passed, which is the
evidence that the apply converged rather than merely exited zero.

The last two rows are the §6 cleanup, run separately through
`catalog_reconcile.py --delete`: 22 catalog entries from a superseded
repository and 66 unowned notebooks removed, leaving the live org holding
exactly what this platform declares. One detail worth recording because it
looks like a partial result and is not: 4 notebooks still carry the
`dd-ai-start` author handle. They were ADOPTED by name in an earlier session —
`publish_runbooks` adopts a same-name notebook rather than creating a
duplicate — so they are managed runbooks that kept their original author. 58
of the 62 were deleted; the other 4 were never unmanaged.

### What changed since the first audit

The first pass recorded 14 MISSING sections. Nine parallel workstreams closed
them. The honest headline has not changed and is stated at §60: **the monitors
are correct and most of them still return no data**, because the telemetry does
not yet carry the tags the queries select on (§8). Building more monitors does
not fix that; §8 does.

---

## 1–3 · Audit, completion discipline, technology scope

| § | Requirement | Status | Where | Gap → Remediation | Validation |
|---|---|---|---|---|---|
| 1 | Repository/platform gap analysis first | **OK** | this document | — | — |
| 2 | Work to completion, not to recommendations | **OK** | delivered work is deployed, not proposed | — | production deploy green; evidence artifact per run |
| 3 | Estate is Azure, VMware, Azure SQL, SQL Server, Snowflake, Cosmos | **OK** | `platform/policy/archetypes/` | PostgreSQL retirement is COMPLETE — the transitional file is deleted, and no archetype or SLO query reads a `postgresql.` metric | `test_the_postgres_retirement_is_complete` |

---

## 4 · Payments removal

| § | Requirement | Status | Where | Gap → Remediation | Validation |
|---|---|---|---|---|---|
| 4 | Remove payments team and all payment configuration | **OBSOLETE → resolved** | `teams.yaml`, `platform/entities/`, `platform/monitors/` | Team, 2 services, 3 self-service manifests, 1 tier0 SLO, 15 notification rules, 2 schedules, 1 escalation policy, 7 monitors removed | `payment` count in source, in both rendered plans, and in the live estate = **0** |

---

## 5–7 · Catalog and entity modelling

| § | Requirement | Status | Where | Gap → Remediation | Validation |
|---|---|---|---|---|---|
| 5 | Correct entity types | **OK** | `platform/entities/`, `platform/policy/entity_kinds.yaml`, `modules/catalog_entity`, `tools/entity_resolver.py` | Registration declares `kind:`; the resolver maps it to the v3 entity union. **Scope correction:** that union is `service, datastore, queue, system, api` — there is no Frontend App or Repository kind. A frontend registers as a `service` of `spec.type: web` and says so in the catalog rather than inventing a kind the API rejects | `test_entity_model.py`; kind census via `make entities` |
| 6 | Catalog = actual managed estate | **OK** | `platform/entities/` (6), `tools/catalog_reconcile.py` | Every check ran forward — is what we declared deployed? — and none ran backward. The reconciler answers the backward question for catalog entries AND runbooks, reports by default and deletes only on an explicit dispatch. It found 22 catalog services from a superseded repository with no telemetry, 4 orphan notebooks, and 62 authored by Datadog's own agent | `make reconcile`; `test_catalog_reconcile.py` |
| 7 | Reconcile discovered vs managed, do not duplicate | **OK** | `tools/build_inventory.py`, `tools/reconciliation_report.py` | Discovered telemetry enriches a registration rather than creating a second object; unregistered discoveries land in the unowned pool with an SLA | reconciliation report; `test_reconciliation.py` |

---

## 8 · Unified tagging

| § | Requirement | Status | Where | Gap → Remediation | Validation |
|---|---|---|---|---|---|
| 8 | Consistent `service` / `env` / `version` identity across APM, logs, metrics, RUM, monitors, SLOs, catalog | **PARTIAL** | `docs/tagging-standard.md`, `platform/policy/global.yaml` | **This is the single most consequential open item in the audit.** The standard is written and complete. Nothing emits `alert_band` onto telemetry, so every query that selects on it matches an empty set — the monitors are correct and silent. Remediation and the two honest options are in `docs/tagging-standard.md` | `profile_engine.py` violations; `deployment-version-tag-missing` archetype |
| 8 | Fix CI/CD so deployment metadata reaches Datadog | **MISSING** | — | No pipeline sets `DD_VERSION` / `DD_GIT_COMMIT_SHA`. This is the one remaining MISSING row in the matrix. Remediation: set both in the deploy workflow and document the per-runtime equivalent | deployment events visible in Datadog |

---

## 9–10 · YAML as source of intent

| § | Requirement | Status | Where | Gap → Remediation | Validation |
|---|---|---|---|---|---|
| 9 | Layered inheritance | **OK** | `platform/policy/` 8-layer hierarchy | Terraform interprets; it never decides | `test_policy_model.py` |
| 10 | One YAML onboards an entity | **OK** | `platform/entities/*.yaml`, `platform/schemas/entity.schema.json` | Accepts `kind`, `platform`, `criticality`, `monitoring_profile`, `slo`, `oncall`, `dependencies`, `components` | `test_entity_model.py`; the MCP generates and validates one in `test_generated_entity_yaml_validates` |

---

## 11–15 · SLOs

| § | Requirement | Status | Where | Gap → Remediation | Validation |
|---|---|---|---|---|---|
| 11 | Service may have 0, 1 or many SLOs | **OK** | `platform/policy/slo_profiles.yaml` | An entity type declares an objective SET (availability / latency / freshness); a service resolves any subset | `test_slo_profiles.py` |
| 12 | SLO resolution chain ending in service override | **OK** | `tools/slo_resolver.py`, `stacks/coverage/slos.tf` | 8 layers, per-field provenance. **`scope` and `profile` are separate keys**: `scope` decides whether an entity gets its own SLO, `profile` which objectives — they were briefly the same key, and the collision gave four entities the SLO they were declining | `terraform console` and `slo_resolver` both return `[identity-api]`; `test_declining_an_slo_does_not_materialize_one` |
| 13 | SLO/catalog association actually works | **OK** | C18 in `tools/coverage_report.py` | Every SLO must name an entity that exists; an SLI with an unsubstituted placeholder is a finding | C18 |
| 14 | Not every entity needs an SLO | **OK** | effective scope, per entity | — | `test_a_tier2_service_carries_no_objectives_of_its_own` |
| 15 | Monitor-to-SLO governance classification | **OK** | `slo_relation` on every archetype (8 relations) | Lint rejects a monitor-SLO member that does not declare `sli_producing` — the check that caught 7 archetypes when the database latency SLI was rebuilt | `validate_policy.py` REFERENCE checks |

---

## 16–18 · Profiles, single-YAML monitors, predictive-first

| § | Requirement | Status | Where | Gap → Remediation | Validation |
|---|---|---|---|---|---|
| 16 | Monitoring profiles resolve from entity type + platform + env + criticality + telemetry | **OK** | `platform/policy/profiles.yaml`, `tools/profile_engine.py` | Telemetry availability is the last step: a profile whose every pack member is blocked demotes to `observe_only` with the missing sources named. **Packs are now selected by `platform`** — a datastore no longer claims SQL Server, Cosmos and Snowflake coverage at once | `test_a_profile_does_not_claim_coverage_it_cannot_deliver`; `test_a_datastore_gets_only_its_own_technology_packs` |
| 17 | One YAML file adds a monitor | **OK** | `platform/policy/archetypes/*.yaml`, 270 archetypes | Naming, tags, routing, runbook, workflow, recovery, correlation all derived | `test_self_service.py`, `validate_policy.py` |
| 18 | Predictive-first | **OK** | `global.yaml → detection_policy` | Fixed thresholds require a recorded rationale | `test_predictive_detection_dominates` |

---

## 19–23 · Coverage by technology

| § | Requirement | Status | Where | Gap → Remediation | Validation |
|---|---|---|---|---|---|
| 19 | Azure coverage (20 named services) | **OK** | `azure-*.yaml` | All 20 covered; NSG via a log-derived metric, documented | live monitor validation |
| 20 | Cost — anomaly, budget, forecast, growth, subscription trend | **OK** | `azure-cost.yaml` | 5 layers; nothing pages | priority matrix test |
| 21 | SQL Server / Azure SQL / Cosmos / Snowflake depth | **OK** | `sqlserver.yaml`, `cosmosdb.yaml`, `snowflake.yaml` | Metric names verified against published integration lists, not guessed | live validation |
| 22 | Application — APM, runtime, pools, GC, deployment, RUM CWV | **OK** | `application-runtime.yaml` | Runtime-aware by metric namespace | live validation |
| 23 | Infrastructure and VMware | **IMPROVE** | `infrastructure*.yaml`, `vmware.yaml` | Swap, hardware, patch/EOL covered. VMware HA/DRS events and orphaned-VM detection still not covered | archetype census per the §23 checklist |

---

## 24 · Control-M

| § | Requirement | Status | Where | Gap → Remediation | Validation |
|---|---|---|---|---|---|
| 24 | Real-time in-flight job anomaly detection | **OK** | `platform/policy/archetypes/controlm.yaml` (9 archetypes) | In-flight duration ratio, late start, not executed, abnormally short, runtime drift, dependency failure, stale last success, job failure, exporter telemetry loss. Emission contract in `docs/telemetry-gaps.md` §9; a dedicated `controlm_exporter` telemetry source rather than a borrowed one | `test_controlm.py`; the 9 runbooks publish on the next deploy |

Note: an earlier instruction in this engagement removed Control-M from scope.
The requirement set reinstates it; the reinstatement is treated as authoritative
and was flagged at the time rather than silently applied.

---

## 25–30 · Events, incidents, on-call, routing, ServiceNow

| § | Requirement | Status | Where | Gap → Remediation | Validation |
|---|---|---|---|---|---|
| 25 | Event Management pipeline | **PARTIAL** | `platform/events/correlation-rules.yaml`, `tools/correlate_events.py` | Rules are an executable specification; `correlation_key`/`dedup_key` are stamped on every monitor so native aggregation works. Datadog Event Management itself is still not configured from here | correlation test; live event-aggregation check |
| 26 | Correlation examples incl. Control-M | **OK** | same | The Control-M rule exists now that the signals do | `test_correlation.py` |
| 27 | Incident Management + Incident Command | **PARTIAL** | `notification_profiles.yaml` | Severity → incident intent is declared and routes. No incident-command role model, no timeline/PIR automation | live incident created from a P1 |
| 28 | On-Call: teams, schedules, escalation, routing, recovery | **IMPROVE** | `modules/team_oncall` | Structure is complete: 7 teams, 14 schedules, 7 four-step policies. **Rosters are empty** — every position is unassigned, so a page reaches nobody. This is a data gap the platform cannot close for itself: no users have been provided, and the requirement set forbids inventing them | schedule occupancy check; the portal reports on-call coverage as 0% rather than hiding it |
| 29 | Centralized routing, no PagerDuty/Slack | **OK** | `modules/notification_rules` | Monitors carry no destinations; every route resolves | route resolution census |
| 30 | ServiceNow used intentionally | **OK** | `notification_profiles.yaml` | P1 incident / P2 incident / P3 task / P4 none | route census |

---

## 31–35 · Runbooks, workflows, dashboards, reports, survey

| § | Requirement | Status | Where | Gap → Remediation | Validation |
|---|---|---|---|---|---|
| 31 | Real Datadog-native runbooks | **OK** | `platform/runbooks/` (270), `tools/publish_runbooks.py` | Published as notebooks, attached via `assets`; no URLs in monitor messages | attachment census; C16 |
| 32 | Workflow Automation with a safety contract | **IMPROVE** | `modules/workflow_automation`, 27 catalogued | Classes: manual / guided / approval / automatic. **Only 2 deploy** — 18 legacy workflows hold the org quota. External blocker | quota release, then budget raise |
| 33 | Minimal dashboards (~3–4) | **OK** | `stacks/foundation/dashboards.tf` | **3 dashboards**: enterprise overview, operations reliability, SLO executive health. The 14 generated per-domain dashboards were retired in favour of native domain views and the monitor list | dashboard census |
| 34 | Reports catalog | **OK** | `tools/reports.py` — 20 reports in 6 families (exec, ops, plat, db, azure, infra) | Runs offline against the committed fixtures in CI, so the review queue is in the PR artifact | `test_reports.py`; `make reports` |
| 35 | Observability survey | **OK** | `docs/observability-survey.md` | Asks only what cannot be inferred from telemetry or policy | onboarding walkthrough |

---

## 36–41 · Fleet, agents, telemetry requirements, scorecards

| § | Requirement | Status | Where | Gap → Remediation | Validation |
|---|---|---|---|---|---|
| 36 | Fleet Management standard and automation | **OK** | `platform/policy/agent_profiles.yaml`, `tools/fleet_compliance.py` | Declares the required fleet, minimum version, offline threshold and exemption rules with recorded reasons | `make fleet`; `test_fleet_compliance.py` |
| 37 | Standard agent profiles | **OK** | 5 profiles + conditional profiles keyed on `os_family`, `service_archetype`, `db_engine` | `db_engine` exists because `service_archetype: datastore` cannot tell SQL Server from Cosmos DB and they need different agent configuration | profile → check census |
| 38 | Every monitor declares required telemetry | **OK** | `telemetry:` on all 270 archetypes; 40-source vocabulary | The lint DERIVES the requirement from each query and rejects a declaration that disagrees, so it cannot drift | `validate_policy.py` TELEMETRY checks |
| 39 | Fleet compliance detection and percentage | **OK** | `tools/fleet_compliance.py`, 8 checks | The denominator is the **inventory**, not the host list — a denominator built from hosts that already report is 100% compliant by construction, and a host with no agent would be invisible. A denominator of zero is reported as *not measured*, never as 100% | `test_fleet_compliance.py`; the MCP's `broken_agents` answer |
| 40 | Private synthetic locations | **N/A** | — | Conditional on internal apps needing them. No internal endpoint in the current inventory requires a private location, and the requirement set forbids fabricating locations | inventory of internal endpoints |
| 41 | Entity-aware scorecards | **OK** | `platform/policy/scorecards.yaml`, `tools/monitor_scorecard.py` | Grades ENTITIES via `resource_type → kind`, with an explicit exhaustive classification that raises on an unclassified type rather than defaulting | scorecard run; `test_scorecard.py` |

---

## 42–46 · MCP server

| § | Requirement | Status | Where | Gap → Remediation | Validation |
|---|---|---|---|---|---|
| 42 | Production MCP server, independent of Bits AI | **OK** | `mcp/` — 23 tools over the same policy engine Terraform reads | No second interpretation of policy anywhere in it | `test_tool_contracts.py` |
| 43 | Ask mode — 30 grounded questions | **OK** | `mcp/obs_ask.py` — 30 questions | Every answer cites a real file, API route or named fixture; an unknown subject is a refusal, not an invention | `test_ask_grounding.py`, incl. `test_evidence_sources_are_resolvable` |
| 44 | Act mode — inspect, validate, generate, PR, plan, apply | **OK** | `mcp/obs_act.py`, `mcp/obs_gitops.py` | Generates an entity registration, validates it with the **same** schema and resolver CI runs, and proposes a PR. It cannot propose a file its own gate would reject | `test_act_gitops.py` |
| 45 | MCP safety: authn, RBAC, dry run, approval, audit | **OK** | `mcp/obs_governance.py` | Write fence (deny-first), plan tokens bound to content, environment authorization, named second approver for production, audit line per call | `test_governance.py` — negative tests for each refusal |
| 46 | MCP architecture (intent router, read/git/ops planes) | **OK** | `mcp/obs_router.py` + the three planes | — | `mcp/README.md`; contract tests |

---

## 47–50 · Executive surfaces

| § | Requirement | Status | Where | Gap → Remediation | Validation |
|---|---|---|---|---|---|
| 47 | Executive real-time web portal | **OK** | `portal/` | Read-only by construction: GET/HEAD only, no verb but GET in the Datadog client, both asserted by tests | `portal/tests` (54, all offline) |
| 48 | Progressive drilldown enterprise → system → service → SLO → incident | **OK** | `portal/app/view.py` | Verified in a headless browser | drilldown test |
| 49 | Portal reads live Datadog APIs, shows freshness, read-only role | **OK** | `portal/app/datadog.py`, `sources.py` | Every view carries a *where these numbers come from* table with origin, state and data age. Fixture mode is the default and is labelled; `--live` without both keys exits rather than serving recorded data under a live label | freshness test; a test that plants a fake key in the environment and greps every response |
| 50 | Executive presentation (32 topics) | **OK** | `docs/presentation/` | 55 slides (43 + 12 appendix) with speaker notes, generated from a script so a number changes in one place. 22 slides carry ROADMAP / PARTIAL / ACT-NOW status pills | deck review |

---

## 51–57 · Outcomes, SOPs, CI/CD, repository quality, RBAC, architecture

| § | Requirement | Status | Where | Gap → Remediation | Validation |
|---|---|---|---|---|---|
| 51 | Expected outcomes documented | **PARTIAL** | `README.md`, `docs/operating-model.md`, the reports catalog | Coverage, simplicity and noise are documented and now measured by the reports. No before/after baseline exists, because there was no instrumented "before" | outcome metrics |
| 52 | New entity SOP | **OK** | `docs/golden-path.md` | Entity-kind aware, including which kinds carry dependencies and which do not | walkthrough |
| 53 | New monitor SOP | **OK** | `docs/golden-path.md`, `docs/implementation-guide.md` | — | walkthrough |
| 54 | CI/CD guardrails (30 validations) | **IMPROVE** | `.github/workflows/ci.yml`, `tools/validate_*.py` | Entity-kind, SLO/catalog identity and duplicate-SLO checks now exist. Orphan-resource detection is still not a gate | CI job matrix |
| 55 | Repository quality and directory documentation | **OK** | `README.md` | Examples moved out of production config; the map names `platform/entities/`, `mcp/`, `portal/` and the presentation | tree review |
| 56 | Minimal RBAC (~6 roles) | **OK** | `modules/rbac` | 4 roles | role census |
| 57 | End-state architecture | **IMPROVE** | `docs/reference-architecture.md` | Documents the monitoring spine. The MCP and portal planes are documented in their own READMEs but not yet folded into the architecture document | architecture doc |

---

## 58–60 · Deliverables, proofs, acceptance

| § | Requirement | Status | Gap |
|---|---|---|---|
| 58 | 56 named deliverables | **PARTIAL** | 49 complete, 6 partial, 1 blocked externally (workflow quota) |
| 59 | Automation proofs | **OK** | Entity-kind, SLO-resolution, Control-M, MCP and portal proofs all exist as tests now |
| 60 | Final acceptance criteria | **PARTIAL** | See below |

---

## §60 · What is genuinely not done

Five things, stated plainly, because a matrix of green rows is exactly where an
audit becomes misleading.

1. **The telemetry does not carry `alert_band` (§8).** 676 monitors are correct
   and most of them return no data. This is the top of the list and nothing
   else on it matters as much. It is not fixable inside this repository — it is
   an agent-configuration and service-registration change on the emitting side.
2. **Deployment metadata never reaches Datadog (§8).** No pipeline sets
   `DD_VERSION` / `DD_GIT_COMMIT_SHA`, so version-grouped queries and
   deployment correlation cannot work. This is the one MISSING row.
3. **On-call rosters are empty (§28).** The escalation structure is real and a
   page would traverse it correctly to nobody. No users have been provided, and
   fabricating them is forbidden — correctly.
4. **The org workflow quota is held by 18 legacy workflows (§32).** 2 of 27
   catalogued workflows deploy. External blocker.
5. **Datadog Event Management and incident command are declared, not
   configured (§25, §27).** Severity routes to an incident; the role model,
   timeline and PIR automation do not exist.

Two smaller ones, recorded so they are not lost: VMware HA/DRS and orphaned-VM
detection (§23), and orphan-resource detection as a CI gate (§54).

**One defect in this platform's own pipeline.** `publish_runbooks --write-registry`
writes notebook ids into `platform/policy/runbooks.yaml` in the CI checkout, which
is then discarded, so the committed registry permanently trails production — today
by 9, the Control-M runbooks. Nothing breaks, because publishing re-adopts by name
each run, but the repository never records what it published. It is called out here
rather than papered over because the catalog reconciler had to be built around it:
matching notebooks by id alone would have classified the newest runbooks as
unmanaged and deleted them. The reconciler counts the drift
(`notebooks_published_but_unrecorded`) so a fallback that quietly covers for it
cannot hide it. The real fix is for the deploy to commit the registry back, or for
the ids to live with state rather than inside intent.

---

## Where the phases landed

| Phase | Work | Sections closed |
|---|---|---|
| **1** | Entity model, kinds, catalog reconciliation | §5, §6, §7, §10, §41, §59 |
| **2** | Telemetry requirements on every archetype + applicability | §16, §38, §39 |
| **3** | Fleet management + agent profiles | §36, §37, §39 |
| **4** | SLO profiles and per-service objectives | §11, §12, §13, §15 |
| **5** | Control-M in-flight monitoring | §24, §26 |
| **6** | Reports catalog, dashboard consolidation, survey, scorecards | §33, §34, §35, §41 |
| **7** | MCP server: Ask, Act, governance | §42–§46 |
| **8** | Executive portal | §47–§49 |
| **9** | Presentation | §50 |
| **integration** | Reconciling the seams the parallel phases left | §3, §12, §16, §31, §34 |

The integration pass is listed because it was not bookkeeping. Phases 1 and 4
independently used `slo.profile` to mean two different things, and the
collision gave four entities an SLO they had declined while Terraform and the
coverage report disagreed about how many existed. The datastore archetype
claimed three database technologies at once. The MCP wrote registrations to a
directory the entity model had replaced, and its production approval gate did
not recognise the new format — an entity targeting prod reported no
environments and skipped the second-approver requirement entirely. None of
these failed a test until they were looked for.
