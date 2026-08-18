# Deployment

The single authoritative description of how this platform reaches the Datadog
org. It is written from `.github/workflows/deploy.yml` — if the two ever
disagree, the workflow is right and this file has a bug.

## The promotion model

The **same** definitions move through every environment; nothing is copied or
edited between them. Each apply narrows the coverage stack's `environments`
variable to exactly one environment, and each environment has **its own state
file**, so promoting one environment can never rewrite another's resources.

| Trigger | What runs |
|---|---|
| Push to `main` | nonprod job only: apply **qa**, then **stage** (stage only if qa applied) |
| `workflow_dispatch`, target `nonprod` | same as a push |
| `workflow_dispatch`, target `production` | nonprod first (promotion order preserved), then the production job behind the `datadog-production` environment gate |

Production **never** deploys from a bare push. The `datadog-production` GitHub
environment carries the production secrets and, where configured, a reviewer
approval.

## The production job, step by step

1. **Foundation apply** (`stacks/foundation`, state `foundation/prod.tfstate`)
   — teams, on-call, notification rules, RBAC, dashboards, workflows, service
   catalog, downtimes. Foundation goes first because an alert that fires into
   a routing void is worse than no alert.
2. **Runbook publish** (`tools/publish_runbooks.py`) — the one API-deployed
   component (the provider has no notebook resource; ADR-006). Content-hash
   drift control makes it a no-op when nothing changed.
3. **Coverage apply** (`stacks/coverage`, state `coverage/prod.tfstate`) —
   monitors, SLOs, burn-rate alerts, composites for `prod`.
4. **Idempotency gate** — a second plan of both stacks must be empty.
5. **Coverage & compliance report** — `coverage_report.py --live --gate deploy`
   blocks on platform-integrity findings only (coverage gaps, contract
   violations on managed monitors/SLOs, live SLO errors). Estate-hygiene
   findings stay in the report and are chased by the nightly governance run,
   which opens issues — a deploy must not go permanently red over a tag on a
   resource the platform does not own.
6. **Quality scorecard** — fleet score ≥ 85, zero failing monitors.

Everything the run measured is uploaded as the `post-deploy-evidence`
artifact.

## State (ADR-016)

There is no backend block. State is **git-backed**: one file per
stack × environment (`foundation/prod.tfstate`,
`coverage/{qa,stage,prod}.tfstate`) on the orphan branch `tfstate` of this
repository, moved in and out by `tools/tfstate-git.sh` around every
credentialed plan or apply.

- **Locking** — every state-touching workflow (`deploy.yml`,
  `governance.yml`) shares the `concurrency: tfstate` group; no two runs
  overlap.
- **Versioning** — the branch's git history.
- **Persist-on-failure** — a failed apply still persists state, because a
  partial apply has already created real resources and losing the state that
  tracks them turns a red apply into an orphan fleet.
- **Never run `terraform apply` locally.** A local apply sees empty state and
  would duplicate the estate. `make plan-offline` is the local loop; real
  plans and applies happen only in the workflows.

## The governance loop (`governance.yml`)

- **Nightly drift** (06:00 UTC): `terraform plan -detailed-exitcode` per
  environment against restored state, plus runbook content-hash drift. Both a
  drift (exit 2) and a hard error (exit 1) are red, and a red run opens a
  governance issue.
- **Weekday coverage & quality** (07:00 UTC Mon–Fri): rebuild the inventory
  from the live org, reassign profiles, run `coverage_report.py --live` with
  the full governance gate (every finding blocks), and the scorecard. A red
  run opens a governance issue with the report attached.

## CI (`ci.yml`, every PR and push to main)

YAML syntax → JSON schema → the pytest suite (which asserts policy lint,
manifest validation, runbook completeness/registry sync, generated-doc
staleness, scorecard thresholds, governance checks and the 1.2M-resource
scale path) → `terraform fmt`/`validate` → offline plans (preconditions,
budgets) → plan determinism → Trivy + gitleaks → and, on non-fork PRs, a
credentialed plan whose JSON is fed to `tools/validate_live.py`, which
submits **every planned monitor** to Datadog's validation API and reports
defects grouped by cause.

## Operational notes

- The workflow catalog deploys under `workflow_budget`
  (`stacks/foundation/budget.auto.tfvars`): the org's workflow-count quota is
  mostly consumed by legacy workflows owned by another login that CI
  credentials cannot delete (per-resource ownership — the API returns 403).
  Delete them in the Datadog UI as their owner, then raise the budget; the
  priority list in `stacks/foundation/main.tf` controls what deploys first.
- `publish_runbooks.py --write-registry` (run locally with credentials)
  records published notebook IDs back into `platform/policy/runbooks.yaml`;
  commit the result.
- Remaining live-estate retirement work is tracked in
  [migration-strategy.md](migration-strategy.md).
