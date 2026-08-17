# Final Validation & Evidence Report

Executed 2026-08-17 in the build environment (Terraform 1.9.8, Datadog
provider 3.x latest in the `>=3.60,<4.0` window, Python 3.11). Every claim
below was produced by a command in this repo; CI re-runs all of them on every
PR (`.github/workflows/ci.yml`).

## 1. Environment inspection (live Datadog org, read API)

- Confirmed **0 monitors** (monitor search + monitor-group search:
  `total_count: 0`), 21 SLOs, 63 runbook notebooks, 18 workflows,
  5 platform dashboards, 22 catalog services, 0 reporting hosts.
- Found 4 monitor-type SLOs broken by deleted monitors and 3 metric SLOs with
  silent custom-metric telemetry. Details: `docs/current-state-assessment.md`.

## 2. Terraform validation & plan

| Check | Result |
|---|---|
| `terraform fmt -recursive -check` | clean |
| `terraform validate` — 9 modules | all pass against the real provider schema |
| `terraform validate` — 2 stacks | pass |
| Offline plan `stacks/coverage` | **95 resources: 89 monitors + 6 SLOs**, 0 errors |
| Offline plan `stacks/foundation` | 55 resources (teams, on-call, 21 routing rules, 18 workflows, 8 dashboards, downtime), 0 errors |
| Determinism | two consecutive plans, normalized and diffed: **identical (95/95)** |
| Live-API idempotency | requires org credentials; wired as post-deploy gate (`deploy.yml`: `terraform plan -detailed-exitcode` after apply) |

Plan-time guardrails demonstrably fire: during the build, the cardinality
precondition rejected an archetype grouping by `url` (banned key) — fixed at
the source, not silenced.

## 3. Live Datadog validation of generated monitors

A factory-rendered monitor (`[application][prod][sev2] Application Error Rate
Anomaly` — anomaly query, full contract message, 24 governance tags) was
submitted to Datadog's monitor-validation API: **`is_valid: true`**. The same
validation runs for *every* monitor at plan time when CI has credentials
(provider `validate` flag, enabled by default).

## 4. Test suite — 32/32 passing (`python -m pytest tests/`)

- **Scale:** 1,200,000-resource / 100,000-service synthetic estate through the
  profile engine: 100% of resources receive owner + env + criticality +
  profile; deliberate defects surface as violations; runtime well under the
  operational budget.
- **Profile policy:** tier1→critical, sandbox→observe-only-with-reason,
  security→security-sensitive, exception EXC-2026-001→observe-only,
  invalid env flagged, missing owner falls back + flags.
- **Governance gates:** the Terraform-planned monitor estate passes C5–C12
  clean; seeded click-ops, duplicate, runbook-less, workflow-less monitors and
  removed coverage packs are each detected by the right check; the org's real
  broken SLOs surface in C13.
- **Manifest gates:** the reference self-service manifest passes; 7 violation
  classes (unknown SLO/team/workflow, cardinality, unscoped query, unjustified
  fixed threshold, missing fields) are rejected with specific errors.
- **Event correlation:** a 6-event DB-failure storm (replication lag →
  connection saturation → app errors → app latency → burn alert + duplicate)
  collapses to **1 page, 1 incident, 4 suppressed children**; deployment
  events attach as context without paging; unrelated groups stay separate;
  recovery closes the group; sev3 never pages.
- **Runbooks:** template with all 9 mandatory sections enforced; renderer
  deterministic with embedded drift hash.

## 5. End-to-end pipeline demo (120k-resource estate)

`build_inventory --synthetic 120000` → `profile_engine` → `coverage_report`:

- 120,000 resources, 10,000 services; profiles: 20,200 critical /
  40,209 standard / 370 security-sensitive / **59,221 observe-only — every
  one with an explicit policy reason** (dev/sandbox/tier4/exception).
- **Coverage of the alertable estate: 100.0%** (60,779/60,779) from
  **89 monitors** — the bounded-object invariant at work.
- Seeded tag defects: 2,385 resources flagged by C3 (invalid vocabulary /
  unknown team), 0 unowned (domain-owner fallback + flag).
- Exit code 1 — correct: the report stays red while genuine gaps exist
  (C3 hygiene + C13's real telemetry gaps DG-1..3 in the live org).

## 6. Acceptance criteria traceability

| Criterion | Status | Evidence |
|---|---|---|
| 100% of discovered resources have profile/owner/criticality/env/coverage status | ✅ | §5; scale test §4 |
| 100% of alerting monitors carry SLO+runbook+workflow+team+routing+recovery+tags | ✅ | factory contract (§3), C5–C7=0 (§4) |
| Baseline coverage with zero team-authored monitors | ✅ | grouped `by {service}` packs; §5 |
| One small manifest → compliant custom monitor | ✅ | `payments-checkout-latency.yaml` → planned monitor; validator tests |
| Duplicates/unowned/untagged/unmanaged/expired-exceptions auto-identified | ✅ | C2/C3/C8/C9/C12 tests |
| Predictive detection + burn-rate alerts | ✅ | 19 burn monitors + anomaly/forecast/outlier/change archetypes (§2) |
| Correlation: many related alerts → one incident | ✅ | correlation tests (§4) |
| End-to-end on-call/Teams/ServiceNow/workflow/escalation/recovery tested | ◐ | full path implemented (routing rules, escalation policies, recovery messages, incident creation) and logic-tested (§4); the live fire-drill requires org credentials + rosters — scripted as migration step M2/M7 |
| Terraform validation & deployment pipelines pass | ✅ | §2; `ci.yml` mirrors every step |
| Second plan clean | ✅ (plan-determinism) / gated post-apply (§2) |
| Coverage report evidences every criterion | ✅ | this document + `coverage_report.py` outputs |

## 7. Honest limitations (and where they're handled)

1. **No apply was executed against the org** — this environment holds no
   Datadog write credentials (read-only MCP access only). Everything up to
   the API write boundary is executed and verified; applies run from
   `deploy.yml` behind the `datadog-production` approval gate using the
   `svc-observability-terraform` service account. Post-apply idempotency and
   the live coverage run are wired as pipeline steps, not manual follow-ups.
2. **Provider gaps** are documented with controlled API-backed paths:
   notebooks (ADR-006, hash-drift publisher) and event-correlation rule CRUD
   (ADR-007, deterministic keys + versioned ruleset + reference engine).
3. **On-call rosters** need real Datadog user IDs from IdP sync
   (`oncall_members` tfvars); schedules/policies are created the moment
   members exist (module handles the empty bootstrap safely).
4. **Live telemetry gaps** found in assessment (DG-1..3 silent custom
   metrics) are tracked red in C13 until the producers ship — the report
   refuses to claim coverage that telemetry can't back.
