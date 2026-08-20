# Azure DevOps deployment pipeline

`azure-pipelines.yml` deploys this platform to Datadog:

```
Validate ──▶ Nonprod (dev → qa → stage) ──▶ Production (approval-gated)
```

It is a port of `.github/workflows/{ci,deploy}.yml` with the same guarantees.
Templates live in `.azuredevops/templates/`.

| File | Responsibility |
|---|---|
| `azure-pipelines.yml` | Stages, promotion order, approvals, post-deploy verification |
| `templates/install-tools.yml` | Terraform (pinned, checksum-verified), Python, deps, jq, optional scanners |
| `templates/preflight.yml` | Credentials, repository shape, git write path — fails in seconds |
| `templates/tf-apply.yml` | One stack × one environment: restore state → plan → apply → persist state |

---

## One-time setup

### 1. Variable group

Create a variable group named **`datadog-observability`** (Pipelines →
Library). Back it with Azure Key Vault so rotation happens in one place.

| Variable | Value | Secret |
|---|---|---|
| `DD_API_KEY` | Datadog API key for the CI service account | **yes** |
| `DD_APP_KEY` | Datadog application key for the same service account | **yes** |

Use a least-privilege **service account**, never a personal key. The account
needs `monitors_write`, `slos_write`, `notebooks_write`, `workflows_write`,
`dashboards_write`, `monitors_downtime`, and `user_access_manage` only if
`manage_rbac` is left on for the foundation stack.

> Azure DevOps does **not** expose secret variables to scripts as environment
> variables automatically. Every step that needs them maps them explicitly in
> an `env:` block. This is already done throughout the pipeline — preserve it
> when adding steps, or `preflight` will fail with an explanatory message.

Grant the pipeline access: Library → the group → Pipeline permissions.

### 2. Environments

Create two environments (Pipelines → Environments):

| Environment | Checks to add |
|---|---|
| `datadog-nonprod` | **Exclusive Lock** |
| `datadog-production` | **Exclusive Lock** + **Approvals** (at least one reviewer) |

**The Exclusive Lock check is not optional.** Terraform state for this
platform lives on the `tfstate` branch of this repository (ADR-016), and
GitHub Actions serialises state access with `concurrency: tfstate`. Azure
DevOps has no equivalent pipeline-level setting — the Exclusive Lock check,
combined with the `lockBehavior: sequential` already set on both deploy
stages, is what stops two runs from writing state at once.

### 3. Repository write access

The deploy stages push state commits to the `tfstate` branch, so the build
identity needs write access.

- **Azure Repos:** grant `<Project> Build Service (<Org>)` the **Contribute**
  permission on the repository. Under Project Settings → Repositories →
  Security.
- **GitHub-hosted repository:** the GitHub service connection must have write
  scope on the repo. The pipeline already sets `persistCredentials: true` and
  `fetchDepth: 0` on every checkout that applies — both are required, and
  `preflight` fails with a specific message if either is missing.

### 4. Create the pipeline

Pipelines → New pipeline → your repo → *Existing Azure Pipelines YAML file* →
`/azure-pipelines.yml`.

---

## Running it

| What you want | How |
|---|---|
| Validate a PR | Automatic — the `pr:` trigger runs the Validate stage only |
| Deploy dev, qa, stage | Automatic on merge to `main` (`target` defaults to `nonprod`) |
| Deploy production | Run pipeline → set **Promotion target** = `production` → approve at the gate |
| Validate without deploying | Run pipeline → **Promotion target** = `validate-only` |

Production never deploys from a bare push. It requires an explicit manual run
with `target=production`, and it re-applies qa and stage first so promotion
order is preserved.

### Parameters

| Parameter | Default | Notes |
|---|---|---|
| `target` | `nonprod` | `validate-only` \| `nonprod` \| `production` |
| `runSecurityScan` | `true` | trivy (IaC misconfiguration) + gitleaks (secrets) |
| `commitRunbookRegistry` | `false` | See the warning below |
| `vmImage` | `ubuntu-latest` | Blank to use a self-hosted pool |
| `poolName` | *(empty)* | Used only when `vmImage` is blank |

> **`commitRunbookRegistry` defaults to `false` deliberately.** Publishing a
> runbook mints a notebook id that monitors attach to, and that id must be
> committed back or the nightly drift check (`publish_runbooks.py --check`)
> fails on every unrecorded entry. The GitHub Actions deploy workflow already
> does this write-back. Turn this on **only** after GitHub Actions stops
> deploying this repository — two pipelines committing the same file will
> race.

---

## What each stage does

### Validate

Runs offline, no credentials required (except the optional live-plan job):

- YAML syntax across `platform/`, and JSON-schema validation of entity
  registrations and monitor manifests.
- Three pytest suites — platform (392), MCP server (161), portal (54).
  Policy lint, manifest validation, runbook registry sync, generated-doc
  staleness and scorecard thresholds all run *inside* these.
- Agent configuration renders and is scanned for inlined secrets.
- `terraform fmt -check`, `terraform validate` across all 12 modules and both
  stacks, an offline plan of each stack, and a **determinism check** — two
  consecutive plans must be byte-identical, because a non-deterministic plan
  churns resources on every apply.
- trivy + gitleaks.
- **Live monitor validation:** every planned monitor is checked against
  Datadog's own validation API, so an invalid query cannot reach an apply.
  Skips with a warning when credentials are absent.

### Nonprod

Publishes runbooks, then applies `coverage` to **dev, qa, stage in sequence**,
each with its own state file. Emits a deployment marker for qa and stage
(dev instantiates zero monitors by policy, so there is no behaviour for a
version to correlate with).

### Production

1. **Foundation** — teams, routing, on-call, workflows, RBAC. First, because
   an alert that fires into a routing void is worse than no alert: it creates
   the appearance of coverage.
2. **Runbooks** — published before the coverage apply so every monitor can
   attach its notebook through the native `assets` field.
3. **Coverage** — monitors, SLOs, burn-rate alerts, composites.
4. **Idempotency** — a second plan must be empty (`-detailed-exitcode`).
5. **Coverage & compliance report** against the live org, gated on platform
   integrity.
6. **Quality scorecard** — fleet score ≥ 85, zero failing.
7. **Monitor reconciliation** against the live estate.
8. **Fleet compliance** — report-only by decision.
9. **Deployment marker** — last, and only on a green run.

Evidence from steps 5–8 is published as the `post-deploy-evidence` artifact.

---

## Design notes

**State is persisted even when apply fails.** A partial apply has already
created real Datadog objects; discarding the state that tracks them turns a
red build into an orphaned fleet that the next run tries to create again.
`tf-apply.yml` captures the exit code, persists state, *then* fails.

**Terraform is never taken from the agent image.** It is downloaded at the
pinned version and its SHA256 is verified against HashiCorp's published sums
before unzipping. A corrupted or substituted download fails the build instead
of planning with it.

**`terraform init` uses `-reconfigure` in the apply path.** A self-hosted
agent reuses its workspace, and a `.terraform/` left by an earlier run can
record a backend this repository no longer declares. Without `-reconfigure`
that fails on the *second* run only — and never on a hosted agent, which is
the worst kind of bug to chase.

**Caching.** The Terraform binary is cached by version and providers by the
version constraints in `versions.tf`. Provider lock files are not committed
(see `.gitignore`), so the constraints are the most stable available key. If
you want fully reproducible provider resolution, commit
`.terraform.lock.hcl` and key the cache on it instead.

---

## Troubleshooting

| Symptom | Cause |
|---|---|
| `DD_API_KEY is empty` at preflight | Variable group not linked, or the value not mapped into the step's `env:` block |
| `git cannot reach 'origin'` | Build identity lacks write access, or `persistCredentials: true` was removed |
| `this is a shallow clone` | `fetchDepth: 0` was removed from a checkout in a deploy stage |
| `Backend initialization required` | A stale `.terraform/` on a reused agent workspace — the apply path already passes `-reconfigure`; add it to any step you introduce |
| Two runs applied at once | The **Exclusive Lock** check is missing from the environment |
| Production stage does not appear | It is compiled in only when `target=production`; a bare push cannot deploy prod by design |
