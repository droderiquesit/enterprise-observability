# Enterprise Datadog Monitoring Framework

Inventory-driven, predictive-first, policy-as-data monitoring for **tens of
thousands of services and hundreds of thousands of resources** — delivered
through Terraform and a small set of Python tools, with a bounded number of
managed Datadog objects, deployed and governed entirely from this repository.

```
655 monitors cover a 100,000-service estate.
Adding 50,000 more services creates ZERO new Datadog objects.
74 of those 655 (11%) are permitted to wake a human.
Teams write 5 tags. For anything unique, they write one YAML file.
```

**Who this is for:** platform/SRE engineers who operate the framework (start
here, then [docs/deployment.md](docs/deployment.md)), service teams who just
want coverage ([docs/golden-path.md](docs/golden-path.md) — five tags, or one
YAML file), and reviewers who want the design rationale
([docs/reference-architecture.md](docs/reference-architecture.md),
[docs/decision-records.md](docs/decision-records.md)).

---

## The invariant

> **The number of managed Datadog objects grows with the number of monitoring
> DECISIONS, not the number of monitored RESOURCES.**

The naive model is `services × environments × signals` — 100,000 × 4 × 20 =
**~8,000,000 monitors**. This framework produces **655**, with the same
coverage, because resources are *groups* inside grouped multi-alert monitors,
selected by tag.

| | |
|---|---|
| Archetypes → instances | 261 → 655 (archetype × environment × alert band) |
| SLOs | 21 domain + one per tier0 service → 44 burn-rate monitors |
| Composites | 7 confirmed-impact patterns |
| Self-service | 4 (one YAML file each) |
| Monitors in **dev** | **0** — by policy, not by muting |
| Fixed thresholds with no written rationale | **0** (CI-enforced) |
| Monitors missing runbook / SLO / automation / routing | **0** (contract-enforced) |

(Estate counts are asserted by CI: the test fixtures are regenerated from the
actual plan — `make fixtures` — and plan-time `check` blocks budget them.)

---

## How it is designed

**Policy is data; Terraform interprets it.** Every monitoring decision lives in
`platform/policy/*.yaml`, reviewed in PRs. Terraform (`stacks/`, `modules/`)
and the Python tools (`tools/`) both read those files; neither is ever the
source of a rule the other re-implements.

**Resources are groups, not monitors.** A query scoped to
`{env:prod, alert_band:critical, service_archetype:api}` grouped
`by {service}` covers every API in production. A new service joins on its
first trace. That is the whole scalability argument.

**Priority is derived; paging is narrower still.**
`priority = clamp(matrix[impact_class][band], env ceiling)` — and paging
additionally requires production, the critical band, and either P1 or a source
with *confirmed* impact (an SLO burn-rate alert or a composite). A P2 symptom
raises an incident and a ticket and wakes nobody.

**Every standard is a command.** If a rule cannot be checked mechanically it
does not belong in the standard: twelve policy-lint rule families, plan-time
preconditions and budget `check`s, seventeen runtime coverage checks (C1–C17),
an eight-dimension quality score, and a CI stage that submits every planned
monitor to Datadog's own validation API.

---

## Repository map

| Location | Purpose | Add content here when |
|---|---|---|
| `platform/policy/` | The configuration hierarchy — every monitoring decision, as YAML | Changing what is monitored, how loud it is, who is told |
| `platform/policy/archetypes/` | The monitor catalog (261 definitions, 14 domains) | Adding/tuning a monitor *pattern* for everyone |
| `platform/services/` | Service registrations (golden path, step 1) | Registering a service — one file |
| `platform/monitors/` | Self-service monitors | A team needs one genuinely unique monitor — one file |
| `platform/runbooks/` | 152 runbooks (generated frame + human sections) | Filling in the human sections of a runbook |
| `platform/schemas/` | JSON Schema for the two hand-written formats | Only when the manifest format itself changes |
| `platform/events/` | Correlation policy | Changing how alerts group into incidents |
| `modules/` | Reusable Terraform (9 modules) | A genuinely reusable capability — not a one-resource wrapper |
| `stacks/foundation/` | Terraform: teams, on-call, routing, RBAC, dashboards, workflows | Changing org-level plumbing |
| `stacks/coverage/` | Terraform: monitors, SLOs, burn alerts, composites | Rarely — it interprets policy; change the YAML instead |
| `tools/` | Python/shell tooling: validate · discover · measure · generate · publish | Adding a check or a generator (shared helpers: `obs_common.py`) |
| `tests/` | Pytest suite incl. a 1.2M-resource scale test; plan-derived fixtures | Adding or changing checked behavior |
| `docs/` | Maintained docs + the **generated** coverage matrix + `archive/` (dated snapshots) | A subject that outgrows this README |
| `.github/workflows/` | `ci` (PR gate) · `deploy` (promotion) · `governance` (nightly/weekday loops) | Only when adding an approved automation path |

Generated output goes to `generated/` (gitignored) — never commit it. The two
exceptions, committed by design and staleness-gated in CI:
`docs/monitor-coverage-matrix.md` and `tests/fixtures/monitors_planned.json`.

---

## How a change ships

1. Edit YAML under `platform/` (or a module/stack if you really are changing
   the interpreter). Run `make validate`.
2. Open a PR. CI runs the full gate: YAML/schema, the pytest suite (policy
   lint, manifests, runbooks, generated-doc staleness, scorecard, scale),
   `terraform fmt`/`validate`, offline plans with every precondition and
   budget check, plan determinism, Trivy + gitleaks, and a credentialed plan
   whose monitors are validated by Datadog itself.
3. Merge to `main` → `deploy.yml` applies **qa**, then **stage**, automatically.
4. Production is an explicit `deploy.yml` dispatch with target `production`,
   behind the `datadog-production` approval environment. The run finishes with
   an idempotency gate, the live coverage report (`--gate deploy`) and the
   scorecard, and uploads everything as the `post-deploy-evidence` artifact.
5. Between deploys, `governance.yml` detects drift nightly and re-measures
   coverage/quality on weekday mornings; red runs open governance issues.

State is git-backed (ADR-016): per-stack×environment files on the orphan
`tfstate` branch, moved by `tools/tfstate-git.sh`, locked by the shared
`concurrency: tfstate` group. **Never `terraform apply` locally** — a local
apply sees empty state and would duplicate the estate. Details:
[docs/deployment.md](docs/deployment.md).

## Common tasks

```bash
make setup            # venv + terraform init (offline)
make validate         # the offline CI gate: fmt + pytest + terraform validate
make plan-offline     # full plan, no credentials — exercises every guardrail
make matrix           # regenerate docs/monitor-coverage-matrix.md
make runbooks         # regenerate runbook drafts from the catalog
make fixtures         # regenerate the plan-derived test fixture
make inventory coverage   # live inventory + coverage report (needs DD keys)
```

To **add**: a service → one file in `platform/services/` (see
[golden-path](docs/golden-path.md)); a custom monitor → one file in
`platform/monitors/`; a monitor pattern → `platform/policy/archetypes/`; a
team → `platform/policy/teams.yaml`; an SLO → `platform/policy/slos.yaml`; an
environment or band → `platform/policy/environments.yaml` +
`global.yaml` vocabulary (a real design change — read
[reference-architecture §4](docs/reference-architecture.md) first).

**Avoid:** hand-editing anything generated (the matrix, runbook frames,
fixtures — regenerate instead); per-service monitors ("just for now" is how
8M-monitor estates happen); local applies; committing secrets or state
(gitleaks and the gitignore both gate this); adding a Python rule that
duplicates policy YAML — read the YAML through `obs_common.load_policy()`.

---

## Documentation

| Document | Subject |
|---|---|
| [reference-architecture.md](docs/reference-architecture.md) | The full architecture: strategy, tiers, priorities, environments, routing, predictive detection, per-domain standards, SLOs, composites, correlation, RBAC (§1–§19, §30) |
| [implementation-guide.md](docs/implementation-guide.md) | Schemas, module architecture, repository structure, CI/CD, validation tooling, worked examples (§20–§27) |
| [deployment.md](docs/deployment.md) | **How the platform reaches the org** — promotion, state, gates, operational notes |
| [golden-path.md](docs/golden-path.md) | The developer view: what a team actually does |
| [operating-model.md](docs/operating-model.md) | Ownership, cadences, change-safety, escalation |
| [migration-strategy.md](docs/migration-strategy.md) | General migration playbook + what remains open in this org |
| [quality-scorecard.md](docs/quality-scorecard.md) | The 8-dimension monitor quality model |
| [tagging-standard.md](docs/tagging-standard.md) | The six tags a service owner applies, and how |
| [telemetry-gaps.md](docs/telemetry-gaps.md) | Every `acme.*` metric's emission contract |
| [decision-records.md](docs/decision-records.md) | ADR-001…ADR-018 |
| [monitor-coverage-matrix.md](docs/monitor-coverage-matrix.md) | **Generated** — every archetype instance, staleness-gated in CI |
| `docs/archive/` | Dated pre-deployment snapshots (evidence, superseded) |

**Deployment status:** first full promotion (qa → stage → prod) completed
green on 2026-08-18 — deploy run #24, with the evidence artifact attached to
the run. Current live numbers always come from the latest green deploy run
and the nightly governance issues, not from this file.
