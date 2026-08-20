# Architecture Decision Records

## ADR-001 — Policy-as-data; Terraform is a pure interpreter

**Decision.** All monitoring intent lives in `platform/policy/*.yaml`. Terraform
makes no monitoring decisions. Teams touch YAML only.

**Why.** At 100k services, per-team HCL becomes unreviewable sprawl. YAML policy
is diffable, lintable, and safe for people who do not write Terraform.

**Consequence.** The hierarchy merge is implemented once, in
`stacks/coverage/locals_*.tf`, and covered by the offline-plan and determinism
CI gates.

---

## ADR-002 — Grouped multi-alert monitors, never per-resource monitors

**Decision.** One monitor per (archetype × environment × alert band). Resources
are *groups*, selected by tag.

**Why.** Bounded object count: 476 monitors for a 100k-service estate against a
naive ~8,000,000. Instant coverage for new resources. A single point of tuning.

**Trade-off.** Per-resource thresholds are impossible by design. The sanctioned
escape hatch is one self-service YAML file, which is reviewed, attributed and
scored.

---

## ADR-003 — The alert band, not the tier, is what monitors select on

**Decision.** Monitoring profiles collapse into three selectable bands —
`critical`, `standard`, `baseline` — plus `none`. Queries filter on
`alert_band`.

**Why.** Priority and routing differ per tier, so a single monitor cannot serve
all tiers. Instantiating per *tier* would mean four instances per archetype per
environment; per *band* means at most three, and tier0/tier1 want identical
detection anyway. The tier0 distinction is expressed where it actually matters —
per-service SLOs — which costs a handful of objects rather than doubling the
estate.

---

## ADR-004 — Priority is derived; paging is a separate, narrower rule

**Decision.** `priority = clamp(matrix[impact_class][band], env ceiling)`.
Paging additionally requires production, the critical band, and either P1 or a
source with *confirmed* impact (SLO burn or composite).

**Why.** "How urgent is this?" and "must a human be woken?" are different
questions, and conflating them is the main cause of alert fatigue. A P2 symptom
— a deadlock, an OOMKill, a failed cron — is a real problem with a real ticket
and no claim on anyone's sleep.

**Evidence.** The rule took the paging estate from 96 archetype patterns to 39.
Both the paging count and the P1 count are asserted at plan time.

---

## ADR-005 — Cardinality and paging guardrails are hard failures

≤3 group keys, banned identity keys, a 1,000-group budget, a 1,500-monitor
budget, a 90-pattern paging budget. Enforced at merge (policy lint), at plan
(preconditions and `check` blocks), and at runtime (checks C11, C14).

**Evidence.** The guardrails caught real defects during construction: an
archetype grouping by `url`; four host archetypes whose `notify_by: [cluster]`
was not a subset of `group_by: [host]` and therefore did nothing at all; and two
composites whose members had mismatched groupings.

---

## ADR-006 — Tag-based routing; no people in monitors

Monitors carry `team`, `priority`, `pages`, `notification_profile`.
`datadog_monitor_notification_rule` resolves those to Teams channels, ServiceNow
handles and On-Call targets. Changing a destination is one line in `teams.yaml`
and touches zero monitors.

`pages` is part of the routing filter because priority alone does not determine
paging (ADR-004) — a P2 symptom and a P2 burn alert must reach different
destinations from the same priority.

---

## ADR-007 — Composites demote their members, and declare their owner

**Decision.** A composite's members are rewritten to P4 with no routing where
`demote_members: true`; the composite carries the page. Every member must share
an identical `group_by`. `owner_team` is mandatory and cross-team members must
be named in `cc_teams`.

**Why.** Without demotion a composite *adds* an alert instead of replacing
several. Without identical groupings Datadog correlates any group of A with any
group of B — a database in Frankfurt with an API in Virginia.

**Evidence.** The identical-grouping rule rejected the originally-designed
"host CPU AND application latency" composite. That relationship is real but
belongs to event correlation (topology rules joining on env + region), not to a
composite monitor.

---

## ADR-008 — Automation is classified by blast radius

`diagnostic_only` (read-only, runs on every alert) · `fully_automatic` (bounded,
reversible, rate-capped) · `approval_required` (waits for a human) · `manual`.

The module refuses to publish a `fully_automatic` workflow without
`reversible: true` and `max_actions_per_hour > 0`, and refuses any irreversible
workflow that is not change-board approved.

**Evidence.** The rule fired on `remediate-rerun-job`, which was marked
irreversible with owner approval. The resolution was to make the guardrail
explicit: the workflow refuses to touch a job that has not declared itself
idempotent, and re-running an idempotent job changes nothing.

---

## ADR-009 — Four roles plus one scoped security role

Platform Admin (break-glass, ≤3 humans), Observability Engineer (the CI service
account's role), Engineering User, Read Only. Security Engineer exists
separately because `security_monitoring_*` write permissions cannot be expressed
by the core four without over-granting. Permissions resolve by NAME against the
live catalog at plan time, so a typo fails the plan. Assignment is by IdP group
only.

---

## ADR-010 — Three dashboards, not eighteen and not four thousand

**Original decision.** Four hand-authored boards plus one generated drill-down
per domain — 18 total. Per-service views stayed Datadog-native, because a custom
dashboard per service at 100k services is unmaintainable and redundant.

**Revised.** The per-domain generator was the mistake, and it was a tempting one:
a per-domain board *looks* like a service to the domain that owns it. In
practice the 14 generated boards were the same five widgets with `domain:x`
substituted, and during an incident people went to the monitor list instead —
it filters faster than a dashboard loads and it shows what is firing rather than
a fixed panel set. Datadog already ships the per-domain view (the filtered
monitor list, Service Catalog, APM, Infrastructure, SLO list, and the
Kubernetes/Azure integration dashboards), maintained by Datadog and correct the
day a new resource type appears. A hand-built copy is strictly worse: it is a
snapshot of what we knew about that domain on the day it was generated.

Three boards survive, one per audience:

| Board | Audience | Answers |
|---|---|---|
| Enterprise Observability Overview | observability-platform | Is the platform itself healthy — coverage, ownership, alert quality, budget |
| Operations & Reliability | responders, weekly review | What is firing, what changed, how each domain is behaving |
| SLO & Executive Health | leadership | The promises, and whether we are keeping them |

**The rule that replaces the generator.** A dashboard exists only where the
answer spans domains. Anything scoped to one domain, service or resource is a
native Datadog view; anything that is a periodic question rather than a live one
is a **report** (ADR-019), which is where the five §34 report families went
instead of becoming twenty more boards.

**Consequence.** The on-call board's widgets moved into Operations &
Reliability and the Alert Quality board's into Enterprise Observability
Overview; both boards and all 14 domain boards are destroyed on the next apply.
`moved` blocks keep the two surviving boards' ids and URLs. A test asserts the
estate holds at most four dashboards and that no dashboard *template* remains —
a template left behind is a generator waiting to be re-enabled.

---

## ADR-011 — Runbooks are generated, then completed by humans

**Gap.** The Datadog provider has no notebook resource.

**Decision.** One runbook per archetype, id-matched so "every monitor has a
runbook" is mechanically checkable. The generator writes the block a machine
genuinely knows (what fired, why, which SLO, which automation, which grouping,
escalation contract) between `AUTOGENERATED` markers, regenerated on every
catalog change; human sections outside the markers are preserved. Publishing is
API-backed with an embedded content hash: idempotent, drift-detecting, and
`--check` fails CI.

**Consequence.** 152 runbooks exist with all ten mandatory sections. 906
sections are marked `TODO(owner)` and tracked per domain — an honest backlog
rather than 152 empty files or 152 stale ones.

---

## ADR-012 — Event correlation: deterministic keys plus a reference engine

**Gap.** Datadog Event Management correlation rules have no GA Terraform
resource or public CRUD API.

**Decision.** (1) The factory stamps deterministic `correlation_key` and
`dedup_key` on every monitor, so native aggregation works with zero custom
rules. (2) The intended topology, vendor-outage, maintenance and scope-uplift
policy is versioned in `platform/events/correlation-rules.yaml`, and
`tools/correlate_events.py` is its executable reference implementation, proven
in CI. (3) When the API goes GA, the YAML becomes its input with no monitor
changes.

---

## ADR-013 — No backend block is committed *(superseded by ADR-016)*

**Superseded:** nothing injects a backend any more — under ADR-016 Terraform
always runs on the default local backend and `tools/tfstate-git.sh` moves the
state files to/from the `tfstate` branch around each credentialed step. What
survives from this ADR: no backend block is committed, and offline CI stages
run with no secrets at all.

---

## ADR-014 — Thresholds are never rewritten, anywhere

**Decision.** No automatic per-environment threshold scaling. No `threshold`
exception control. No numeric override on an inherited archetype query.

**Why.** Datadog requires `monitor_thresholds` to equal the numeric literal
inside the query. Honouring a threshold override therefore means rewriting a
number inside a query string at plan time, so the deployed monitor differs from
the reviewed catalog entry in a way no diff shows.

**Discovered by** validating every monitor against `/api/v1/monitor/validate`:
27 monitors were rejected for threshold/query mismatch, all of them produced by
the environment-scaling feature.

**Consequence.** Environment tolerance is expressed through wider evaluation
windows, band instantiation and priority ceilings — all of which are
independent of the query text. A team that needs a different number either
changes the archetype (everyone benefits) or writes a custom monitor with its
own explicit query (only they carry it). See ADR-015.

---

## ADR-015 — Validate against the vendor, every pull request

**Decision.** CI stage 23 plans with credentials so the Datadog provider
validates every monitor; `tools/validate_live.py` does the same job
concurrently and reports all failures grouped by cause.

**Why.** A policy linter can only enforce rules someone thought to write down.
Six classes of defect — two reserved tag keys, two forecast constraints, the
threshold/query coupling, and a multi-alert-only option — survived
`terraform validate`, a 12-family policy linter, 85 unit tests and a clean
offline plan. Every one was caught by the vendor's own validator.

**Consequence.** Offline CI stages stay fast and secret-free; the credentialed
stage is the last gate before merge and is not optional.

---

## ADR-016 — Git-backed Terraform state on a `tfstate` branch

**Decision.** Terraform state lives on the orphan branch `tfstate` of this
repository — one file per stack × environment
(`coverage/qa.tfstate`, `coverage/stage.tfstate`, `coverage/prod.tfstate`,
`foundation/prod.tfstate`) — moved in and out by `tools/tfstate-git.sh`
around every credentialed plan/apply. Terraform always runs on the default
local backend. Directed by the platform owner: GitHub is the system of
record for this platform, including state; no cloud storage account is
introduced for it.

**How each remote-backend guarantee is met.**

| Guarantee | Mechanism |
|---|---|
| Locking | the `concurrency: tfstate` group shared by deploy.yml and governance.yml — GitHub serialises every state-touching run; persist additionally refuses non-fast-forward pushes and rebase-retries, so a lost race cannot overwrite another run's commit |
| Versioning & recovery | every apply is one commit on `tfstate`; recovery is `git checkout` |
| Encryption | GitHub encrypts content at rest; the repository is private |
| Per-environment separation | one state file per environment; the deploy workflow applies exactly one environment per state file, so promotion can never plan a destroy against another environment's resources |

**Why not the previous azurerm design.** It required a storage account,
Azure AD federation, and three more secrets — none of which serve any other
purpose here — and its example wiring pointed both stacks at one state key
(a real defect this ADR's per-env files also fix). The state contains no
secrets (Datadog credentials live only in env vars), which is the
precondition that makes repository-hosted state acceptable.

**Consequence.** The `tfstate` branch is written only by CI (and by an
operator running the script deliberately); branch protection should exclude
it from required reviews. `.gitignore` keeps `*.tfstate*` out of every
OTHER branch, so state can never ride along in a feature PR.

---

## ADR-017 — Workflow automations deploy under an explicit budget

The Datadog org caps workflow automations (~20 per org), and most of the quota
is held by legacy workflows owned by a different login. Workflow ownership is
per-resource: the CI service account gets a 403 deleting them even after a
restriction-policy grant, so CI cannot reclaim the quota itself.

Rather than let the foundation apply fail at the quota mid-run, the catalog
deploys under a committed budget (`stacks/foundation/budget.auto.tfvars`,
`workflow_budget`) against an explicit priority list in
`stacks/foundation/main.tf`, with a `check` block asserting the list stays
complete as the catalog grows. When the legacy workflows are deleted in the UI
by their owner, raising the budget deploys the rest in priority order — no
other change needed. Until then, monitors that reference not-yet-deployed
workflows page correctly; only the automated enrichment is pending.


## ADR-018 — Every monitor carries an auto-resolve window

Datadog's `timeout_h` defaults to `0`, meaning a triggered monitor stays
triggered until a human clears it. The platform inherited that default, and it
is a silent paging defect rather than a cosmetic one: while a group sits in the
triggered state Datadog does not notify again for the **next** occurrence of the
same condition on that group. One stale alert — a batch run whose group
disappeared, a host that was decommissioned, a deployment event that will never
recur — quietly disables that monitor's page while the monitor list still shows
it as healthy and configured.

Auto-resolve is therefore mandatory and policy-derived, not per-archetype
discretion. `platform/policy/global.yaml → monitor_defaults.auto_resolve`
resolves a window for every monitor in the order archetype override → signal →
detection → priority, and higher priorities resolve *sooner*, because a stuck P1
is the one suppressing the page that matters.

The window is a resolution mechanism, not a silencer: `timeout_h` only applies
when a monitor stops reporting data while triggered, so a condition that is
still true keeps alerting, and one whose signal recovers resolves normally
through its recovery threshold. Missing telemetry stays a separate contract
(`notify_no_data` / `no_data_timeframe`), which is why the `telemetry_health`
signal is deliberately not shortened.

Both monitor modules refuse to **plan** a monitor whose window falls outside the
policy range, and coverage check C17 grades the deployed estate the same way, so
the guarantee cannot be lost either by a Terraform change or by an out-of-band
edit in the UI.

---

## ADR-019 — Reports are a catalog of questions, not a folder of scripts

**Gap.** §34 asks for five report families — executive, operations, platform,
database, Azure. The obvious implementation is a dashboard per question, which
is exactly the failure ADR-010 had just finished undoing.

**Decision.** A report is a **catalogued question**, and the catalog is data:
`platform/policy/reports.yaml` holds the id, family, audience, the question in
the reader's own words, its data sources, cadence, and what the reader is
expected to DO. `tools/reports.py` implements exactly those ids, and the test
suite asserts the two agree in both directions — a catalogued report with no
code is a promise nobody keeps, and code with no catalog entry has no audience
and no cadence.

Two constraints keep it small:

1. **No new telemetry.** Every report answers from data the estate already
   emits. A question that cannot be answered from existing telemetry is a
   telemetry gap, not a report.
2. **Every report states an action.** A report with no action is a dashboard
   with extra steps, and the linter rejects one.

**Degradation is declared, never silent.** Three operations reports ask
questions only a running estate can answer: which monitors never fire, which
fire constantly, which oscillate. Offline they answer the *structural* half —
which monitors cannot fire here, which are built to be noisy, which are built to
flap — and label the answer `evidence: structural`. That is what lets the whole
catalog run on a pull request with no credentials.

**Consequence.** Twenty reports across five families, all runnable offline
against `tests/fixtures`. The seven operations reports that §34 named and
nothing implemented — never-triggered, noisy, flapping, services without
telemetry, missing ownership, runbook coverage, on-call coverage — exist and are
tested. They are **not** a CI gate: coverage and the scorecard are the gates, and
a third gate that fires on a review backlog would only teach people to ignore
all three.

---

## ADR-020 — Entity-aware scorecards score alongside the fleet gate, not instead of it

**Gap.** §41 wants services, datastores and infrastructure graded by different
rules. The existing scorecard graded every monitor against one set of weights,
and that set was written for a request-path service — so it asked a database
instance to justify itself as though it were an API.

**Decision.** Three entity kinds (`service`, `datastore`, `infrastructure`),
resolved from an explicit, exhaustive and validated `resource_type` map in
`platform/policy/scorecards.yaml`. Each kind re-weights the same seven
dimensions; datastores carry one additional dimension, `durability`. The seven
dimensions are computed **once**, by the fleet model, and read twice — two
scoring implementations would eventually disagree about what "actionability"
means, and then the two published numbers would be arguing with each other in
the same report.

**Why an unclassified `resource_type` is a lint error rather than a default.**
A silent default to `service` is how a new datastore technology gets graded as a
request path and is never asked for a backup check. Classifying a new type is a
one-line decision, and it should be a decision.

**Why the entity score does not replace the fleet score.** The fleet number
gates the deploy pipeline at ≥ 85. Re-weighting it in place would have changed
what that gate *means* without anybody deciding to change it: the same estate
would score differently on Monday than on Friday, and nobody could tell a real
regression from the reweight. So the fleet model is untouched, the entity model
is added with its own per-kind minimums, and both are published. The fleet score
gates deploys; the entity minimums are enforced by the test suite and by the
governance run (`--enforce-entity-minimums`).

**Consequence.** Four kind-specific rules, each one run against the real catalog
before it was written: three find nothing today and exist as regression guards,
and one finds a genuine backlog — three datastore technologies (`azure_storage`,
`snowflake_warehouse`, `storage_volume`) have no capacity forecast, backup,
replication or freshness check. That is why the datastore minimum is 80 while
service and infrastructure are 85: an honest recorded gap rather than a rounding
allowance.

## ADR-019 — A service states its intent; the platform resolves its SLOs

Objectives used to be assigned, not resolved. A tier0 service received exactly
one auto-generated availability SLO at the tier target, measured by one HTTP
trace template applied to every tier0 service regardless of what it was. That
model could not express two things the business routinely asks for: a service
that owes *several* promises (availability **and** latency **and** freshness),
and two technically identical services that owe *different* numbers — a
partner-facing API on a contractual 99.99% and its internal twin on 99.9%,
running the same code, on the same archetype, behind the same monitors.

Targets could not simply be moved into the service YAML either. A number written
per service is a number nobody reviews: the tier, the entity type and the
platform each have a legitimate say, and the service should only have to state
what is *different* about its promise.

So objectives resolve through a chain, later layers winning field by field:

    enterprise defaults → entity type → platform → criticality (tier) →
    environment → slo_profile → service override

Each layer owns what it is competent to decide. The **entity type** owns the SLI,
because only it knows that a datastore's availability is a service check and a
batch job's is a completed run — the old template measured a datastore with
`trace.http.request.*`, which returns nothing and produces an SLO that is
permanently, silently green. The **tier** owns the targets and burn windows,
because those are business statements and already live in `tiers.yaml`. A
**profile** is the named set a service owner actually chooses, and the
**service** gets the last word, with a written rationale, because nothing sits
above it.

Two rules keep the chain honest. An objective is created only when some layer
switches `enabled: true`, so declaring an SLI is not the same as promising one —
which is what makes a service that names no profile resolve exactly what it
resolved before profiles existed. And technical constraints are *invariants*
applied after the chain, not layers inside it: Datadog rejects `burn_rate()` on a
monitor SLO with a non-metric member, so a tier asking for three burn windows on
a service-check-backed objective gets none, regardless of what the tier says.

The chain is implemented twice — `tools/slo_resolver.py` for the tooling and
`stacks/coverage/slos.tf` for the apply — both reading
`platform/policy/slo_profiles.yaml`, neither reading the other, as everywhere
else in this repository. Coverage check C18 then grades the result against the
live estate: every objective must belong to a real catalog entity, be owned by a
registered team, be production-scoped, and be measurable — the last of which
catches the failure this whole area exists to prevent, an objective that looks
healthy only because no data is arriving.
