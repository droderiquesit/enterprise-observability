# Implementation Guide

> Sections 20–27 of the deliverable set. Architecture is in
> [`reference-architecture.md`](reference-architecture.md).

---

## 20. YAML Schema — the single-file developer interface

### The complete custom-monitor schema

```yaml
monitor:
  # --- required ---------------------------------------------------------------
  name: checkout-payment-latency     # kebab-case, MUST match the filename
  archetype: api-latency-p99         # a catalog archetype id, or `custom`
  service: checkout-api              # must be registered in platform/services/
  team: payments                     # must own that service
  env: [stage, prod]                 # dev is rejected: it does not alert
  slo: slo-api-latency               # must exist in the SLO catalog
  runbook: api-latency-p99           # must exist in the runbook registry
  workflow: diag-api-health          # must exist in the workflow registry

  # --- optional: the platform derives these if omitted -------------------------
  priority: P2                       # derived from impact_class × band otherwise
  thresholds:
    warning: auto                    # `auto` = inherit the archetype's tuned value
    critical: auto
  predictive:
    anomaly: true                    # selects the archetype's predictive variant
    forecast: false
  notification_profile: production_critical
  group_by: []                       # ≤3 keys; identity keys rejected
  summary: "..."                     # one sentence for the alert body
  impact: "..."                      # business impact statement
  justification: >                   # REQUIRED when re-using a catalog archetype,
    ...                              # or for any fixed threshold on a behavioural signal

  # --- only for `archetype: custom` --------------------------------------------
  domain: api
  monitor_type: query alert
  detection: anomaly
  impact_class: customer_impact
  resource_type: service
  query: "..."                       # must be scoped to env AND service
```

JSON Schema: [`platform/schemas/monitor.schema.json`](../platform/schemas/monitor.schema.json).
Service registration schema: [`platform/schemas/service.schema.json`](../platform/schemas/service.schema.json).

### What the platform derives, so teams never write it

| Derived | From |
|---|---|
| Monitor name (`[P2][prod][api] … `) | naming policy |
| All 12 required tags + 13 governance tags | factory |
| Priority | impact_class × alert_band, clamped by environment |
| Paging behaviour | the paging rule — never settable by a team |
| Teams channel, ServiceNow group, on-call target | tag-based notification rules |
| Message body (all 11 required answers) | message contract |
| Recovery, warning and no-data sections | message contract |
| Evaluation delay, new-group delay, renotify | monitor defaults × tier |
| `correlation_key`, `dedup_key` | failure domain + service + env |
| Runbook deep link | runbook registry |

### `thresholds: auto` and the one thing it cannot do

`auto` inherits the archetype's tuned value. If the archetype does not define
that threshold (an anomaly archetype has no `warning`), the key is **dropped**
rather than invented — a made-up warning threshold is worse than none.

A **numeric override on an inherited archetype is rejected.** Datadog requires
a monitor's thresholds to match the numeric literal inside its query, so "same
query, different number" cannot exist. The validator says so and points at the
two legitimate options: propose an archetype change (everyone benefits), or use
`archetype: custom` with an explicit query (only you carry it).

### `predictive:` expresses intent, not implementation

`predictive: {anomaly: true}` selects the catalog's declared *predictive
variant* of the archetype — for `api-latency-p99` that is `api-latency-seasonal`
(robust/weekly). The team says *"learn my shape instead of reacting to it"*; the
platform picks the technique. If the archetype declares no variant, the manifest
is rejected rather than silently mislabelled.

---

## 21. Terraform Module Architecture

```
modules/
  monitor_factory/       renders every alerting monitor from a resolved instance
  composite_monitor/     confirmed-impact composites, with member demotion
  slo/                   SLOs (domain + tier0) and their IDs
  notification_rules/    tag → destination routing matrix
  team_oncall/           Teams, schedules, escalation policies, routing rules
  workflow_automation/   workflows, classified and guarded by blast radius
  rbac/                  roles and service accounts, resolved by permission NAME
  service_catalog/       service definitions (v2.2) from the registry + inventory
  downtime/              recurring, tag-scoped maintenance windows

(Dashboards are a single resource declared directly in
stacks/foundation/dashboards.tf — a module added nothing.)

stacks/
  foundation/            applied FIRST — everything an alert needs to reach a human
  coverage/              monitors, SLOs, burn alerts, composites, self-service
```

### The factory is the contract

`modules/monitor_factory` makes **no policy decisions**. It receives a
fully-resolved instance and enforces the contract:

```hcl
lifecycle {
  precondition { ... }   # ≤3 group keys
  precondition { ... }   # no banned identity keys
  precondition { ... }   # slo_id + runbook + workflow + team all present
  precondition { ... }   # impact statement + next action present
  precondition { ... }   # only production may page
  precondition { ... }   # only P1/P2 may page
  precondition { ... }   # no org-wide wildcard query
}
```

Plus `variable "instances"` validations for priority, impact class, monitor
type, environment, band, and the `env != "dev"` invariant. **A non-compliant
monitor cannot be planned**, let alone applied.

### Dependency order is deliberate and acyclic

```
coverage_monitors ──► monitor IDs ──► slos ──► SLO IDs ──► burn_monitors
        └──────────► monitor IDs ──► composites
```

Monitor-type SLOs rebuild their membership from the *prod critical* instances of
their declared `member_archetypes`, so an SLO can never end up pointing at
monitors that no longer exist — the failure that broke four SLOs in the previous
generation of this org.

### Plan-time budget assertions

```hcl
check "monitor_budget"   { ... 474 ≤ 1500 ... }
check "paging_budget"    { ... 67 ≤ 90 ...   }   # the burnout metric
check "p1_budget"        { ... 66 ≤ 70 ...   }
check "composite_members_resolved" { ... }
```

Growth in any of these is a reviewed decision in `global.yaml`, never a drift.

### State is git-backed — no backend block anywhere (ADR-016)

Terraform always runs on the default local backend. Around every credentialed
plan/apply, `tools/tfstate-git.sh` restores/persists the stack's state from the
orphan branch `tfstate` of this repository — one file per stack × environment
(`coverage/{qa,stage,prod}.tfstate`, `foundation/prod.tfstate`). Locking is the
`concurrency: tfstate` group shared by the deploy and governance workflows;
versioning and recovery are the branch's git history; per-environment files
mean promotion can never plan a destroy against another environment. Offline
CI stages run with no state and no secrets at all.

---

## 22. Repository Structure

```
platform/                         ← everything a human edits
  policy/
    global.yaml                   tag contract, defaults, cardinality + paging budgets
    domains.yaml                  14 technology domains
    service_archetypes.yaml       service archetypes → packs → archetypes
    profiles.yaml                 5 monitoring profiles + 2 overlays
    environments.yaml             dev / qa / stage / prod policy
    tiers.yaml                    tier0–tier3, SLO scope, escalation
    priorities.yaml               P1–P4 matrix + the paging rule
    teams.yaml                    channels, ServiceNow groups, escalation
    notification_profiles.yaml    6 routing profiles
    grouping.yaml                 grouping, collapse, dedup, storm limits
    composites.yaml               confirmed-impact patterns
    slos.yaml                     21 domain SLOs + tier0 template
    runbooks.yaml                 152-entry registry
    workflows.yaml                27 workflows, classified by blast radius
    exceptions.yaml               time-boxed, owned, approved deviations
    archetypes/*.yaml             151 monitor definitions across 14 domains
  services/*.yaml                 service registrations (the golden path, step 1)
  monitors/*.yaml                 self-service monitors — ONE FILE each
  runbooks/*.md                   152 runbooks (generated frame + human sections)
  events/correlation-rules.yaml   correlation policy
  schemas/*.json                  JSON Schema for the two hand-written formats

modules/                          reusable Terraform (9)
stacks/                           foundation, coverage
tools/                            the Python/shell tooling (see §24)
tests/                            pytest suite including a 1.2M-resource scale test
docs/                             this documentation + the GENERATED matrix + archive/
.github/workflows/                ci · deploy · governance
```

### Mapping to the structure you proposed

| Your layout | Here | Why |
|---|---|---|
| `terraform/modules/` | `modules/` | Same thing; the repo is Terraform-rooted |
| `config/services/` | `platform/services/` | |
| `config/monitor_profiles/` | `platform/policy/profiles.yaml` | One file beats one file per profile at five profiles |
| `config/monitors/` | `platform/monitors/` | |
| `config/teams,environments,tiers/` | `platform/policy/*.yaml` | |
| `policies/monitor_policy/` | `platform/policy/` + `tools/validate_policy.py` | Policy is data; the linter is its executable form |
| `policies/tagging_policy/` | `platform/policy/global.yaml` | The tag contract lives with the standards it serves |

---

## 23. CI/CD Pipeline

`.github/workflows/ci.yml` — four jobs, every stage a guardrail. The
per-tool checks (policy lint, manifests, runbook registry sync, generated-doc
staleness, scorecard thresholds) are asserted INSIDE the pytest suite, so they
run once, not twice:

| Job | Stage | Fails when |
|---|---|---|
| validate | YAML syntax | any policy file is unparseable |
| validate | JSON schema | a manifest or registration violates its schema |
| validate | pytest | policy lint (12 rule families), self-service manifests incl. duplicate detection, runbook completeness & registry sync, generated-doc staleness, scorecard (fleet ≥ 85, zero F), governance checks, the 1.2M-resource scale path |
| terraform | `terraform fmt -check` / `validate` | 9 modules + 2 stacks |
| terraform | Offline plan | any precondition, budget or cardinality gate |
| terraform | **Determinism** | two consecutive plans differ |
| terraform | Estate report → PR summary | (informational) |
| security | Trivy | HIGH/CRITICAL IaC misconfiguration |
| security | gitleaks | a secret in the diff |
| credentialed-plan | plan + `validate_live.py` | any planned monitor is rejected by Datadog's validation API (non-fork PRs) |

`deploy.yml` — controlled promotion. The **same definitions** move:

```
push to main ──► qa + stage        (datadog-nonprod, automatic)

dispatch target=production ──► qa + stage, then prod
    (datadog-production — explicit dispatch + approval, concurrency-locked)
     ↓
foundation → runbooks → coverage → idempotency → coverage report (--gate deploy) → scorecard
```

Full detail: [deployment.md](deployment.md).

`governance.yml` — nightly drift (Terraform + runbook hash), weekday coverage
and quality runs, and it **opens a governance issue** when the report is red.

---

## 24. Policy-as-Code Validation

All tools read the same policy files Terraform reads — there is no second
source of truth. Shared helpers (policy loading, priority/paging resolution,
tag parsing, the rate-limit-aware `dd_request`) live in `obs_common.py`.

| Tool | Role |
|---|---|
| `validate_policy.py` | 12 rule families over the whole catalog |
| `validate_monitors.py` | self-service manifests, with explanations |
| `validate_live.py` | submits every planned monitor to Datadog's validation API concurrently, grouped by cause |
| `build_inventory.py` | authoritative inventory (live, or synthetic at 1.2M for scale tests) |
| `profile_engine.py` | owner, tier, profile, **alert band** — zero-touch onboarding |
| `coverage_report.py` | C1–C15 governance checks; `--gate governance` (nightly, blocks on everything) or `--gate deploy` (blocks on platform-integrity findings only — estate hygiene stays reported, chased by the nightly loop) |
| `monitor_scorecard.py` | quality score per monitor, team and domain |
| `generate_matrix.py` | the coverage matrix (generated, CI-checked for staleness) |
| `generate_runbooks.py` | 151 runbook drafts from the catalog, human sections preserved |
| `publish_runbooks.py` | notebook publishing with content-hash drift control |
| `correlate_events.py` | executable specification of the correlation rules |
| `refresh_fixtures.py` | regenerates `tests/fixtures/monitors_planned.json` from an offline plan (`make fixtures`) |
| `tfstate-git.sh` | moves per-stack×env state to/from the `tfstate` branch (ADR-016) |

### Guardrails, and where each is enforced

| Guardrail | Merge | Plan | Runtime |
|---|---|---|---|
| Duplicate monitors | `validate_monitors.py` | — | C8 |
| Conflicting / overlapping queries | policy lint | — | C8 |
| Monitor explosion | BUDGET | `check "monitor_budget"` | — |
| Excessive cardinality | CARDINALITY | precondition | C11 |
| Unnecessary paging | PRIORITY | precondition + `check "paging_budget"` | C14 |
| Missing ownership | REFERENCE | precondition | C2 |
| Missing SLO | REFERENCE | precondition | C4 |
| Missing runbook | REFERENCE | precondition | C5 |
| Missing notification policy | scorecard | — | C7 |
| Hardcoded routes | *impossible* — the schema has no field for one | | |
| Wildcard queries | SCOPE | precondition | — |
| No actionable response | scorecard | precondition | C15 |
| Expired exceptions | EXCEPTION | — | C12 + runtime archetype |
| Unmanaged (click-ops) monitors | — | — | C9 + runtime archetype |

---

## 25. Example Monitor Definitions

Three committed examples, each teaching something different:

**1. Re-using a catalog archetype with a predictive variant**
([`checkout-payment-latency.yaml`](../platform/monitors/checkout-payment-latency.yaml))
— the exact shape from the brief. Requires a `justification` because the pack
already covers this service; the justification explains that checkout's weekly
traffic shape makes rate-of-change noisy and seasonal anomaly correct **for this
service only**.

**2. A contractual threshold that the catalog cannot express**
([`settlement-partner-file-sla.yaml`](../platform/monitors/settlement-partner-file-sla.yaml))
— `archetype: custom`, because Datadog couples query and threshold and the
platform refuses to rewrite a query behind your back.

**3. A business-outcome signal with no archetype**
([`checkout-payment-authorization-rate.yaml`](../platform/monitors/checkout-payment-authorization-rate.yaml))
— payment decline ratio. Invisible to availability monitoring: every request
succeeds with HTTP 200 while no money moves.

### What one file produces

```
$ terraform plan
+ [P2][prod][api] Checkout Payment Latency (critical)
    query    = avg(last_30m):anomalies(p95:trace.http.request.duration{
                 env:prod,service:checkout-api} by {service}, 'robust', 3,
                 direction='above', seasonality='weekly') >= 1
    priority = 2
    tags     = [ 25 governance tags, generated ]
    message  = [ all 11 contract answers, generated ]
```

---

## 26. Example Notification Policies

From [`notification_profiles.yaml`](../platform/policy/notification_profiles.yaml):

```yaml
production_critical:
  selected_when: "env == prod AND alert_band == critical"
  routes:
    P1: { page: true,  urgency: high, servicenow: incident_p1, teams: team_channel,
          extra_channels: [major_incident_channel, exec_channel], datadog_incident: "SEV-1" }
    P2: { page: true,  urgency: low,  servicenow: incident_p2, teams: team_channel,
          datadog_incident: "SEV-2" }
    P3: { page: false, servicenow: task_p3_when_sustained, teams: team_channel }
    P4: { page: false, servicenow: none, teams: low_noise_channel }
```

Which becomes, for `team:payments`:

```hcl
resource "datadog_monitor_notification_rule" "route-production_critical-P1-page-payments" {
  recipients = ["@teams-teams-payments-alerts",
                "@servicenow-acme-incident-p1",
                "@oncall-payments",
                "@teams-major-incident",
                "@teams-exec-bridge"]
  filter { tags = ["managed_by:terraform",
                   "notification_profile:production_critical",
                   "priority:p1", "pages:true", "team:payments"] }
}
```

Note `pages:true` in the filter. Priority alone does not decide whether a human
is woken, so the routing rule reads the paging decision directly — which is how
a P2 symptom and a P2 burn-rate alert reach different destinations from the same
priority.

---

## 27. Example Terraform

**The hierarchy merge** (`stacks/coverage/locals_instances.tf`) — the whole
framework in one expression:

```hcl
candidates = flatten([
  for aid, a in local.archetypes : [
    for env in var.environments : [
      for band in local.env_policy[env].bands_instantiated : {
        archetype = aid, env = env, band = band
      } if contains(a.bands, band)
    ] if contains(a.envs, env) && local.env_policy[env].alerting
  ]
])
```

**Scope construction** — why one monitor covers an unbounded fleet:

```hcl
scope_for = {
  for k, r in local.resolved : k => join(",", compact([
    "env:${r.env}", "alert_band:${r.band}",
    try(r.a.selector, "") != "" ? r.a.selector : "",
  ]))
}
query = replace(local.windowed_query[k], "__SCOPE__", local.scope_for[k])
```

**Priority resolution** — an environment can only ever be quieter:

```hcl
priority = local.rank_priority[max(
  local.priority_rank[local.prio.matrix[a.impact_class][band]],
  local.priority_rank[local.env_policy[env].priority_ceiling],
  local.priority_rank[lookup(local.priority_exceptions, "${aid}.${env}", "P1")],
)]
```

**The paging decision** — three conditions, all required:

```hcl
pages_for = {
  for k, r in local.resolved : k => (
    local.env_policy[r.env].paging_allowed
    && r.band == "critical"
    && local.resolved[k].priority == "P1"
  )
}
```

**Composite member demotion** — the mechanism that makes composites reduce noise:

```hcl
demoted_archetype_instances = {
  for k, inst in local.archetype_instances : k => (
    contains(local.demoted_instance_keys, k)
    ? merge(inst, { priority = "P4", pages = false, ... })
    : inst
  )
}
```
