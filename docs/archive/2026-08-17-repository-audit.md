> **ARCHIVED SNAPSHOT (2026-08-17).** A point-in-time audit written before
> the first deployment; its blocker rows are resolved and its explanatory
> sections were superseded by the maintained docs
> ([reference-architecture](../reference-architecture.md),
> [implementation-guide](../implementation-guide.md),
> [deployment](../deployment.md), [decision-records](../decision-records.md)).
> Kept as dated evidence of what was verified and found at the time.

# Repository Audit — How the Platform Works, What Was Verified, and How It Deploys

Audit date **2026-08-17**, on branch `claude/datadog-observability-platform-nbhn52`.
Everything below was verified by running it, not by reading it. Section 2 is the
audit trail; section 3 is the deployment runbook.

---

## 1. How the repository works, end to end

The repository turns **reviewed YAML into a complete Datadog installation**.
No monitoring decision lives in Terraform, no Terraform lives in team hands,
and no object is created that a policy file cannot explain.

```
 platform/policy/*.yaml          the decisions   (WHAT to monitor, WHO owns it,
 platform/services/*.yaml        the estate       HOW LOUD each env is)
 platform/monitors/*.yaml        the exceptions
        │
        │  validated by tools/validate_policy.py (12 rule families),
        │  validate_monitors.py, JSON Schemas in platform/schemas/
        ▼
 stacks/coverage + stacks/foundation      pure interpreters: read YAML,
        │                                 expand archetypes × environments ×
        │                                 bands into concrete resources
        ▼
 10 modules/ (monitor_factory, slo_with_burn, rbac, team_oncall,
              notification_rules, workflow_automation, dashboard, …)
        ▼
 Datadog org        (+ runbook notebooks via tools/publish_runbooks.py,
                     the one API-published component — ADR-006)
```

### 1a. The configuration hierarchy

Eight layers, most specific wins, all PR-reviewed YAML under `platform/policy/`:

```
global.yaml → domains.yaml → service_archetypes.yaml → profiles.yaml
  → environments.yaml → tiers.yaml → teams.yaml → exceptions.yaml
```

This implements the required
`global → resource profile → environment → criticality → owner → approved exception`
inheritance. A monitor's final shape (thresholds, priority, routing, paging)
is derived by walking these layers; nothing is copied between environments.

### 1b. The scaling model

`archetypes/*.yaml` holds 151 monitor definitions across 14 domains (api,
application, kubernetes, vmware, cloud/Azure, database, data, messaging,
network, infrastructure, integration, security, saas, platform). Each
archetype × environment × alert band becomes ONE grouped multi-alert monitor
whose query selects by tag (`env`, `alert_band`, `service_archetype`) and
groups `by {service}`. Resources are *groups inside monitors*, so:

* 419 archetype instances + 46 SLO burn monitors + 7 composites + 4
  self-service = **476 monitors + 23 SLOs = 499 objects** for a
  100,000-service estate (verified by plan, below);
* a new service is covered the moment it carries five tags — zero new objects;
* the object count grows with monitoring *decisions*, never with *resources*.

### 1c. The two developer interfaces

* **Onboard a service**: one file in `platform/services/` matching
  `schemas/service.schema.json` (or nothing at all — discovery via
  `tools/build_inventory.py` + `profile_engine.py` assigns profiles from
  existing tags/metadata automatically; registration only adds ownership
  intent).
* **Approved custom monitor**: one file in `platform/monitors/` matching
  `schemas/monitor.schema.json`, rejected by CI unless fully compliant
  (routing, runbook, rationale, no duplicate of an archetype).

### 1d. The two stacks

* **foundation** (178 resources): teams, on-call schedules, 118 tag-driven
  notification rules (Teams / ServiceNow / On-Call routing — no destination
  ever appears in a monitor), 27 workflow automations (incl. ServiceNow
  incident creation), 18 dashboards, RBAC roles/service accounts, service
  catalog entries, downtimes. Applied first: routing must exist before
  anything can alert into it.
* **coverage** (499 objects): all monitors, SLOs, burn-rate alerts,
  composites. Guarded by plan-time preconditions (budget: ≤1500 monitors,
  ≤90 paging, ≤70 P1; cardinality; naming; runbook links).

### 1e. State, promotion, and CI (ADR-016)

* **State** is git-backed on the orphan `tfstate` branch of this repository —
  one file per stack × environment (`coverage/{qa,stage,prod}.tfstate`,
  `foundation/prod.tfstate`), moved by `tools/tfstate-git.sh` (plumbing only,
  fast-forward pushes, rebuild-and-retry on races). Locking = the shared
  `concurrency: tfstate` group across deploy and governance workflows;
  versioning/recovery = the branch's git history; no cloud storage account
  and no extra secrets.
* **Promotion** (`deploy.yml`): the SAME commit is applied env by env —
  qa (19 resources) → stage (120) → *manual approval* → prod (360, which
  also owns the env-agnostic SLOs + burn monitors). dev deploys nothing by
  policy (`environments.yaml: alerting: false`), which is itself the dev
  alert policy. Per-env state files make it structurally impossible for one
  environment's apply to plan a destroy against another's resources
  (verified by exact partition, below).
* **CI** (`ci.yml`, 23 stages): YAML → schema → policy lint → manifests →
  runbook completeness → generated-docs freshness → scorecard → 85 tests →
  fmt → validate → offline plan (all preconditions) → determinism (second
  plan identical) → estate report on the PR → tfsec + gitleaks → and, with
  secrets, a credentialed plan that has Datadog itself validate every
  monitor (ADR-015 — this caught 6 defect classes nothing else caught).
* **Governance** (`governance.yml`): nightly drift (click-ops detection per
  environment + runbook hash drift), weekday coverage & quality runs that
  rebuild the inventory, re-measure coverage against the live org, and open
  a governance issue when red. Coverage check C9 makes click-ops monitors
  themselves a finding.

### 1f. Coverage measurement

`tools/coverage_report.py --live` measures **declared scope** (every service
registration and inventory entry must resolve to a profile with every
required signal instantiated) and **discovered scope** (every live resource
seen by the inventory must map into a monitored group), and fails below
100% on 15 runtime checks. That is the "measurable 100% coverage" claim,
and the governance schedule is what keeps it true between deploys.

---

## 2. Audit trail — what was checked and what was found

### 2a. Verified green (executed this audit)

| Check | Result |
|---|---|
| `validate_policy.py` (12 rule families) | 0 violations |
| `validate_monitors.py` | 3/3 manifests pass |
| `publish_runbooks.py --dry-run` | 152 runbooks valid |
| `generate_matrix.py --check` / `generate_runbooks.py --check` | generated docs current (419 rows / 151 in sync) |
| `monitor_scorecard.py` | fleet 96.5 — grade A, 0 failing |
| `pytest tests/` | **85/85** (incl. the 1.2M-resource scale test) |
| `terraform fmt` / `validate` | clean — 10 modules, 2 stacks |
| Offline plan, coverage | 499 to add, 0 destroy; all preconditions pass |
| Offline plan, foundation | 178 to add, 0 destroy |
| **Per-env plans partition exactly** | qa 19 + stage 120 + prod 360 = combined 499, pairwise overlap **0** |
| `tfstate-git.sh` end-to-end (local remote) | bootstrap, round-trip, no-op detection, per-env and per-stack isolation, clean working tree |
| Live org reachability (read-only) | verified via API; estate enumerated (below) |

### 2b. Live org findings (see live-estate-reconciliation.md for actions)

* **0 monitors** exist — the platform has never been applied; nothing to import.
* **1 orphaned SLO** (`eb41f0e7…`, backing monitor deleted, permanently
  `no_data`) — retire with export at M0.
* **62 legacy runbook notebooks** from the 2026-08-07 experiment — 4 adopted
  by name at first publish, 58 reported stale for checklist retirement.
* **5 legacy hand-built dashboards** — left untouched until platform
  dashboards are live, then retired with export.

### 2c. Defects found by this audit, fixed in this branch

1. **Notebook duplication on first publish** — the publisher matched only by
   registry id (all 152 unrecorded), so first publish would have created
   duplicates of 4 same-named legacy notebooks. *Fixed*: adopt-by-exact-name
   (newest wins), stale reporting (never deletes), `--write-registry` to
   record ids back into `runbooks.yaml` without disturbing comments.
2. **Cross-environment destroy in the promotion pipeline** — the previous
   deploy workflow pointed nonprod and prod applies at a shared state key
   (and both stacks at the *same* key), so a nonprod apply with
   `environments=["qa","stage"]` would have planned the destruction of every
   prod monitor. *Fixed* by per-environment state files (ADR-016) plus the
   exact-partition property in 2a.
3. **Env-agnostic objects duplicated under per-env applies** — SLOs, burn
   monitors, and custom monitors appeared in every environment's plan (73
   overlapping resources). *Fixed*: custom monitors filter on
   `var.environments`; SLOs/burns are owned by the prod apply.
4. **State backend unusable as wired** — the azurerm backend required Azure
   credentials no workflow supplied. *Replaced* by the git-backed state
   design (platform-owner direction: GitHub, not Azure), which also removed
   three would-be secrets.
5. **CI hard-down at the account level** — every GitHub Actions run
   (including a fresh dispatch during this audit) dies in <5 s with no
   runner, no logs. Not fixable from the repository; see blockers.

### 2d. Requirements coverage

GitHub as source of truth ✓ (config, policy, runbooks, state) · Terraform for
every supported surface ✓ (notebooks are API-published only because the
provider has no notebook resource — ADR-006, same guarantees) · one version
promoted dev→qa→stage→prod ✓ · Azure/VMware/DB/apps/data/pipelines/security/
Datadog-itself ✓ (14 archetype domains incl. `security.yaml`,
`platform.yaml` for Datadog self-monitoring: agent health, telemetry loss,
API rate limits, estate budget) · RBAC ✓ · On-Call ✓ · ServiceNow ✓ (notification
rules + workflow automation; org-level integration is a listed blocker) ·
SLOs ✓ · Notebook runbooks ✓ · notification rules ✓ · event correlation ✓
(`platform/events/correlation-rules.yaml` + `tools/correlate_events.py` +
grouping policy) · workflow automation ✓ · dashboards ✓ · coverage reporting ✓ ·
tens of thousands of services ✓ (bounded-object model + scale test) ·
one-YAML service onboarding ✓ · auto-onboarding from metadata ✓ (inventory →
profile engine) · one-YAML custom monitor ✓ · measurable 100% coverage ✓
(15 runtime checks, C1–C15).

---

## 3. Deployment — every step, in order

Steps 1–2 are the external blockers; everything after them is automated.

| # | Step | Who/where | Status |
|---|---|---|---|
| 1 | Restore GitHub Actions runner provisioning (billing/spending limit on the `droderiquesit` account). Proof: one green dispatch of `governance.yml`. | account owner | **BLOCKED — external** |
| 2 | Create GitHub environments `datadog-plan`, `datadog-nonprod`, `datadog-production` (approval gate on the last) and set `DD_API_KEY`/`DD_APP_KEY` in each (service account `svc-observability-terraform`; scopes in live-estate-reconciliation.md §3). Configure the ServiceNow integration in the Datadog org. | org admin | **BLOCKED — credentials** |
| 3 | M0 export: archive orphaned-SLO + 5 legacy dashboard JSON; delete the orphaned SLO. | operator, once | ready (documented) |
| 4 | Merge this branch to `main` → `ci.yml` runs all 23 stages incl. credentialed live monitor validation. | PR review | ready — all stages pass locally |
| 5 | `deploy.yml` nonprod: apply **qa** (19), then **stage** (120), each to its own state file on `tfstate` (branch auto-created on first persist). | automatic on merge | ready — plans verified |
| 6 | Approve `datadog-production` → foundation apply (178: teams, routing, on-call, RBAC, workflows, dashboards) → runbook publish (148 create + 4 adopt; then `publish_runbooks.py --write-registry`, commit ids, retire 58 stale) → coverage **prod** apply (360 incl. 23 SLOs + 46 burn monitors). | approver + automation | ready |
| 7 | Post-deploy gates (same workflow): empty second plan; `build_inventory --live` → `profile_engine` → `coverage_report --live --gate deploy` at 100% (platform-integrity checks block; estate-hygiene findings are reported and chased by the nightly governance gate). | automatic | ready |
| 8 | Steady state: nightly drift + weekday coverage/quality runs open governance issues on red; retire the 5 legacy dashboards once platform dashboards are reviewed. | governance schedule | ready |
