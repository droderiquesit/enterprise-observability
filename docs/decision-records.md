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

## ADR-010 — Four dashboards plus one per domain, not four thousand

Enterprise overview, operations overview, on-call board, **alert quality**, and
one generated drill-down per domain (18 total). Per-service views are
Datadog-native. A custom dashboard per service at 100k services is
unmaintainable and redundant.

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

## ADR-013 — No backend block is committed

CI injects `backend.tf` at deploy time. Committing `backend "local" {}` and
passing remote settings to `init -backend-config` is a silent misconfiguration:
init accepts the flags and state still lands on the runner's disk. Keeping the
block out of the repository makes the intended backend explicit and lets offline
CI stages run with no secrets at all.

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
