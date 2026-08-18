> **ARCHIVED SNAPSHOT (2026-08-17).** This described the live org BEFORE the
> first deployment. Its central claims — no runners, no credentials, nothing
> deployed — were all resolved on 2026-08-18 by deploy run #24 (green end to
> end). Kept as dated evidence; current deployment truth lives in
> [docs/deployment.md](../deployment.md), and the remaining retirement work
> in [docs/migration-strategy.md](../migration-strategy.md).

# Live Estate Reconciliation & Deployment Readiness

Snapshot taken **2026-08-17** (read-only, via the Datadog API). This is the
record of everything that already exists in the live org, what the first
deployment will do about each item, and exactly what access is still missing
before that deployment can run. Nothing here is destroyed silently: every
pre-existing object is either **adopted**, **left alone**, or **retired
through the migration checklist** with an export first.

---

## 1. What exists in the org today

| Object class | Count | Provenance | State |
|---|---|---|---|
| Monitors | **0** | — | The org has no monitors at all. Every monitor the platform plans is a create; there is nothing to import and no click-ops estate to migrate. |
| SLOs | **1** | Earlier experiment (2026-08-03, author `dd-ai-start`) | **Orphaned and permanently broken** — see below |
| Runbook notebooks | **62** | Earlier experiment (2026-08-07, author `dd-ai-start`) | Published, healthy, but from a superseded catalog |
| Custom dashboards | **5** | Hand-built | Working; overlap with the platform's dashboards in intent, not in definition |
| Preset/integration dashboards | ~17 | Datadog | Out of scope — not managed, not counted |

### 1a. The orphaned SLO — retire (M0)

* **Name**: `Network platform availability`
* **ID**: `eb41f0e7654d51278b49c811eb7771db`
* **Why broken**: monitor-type SLO whose single backing monitor (`311841473`)
  was deleted. Status is `no_data` with `calculation_error: monitor not found`
  and can never recover.
* **Why not import**: it carries the *old* naming scheme
  (`slo_id:slo-infra-network-availability`); the current catalog defines
  `slo-network-availability` with different objectives and a metric-based
  spec. There is nothing functional to preserve.
* **Action**: export its JSON to the M0 archive, then delete it in the same
  change window as the first foundation apply. Until then it is left alone.

### 1b. Legacy runbook notebooks — adopt 4, retire 58

The 62 notebooks use the same `Runbook: <Title>` convention the publisher
uses. Four titles collide exactly with the current registry
(`Cloud Cost Anomaly`, `Deployment Regression`, `Host Unavailable`,
`Storage Latency Anomaly`).

`tools/publish_runbooks.py` now **adopts by exact name**: when a registry
entry has no recorded id but a same-name runbook notebook exists, the newest
one is updated in place instead of creating a duplicate; every other
runbook-type notebook the registry does not claim is printed as a stale
retirement candidate and **never deleted by the tool**. Run with
`--write-registry` after the first publish to record the created/adopted ids
in `platform/policy/runbooks.yaml` (comment-preserving in-place edit), and
commit that diff.

Retirement of the 58 unclaimed notebooks is a migration-checklist step (M4):
archive the list the publisher prints, confirm no monitor message links to
them (none can — there are no monitors), then delete manually.

### 1c. Legacy dashboards — leave until platform dashboards are live, then retire

`Executive Overview — Enterprise Health` (`xup-wsr-8ue`),
`Platform Governance` (`dcp-2fy-hfk`), `Operations & Reliability`
(`5d8-asy-and`), `Service & Application Health` (`9qz-g69-edm`),
`Infrastructure & Cloud Health` (`n34-sqv-qix`).

These are unmanaged and stay untouched through the first apply. Once the
foundation stack's dashboards are live and reviewed, retire these five via
the migration checklist (export JSON to the M0 archive first). They are not
imported because the platform dashboards are generated from the catalog and
would fight hand-edits forever.

---

## 2. Validation status of the platform itself

Everything CI checks passes locally as of this snapshot, on toolchain
versions matching CI (Terraform 1.9.8, Python 3.11):

* policy lint: 0 violations · manifests: 3/3 · matrix: 419 rows current ·
  runbooks: 152 registered, 151 archetype + SLO-burn in sync
* scorecard: fleet 96.5 (A), 0 failing · tests: **85/85**
* `terraform fmt`/`validate`: clean across 10 modules + 2 stacks
* offline plans: coverage **499 resources** (476 monitors + 23 SLOs),
  foundation **178 resources**; all preconditions and budget gates green
* previous live read-only validation: 423/423 monitors accepted by
  `POST /api/v1/monitor/validate` (see live-validation-evidence.md)

---

## 3. Why nothing is deployed yet — the exact blockers

The platform has never been applied. Two independent blockers, both outside
this repository:

### Blocker A — GitHub Actions cannot provision runners (hard, blocks everything)

Every workflow run on this repository fails in under 5 seconds with no
runner assigned (`runner_id: 0`), no step executed, and no logs retained
(HTTP 404). Verified three ways: the CI and deploy runs triggered by the
PR #1 merge, and a fresh `workflow_dispatch` of `governance.yml` on
2026-08-17 (run 32070451703) — identical instant failure. The workflow
content is not the cause: every stage of those same workflows passes locally.

**Fix (account owner)**: resolve GitHub Actions billing / spending limit for
the `droderiquesit` account (Settings → Billing → Spending limits → Actions),
or attach the repo to a plan/org with Actions minutes for private repos.
One green `workflow_dispatch` of `governance.yml` proves it.

### Blocker B — deployment credentials (needed the moment runners work)

| Secret | Where | Purpose |
|---|---|---|
| `DD_API_KEY` / `DD_APP_KEY` | GitHub environments `datadog-plan` (read/validate), `datadog-nonprod`, `datadog-production` | Terraform Datadog provider + runbook publisher. Service account `svc-observability-terraform`; never personal keys. App key scopes: `monitors_read/write`, `slos_read/write`, `dashboards_read/write`, `notebooks_read/write`, `teams_read/write`, `on_call_read/write`, `workflows_read/write`, plus `user_access_read/write` only in `datadog-production` (RBAC). |
| GitHub environments | Repo settings | `datadog-plan`, `datadog-nonprod`, `datadog-production` — the last with a required-reviewer approval gate (the prod promotion gate the deploy workflow depends on). |

State needs **no external service and no extra secrets**: it is git-backed on
the `tfstate` branch of this repository (ADR-016), pushed by the workflow's
own `GITHUB_TOKEN` (`contents: write`). If branch protection is enabled,
exclude the `tfstate` branch from required reviews.
| ServiceNow | Datadog org | The ServiceNow integration (instance URL + service account) configured in the org so `snow_record:*` routing in notification rules creates incidents. Not expressible in Terraform's provider; one-time org setting. |

### Not blockers

* Datadog org access itself (read access verified live).
* Repository content — no known red checks remain.

---

## 4. First-deployment order of operations

Once A and B clear, the deploy workflow does this on its own
(`workflow_dispatch` → `production` after `nonprod`), in this order:

1. **M0 export** (manual, once): archive the orphaned SLO JSON and the five
   legacy dashboards' JSON; delete the orphaned SLO.
2. **qa apply (19 resources), then stage apply (120)** (`nonprod` job) — one
   environment per apply, each with its own state file on the `tfstate`
   branch. The first persist auto-creates the branch. Per-env plans
   partition the combined 499-object estate exactly (verified offline:
   19 + 120 + 360, pairwise overlap 0).
3. **prod approval gate**, then in the `production` job:
   **foundation apply** first (teams, routing, on-call, workflows, RBAC,
   dashboards — 178 resources; routing must exist before anything can alert
   into it), **runbook publish** (creates 148, adopts 4 by name — then run
   `publish_runbooks.py --write-registry` locally and commit the recorded
   ids; retire the 58 stale notebooks per §1b), and **coverage prod apply**
   (monitors, SLOs, burn-rate alerts, composites).
4. **Post-deploy gates** (already in the workflow): second plan must be
   empty; `build_inventory --live` → `profile_engine` → `coverage_report
   --live` must be green; scorecard ≥ 85.
