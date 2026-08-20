# Requirement traceability matrix

Audit of this repository and the deployed Datadog org against the 60-section
enterprise platform requirement set.

**Method.** Every section was checked against the repository *and* the live
estate — the last production deploy's evidence artifact (651 monitors, 22 SLOs,
111 notification rules, 261 runbooks), not against memory of what was built.
Nothing is recorded as MISSING because it was not found quickly; each MISSING
row was confirmed by a repository-wide search that returned zero matches.

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
| OK | 22 |
| IMPROVE | 10 |
| PARTIAL | 10 |
| MISSING | 15 |
| OBSOLETE | 1 (resolved) |
| N/A | 2 |

The platform is strong on the **monitor → SLO → routing → runbook** spine and
absent on the **product surfaces** — MCP server, executive portal,
presentation, survey — and on **fleet/agent operations** and **Control-M**.

---

## 1–3 · Audit, completion discipline, technology scope

| § | Requirement | Status | Where | Gap → Remediation | Validation |
|---|---|---|---|---|---|
| 1 | Repository/platform gap analysis first | **OK** | this document | — | — |
| 2 | Work to completion, not to recommendations | **OK** | delivered work is deployed, not proposed | — | production deploy #44 green |
| 3 | Estate is Azure, VMware, Azure SQL, SQL Server, Snowflake, Cosmos | **OK** | `platform/policy/archetypes/` | PostgreSQL/Redis-integration archetypes already removed; AWS/GCP never present | `grep postgresql` → transitional file only |

---

## 4 · Payments removal

| § | Requirement | Status | Where | Gap → Remediation | Validation |
|---|---|---|---|---|---|
| 4 | Remove payments team and all payment configuration | **OBSOLETE → resolved** | `teams.yaml`, `platform/services/`, `platform/monitors/` | Team, 2 services, 3 self-service manifests, 1 tier0 SLO, 15 notification rules, 2 schedules, 1 escalation policy, 7 monitors removed | Plan deltas 658→651 monitors, 126→111 rules, 8→7 teams; `payment` count in both rendered plans = **0** |

---

## 5–7 · Catalog and entity modelling

| § | Requirement | Status | Where | Gap → Remediation | Validation |
|---|---|---|---|---|---|
| 5 | Correct entity types — System, Datastore, Queue, API, Endpoint, Frontend App, Repository, External Provider | **IMPROVE** (was PARTIAL) | `platform/schemas/entity.schema.json`, `platform/policy/entity_kinds.yaml`, `tools/entity_resolver.py`, `modules/catalog_entity` | Phase 1 delivered: `kind:` in the schema, v3 entities of the correct kind emitted by `datadog_software_catalog`, and an `infrastructure_resource` is now rejected rather than silently becoming a Service. **Two named types have no Datadog kind to map to** — the v3 entity union is exactly `service, datastore, queue, system, api` (verified against the generated API client), so `frontend_app` emits `service` + `spec.type: web` + an `entity_kind:` tag, and `repository` emits nothing. Endpoint and External Provider are modelled as `api` and `service` (archetype `saas_dependency`) | `tools/entity_resolver.py` census; `tests/test_entity_model.py` |
| 6 | Catalog = actual managed estate | **PARTIAL** | `platform/entities/` (6 entities: 2 services, 1 frontend app, 1 datastore, 1 queue, 1 system) | Live catalog holds 27 service-catalog entries; 6 are managed here. Demo/fabricated entries not yet reconciled, and the discovered population is still emitted as v2.2 services by `modules/service_catalog` | `build_inventory.py --live` census vs `platform/entities/` |
| 7 | Reconcile discovered vs managed, do not duplicate | **PARTIAL** | `tools/build_inventory.py` reads `/api/v1/hosts` + service definitions | Reads discovery but does not *reconcile* — no merge of discovered telemetry with YAML intent | reconciliation report showing enriched vs duplicated |

---

## 8 · Unified tagging

| § | Requirement | Status | Where | Gap → Remediation | Validation |
|---|---|---|---|---|---|
| 8 | Consistent `service` / `env` / `version` identity across APM, logs, metrics, RUM, monitors, SLOs, catalog | **PARTIAL** | `docs/tagging-standard.md`, `platform/policy/global.yaml` | Standard is written and complete. **Nothing emits `alert_band` onto telemetry**, so every query filters to an empty set; `version` is grouped on but not emitted | `profile_engine.py` violations; `deployment-version-tag-missing` archetype |
| 8 | Fix CI/CD so deployment metadata reaches Datadog | **MISSING** | — | No pipeline sets `DD_VERSION` / `DD_GIT_COMMIT_SHA`. Remediation: add to the deploy workflow and document per-runtime | deployment events visible in Datadog |

---

## 9–10 · YAML as source of intent

| § | Requirement | Status | Where | Gap → Remediation | Validation |
|---|---|---|---|---|---|
| 9 | Layered inheritance: global → entity type → platform → profile → env → criticality → team → override → exception | **OK** | `platform/policy/` 8-layer hierarchy | Layer names differ (domain/archetype/band rather than entity-type/platform) but the mechanism is identical | `test_policy_model.py` |
| 10 | One YAML onboards an entity | **OK** (was PARTIAL) | `platform/entities/*.yaml`, `platform/schemas/entity.schema.json` | Closed. `kind:`, `platform:`, `env:`, `region:`, `criticality:`, `monitoring_profile:`, `slo.profile:`, `oncall:`, typed `dependencies:` and `components:` are all accepted, and `tier:` was renamed to the §10 name `criticality:` without changing the telemetry tag | `test_every_entity_file_validates_against_the_schema`, `test_the_migrated_services_kept_every_field` |

---

## 11–15 · SLOs

| § | Requirement | Status | Where | Gap → Remediation | Validation |
|---|---|---|---|---|---|
| 11 | Service may have 0, 1 or many SLOs | **PARTIAL** | `platform/policy/slos.yaml` (22 SLOs) | Domain SLOs plus one auto tier0 per-service SLO. A service cannot declare *multiple* named objectives | schema + resolver test |
| 12 | SLO resolution chain ending in service override | **PARTIAL** | `stacks/coverage/slos.tf` | Resolves enterprise → domain → tier0 template. No `slo_profile` layer, no per-service objective override | two-services-same-profile-different-target test (§59) |
| 13 | SLO/catalog association actually works | **IMPROVE** | `modules/slo` | SLOs carry `service:` and `slo_id` tags; association to the catalog entity is not asserted anywhere | add C-check joining SLO tags to catalog entities |
| 14 | Not every entity needs an SLO | **OK** | tier0-only per-service SLOs; infrastructure has none | — | `slos.tf` tier0 filter |
| 15 | Monitor-to-SLO governance classification | **MISSING** | — | Monitors carry `slo_id` but no `slo_relation` (SLI-producing / supporting / impacting / diagnostic / informational) | archetype schema field + lint rule |

---

## 16–18 · Profiles, single-YAML monitors, predictive-first

| § | Requirement | Status | Where | Gap → Remediation | Validation |
|---|---|---|---|---|---|
| 16 | Monitoring profiles resolve from entity type + platform + env + criticality + telemetry | **IMPROVE** | `platform/policy/profiles.yaml`, `service_archetypes.yaml` packs | Resolves from service_archetype → packs → archetypes. **Telemetry availability is not an input** | applicability test with telemetry absent |
| 17 | One YAML file adds a monitor, framework supplies the rest | **OK** | `platform/policy/archetypes/*.yaml`, 264 archetypes | Naming, tags, routing, runbook, workflow, recovery, correlation all derived | `test_self_service.py`, `validate_policy.py` |
| 18 | Predictive-first | **OK** | `global.yaml → detection_policy` | Fixed thresholds require a recorded `rationale_fixed_threshold`; lint enforces it | `test_predictive_detection_dominates` |

---

## 19–23 · Coverage by technology

| § | Requirement | Status | Where | Gap → Remediation | Validation |
|---|---|---|---|---|---|
| 19 | Azure coverage — VM, SQL, Cosmos, Service Bus, Event Hub, Front Door, CDN, APIM, Firewall, NSG, ExpressRoute, VPN GW, Private Endpoint, DNS, Redis, ACR, Traffic Manager, Storage, Key Vault, LB | **OK** | `azure-*.yaml` catalogs, 47 cloud + 24 network archetypes | All 20 named services covered; NSG via log-derived metric (documented) | live monitor validation, 604/604 queries valid |
| 20 | Cost — anomaly, budget, forecast, growth rate, subscription trend | **OK** | `azure-cost.yaml` | 5 layers; nothing pages | `test_policy_model` priority matrix |
| 21 | SQL Server / Azure SQL / Cosmos / Snowflake depth | **OK** | `sqlserver.yaml`, `cosmosdb.yaml`, `snowflake.yaml` | Blocking and deadlocks separate; tempdb, log, AlwaysOn, failover, restore verification | metric names verified against published integration lists |
| 22 | Application — APM, runtime, pools, GC, deployment, RUM CWV | **OK** | `application-runtime.yaml` | Runtime-aware by metric namespace | live validation |
| 23 | Infrastructure and VMware | **IMPROVE** | `infrastructure*.yaml`, `vmware.yaml` | Swap, hardware, patch/EOL added. **VMware HA/DRS events and orphaned-VM detection not covered** | archetype census per §23 checklist |

---

## 24 · Control-M

| § | Requirement | Status | Where | Gap → Remediation | Validation |
|---|---|---|---|---|---|
| 24 | Real-time in-flight job anomaly detection | **MISSING** | — (repo-wide search for `control_m`/`controlm` returns **0 files**) | No Control-M integration, metrics, archetypes or runbooks. Remediation: define the six `controlm.job.*` custom metrics, an emitter contract in `telemetry-gaps.md`, and archetypes for in-flight duration ratio, missed start, abnormal short run, dependency failure | duration-ratio anomaly firing on a synthetic long-running job |

Note: an earlier instruction in this engagement removed Control-M from scope.
This prompt reinstates it; the reinstatement is treated as authoritative.

---

## 25–30 · Events, incidents, on-call, routing, ServiceNow

| § | Requirement | Status | Where | Gap → Remediation | Validation |
|---|---|---|---|---|---|
| 25 | Event Management pipeline | **PARTIAL** | `platform/events/correlation-rules.yaml`, `tools/correlate_events.py` | Rules exist as an **executable specification**; `correlation_key`/`dedup_key` are stamped on every monitor so native aggregation works. Nothing configures Datadog Event Management itself | correlation test + live event-aggregation check |
| 26 | Correlation examples (database, VMware, network, deployment, Control-M) | **PARTIAL** | same | 6 rules with root-cause ranking; Control-M rule absent | `test_correlation.py` |
| 27 | Incident Management + Incident Command | **PARTIAL** | `notification_profiles.yaml` (`datadog_incident: SEV-1`) | Severity → incident intent is declared; no incident-command role model, no timeline/PIR automation | live incident created from a P1 |
| 28 | On-Call: teams, schedules, escalation, routing, recovery | **IMPROVE** | `modules/team_oncall` | 7 teams, 14 schedules, 7 four-step policies. **Rosters are empty** — every position is unassigned, so a page reaches nobody | schedule occupancy check |
| 29 | Centralized routing, no PagerDuty/Slack | **OK** | `modules/notification_rules` (111 rules) | Monitors carry no destinations | route resolution: 651/651 resolve |
| 30 | ServiceNow used intentionally | **OK** | `notification_profiles.yaml` | P1 incident / P2 incident / P3 task / P4 none | route census |

---

## 31–35 · Runbooks, workflows, dashboards, reports, survey

| § | Requirement | Status | Where | Gap → Remediation | Validation |
|---|---|---|---|---|---|
| 31 | Real Datadog-native runbooks, not repository links | **OK** | `platform/runbooks/` (261), `tools/publish_runbooks.py` | Published as notebooks, attached via the monitor `assets` field | 651/651 attached, 0 URLs in messages |
| 32 | Workflow Automation with a safety contract | **IMPROVE** | `modules/workflow_automation`, `workflows.yaml` (27) | Catalogued with manual/guided/approval/automatic classes. **Only 2 deploy** — the org workflow quota is held by 18 legacy workflows | quota release, then budget raise |
| 33 | Minimal dashboards (~3–4) | **IMPROVE** | `stacks/foundation/dashboards.tf` | **18 dashboards**: 4 hand-authored + 14 generated per-domain. Requirement is ~4. Remediation: keep enterprise / operations / SLO-executive, retire the per-domain generator in favour of native domain views | dashboard census |
| 34 | Reports catalog (executive, ops, platform, database, Azure) | **MISSING** | — | `tools/coverage_report.py` and the scorecard produce two reports; the five report families in §34 do not exist | report catalog with named outputs |
| 35 | Observability survey | **MISSING** | — (repo-wide search for `survey` returns **0 files**) | Remediation: a short YAML/markdown questionnaire capturing only what cannot be inferred | onboarding walkthrough |

---

## 36–41 · Fleet, agents, telemetry requirements, scorecards

| § | Requirement | Status | Where | Gap → Remediation | Validation |
|---|---|---|---|---|---|
| 36 | Fleet Management standard and automation | **MISSING** | mentioned in 5 docs, implemented nowhere | No agent deployment automation, no Azure Policy/extension/golden-image path | fleet compliance percentage |
| 37 | Standard agent profiles (base, Windows, Linux, application, SQL Server) | **MISSING** | — | Remediation: `platform/policy/agent_profiles.yaml` + per-profile check configuration | profile → check census |
| 38 | Every monitor declares required telemetry | **MISSING** | — | Archetypes declare `resource_type` and `detection` but not a `telemetry:` requirement, so "can this monitor ever fire here?" is unanswerable | applicability engine report |
| 39 | Fleet compliance detection and percentage | **PARTIAL** | `agent-version-drift`, `host-agent-unhealthy`, `os-*` archetypes | Detects agent health and drift; no compliant/required ratio | compliance metric |
| 40 | Private synthetic locations | **N/A → verify** | `saas.yaml` uses `synthetics.*` metrics | No `datadog_synthetics_test` or private-location resources. Requirement is conditional on internal apps needing them | inventory of internal endpoints |
| 41 | Entity-aware Datadog Scorecards | **PARTIAL** | `tools/monitor_scorecard.py` | A **local Python** scorecard over the catalog, not Datadog Scorecards, and it grades monitors rather than entities | Datadog scorecard rule census |

---

## 42–46 · MCP server

| § | Requirement | Status | Where | Gap → Remediation | Validation |
|---|---|---|---|---|---|
| 42 | Production MCP server, independent of Bits AI | **MISSING** | repo-wide search for `mcp` returns **0 files** | Nothing exists. Remediation: a server exposing catalog/monitor/SLO/event/incident/on-call/fleet/report tools over the same policy engine the Terraform uses | tool contract tests |
| 43 | Ask mode — 30 grounded questions | **MISSING** | — | — | each question answered from live state |
| 44 | Act mode — inspect, validate, generate, PR, plan, apply | **MISSING** | — | Must flow MCP → YAML/Git → PR → validation → Terraform → Datadog | PR created by MCP passes CI |
| 45 | MCP safety: authn, RBAC, dry run, approval, audit | **MISSING** | — | — | negative tests: unauthorized write refused |
| 46 | MCP architecture (intent router, read/git/ops planes) | **MISSING** | — | — | architecture doc + code layout |

---

## 47–50 · Executive surfaces

| § | Requirement | Status | Where | Gap → Remediation | Validation |
|---|---|---|---|---|---|
| 47 | Executive real-time web portal | **MISSING** | — | No web application in the repository | portal renders live health |
| 48 | Progressive drilldown enterprise → system → service → SLO → incident | **MISSING** | — | — | navigation test |
| 49 | Portal reads live Datadog APIs, shows freshness, SSO, read-only role | **MISSING** | — | — | freshness indicator |
| 50 | Executive presentation (32 topics) | **MISSING** | — | — | deck review |

---

## 51–57 · Outcomes, SOPs, CI/CD, repository quality, RBAC, architecture

| § | Requirement | Status | Where | Gap → Remediation | Validation |
|---|---|---|---|---|---|
| 51 | Expected outcomes documented | **PARTIAL** | `README.md`, `docs/operating-model.md` | Coverage/simplicity/noise are documented; no measured before/after | outcome metrics |
| 52 | New entity SOP (28 steps) | **PARTIAL** | `docs/golden-path.md` | Covers service onboarding; not entity-kind aware | walkthrough |
| 53 | New monitor SOP | **OK** | `docs/golden-path.md`, `docs/implementation-guide.md` | — | walkthrough |
| 54 | CI/CD guardrails (30 validations) | **IMPROVE** | `.github/workflows/ci.yml`, `tools/validate_*.py` | ~22 of 30 present. Missing: entity kind, SLO/catalog identity, duplicate SLO, telemetry requirement, orphan resource checks | CI job matrix |
| 55 | Repository quality and directory documentation | **IMPROVE** | `README.md` | Clean and documented; examples were mixed into production config (fixed in §4) and the docs index needs the new entity/MCP/portal locations | tree review |
| 56 | Minimal RBAC (~6 roles) | **OK** | `modules/rbac` | 4 roles; payments roles never existed separately | role census |
| 57 | End-state architecture | **PARTIAL** | `docs/reference-architecture.md` | Documents the current spine; MCP/portal planes absent | architecture doc |

---

## 58–60 · Deliverables, proofs, acceptance

| § | Requirement | Status | Gap |
|---|---|---|---|
| 58 | 56 named deliverables | **PARTIAL** | 27 complete, 14 partial, 15 not started |
| 59 | Automation proofs (Azure SQL, VMware, Cosmos, Snowflake, Control-M, app service, custom SLO, queue, new monitor, MCP, portal) | **PARTIAL** | Monitor-inheritance and SLO proofs exist as tests; entity-kind, Control-M, MCP and portal proofs cannot exist until those are built |
| 60 | Final acceptance criteria | **PARTIAL** | 38 of 62 criteria met today |

---

## Recommended sequence

Ordered by dependency, not by prompt order. Each phase is independently
shippable and leaves the platform working.

| Phase | Work | Unblocks |
|---|---|---|
| **1** | Entity model: `kind:` in the schema, entity resolver, System/Datastore/Queue/API kinds, catalog reconciliation | §5, §6, §7, §10, §41, §59 — **schema, resolver and kinds delivered**; catalog reconciliation (§7) still open |
| **2** | Telemetry requirements on every archetype + applicability engine | §16, §38, §39 |
| **3** | Fleet management + agent profiles + deployment metadata (`DD_VERSION`) | §8, §36, §37, §39 |
| **4** | SLO profiles and per-service objective overrides | §11, §12, §13, §15 |
| **5** | Control-M in-flight monitoring | §24, §26 |
| **6** | Reports catalog + dashboard consolidation + survey + scorecards | §33, §34, §35, §41 |
| **7** | MCP server: Ask, then Act, then governance | §42–§46 |
| **8** | Executive portal | §47–§49 |
| **9** | Presentation and final traceability review | §50, §58–§60 |

Phases 1–3 are the ones that change whether the platform *works*: today 651
correct monitors return no data because the telemetry does not carry the tags
they select on. Phases 7–8 are product surfaces on top of a platform that must
be true first.
