# Architecture Decision Records

## ADR-001 — Policy-as-data over per-team Terraform
**Decision.** All monitoring intent lives in `platform/policy/*.yaml`;
Terraform stacks are pure interpreters. Teams touch YAML (requests) only.
**Why.** At 100k services, per-team HCL becomes an unreviewable sprawl; YAML
policy is diffable, lintable, and safe for non-Terraform users.
**Consequence.** The hierarchy merge is implemented once, in
`stacks/coverage/locals_*.tf`, and covered by the offline-plan CI gate.

## ADR-002 — Grouped multi-alert monitors, never per-resource monitors
**Decision.** One monitor per (archetype × environment); resources are monitor
groups. Sharding by `region` only when a fleet approaches the 1,000-group
budget.
**Why.** Bounded object count (89 monitors for 1M+ resources), instant
coverage for new resources, single point of tuning.
**Trade-off.** Per-resource threshold exceptions are impossible by design;
the self-service manifest is the sanctioned escape hatch.

## ADR-003 — Monitor contract enforced at three layers
Variable validation + plan preconditions (can't plan a non-compliant
monitor), CI policy lint (can't merge one), coverage report C5–C11 (can't
*keep* one — including click-ops monitors created outside Terraform).

## ADR-004 — Cardinality guardrails are hard failures
≤3 group keys, banned identity keys, 1,000-group budget. A monitor that
explodes into tens of thousands of groups is a cost and paging hazard; the
plan fails rather than the pager. Evidence: the guardrail caught a real
defect during build (an archetype grouping by `url`).

## ADR-005 — Tag-based routing; no people in monitors
Monitors carry `team` + `severity` tags; `datadog_monitor_notification_rule`
(one per team × severity) maps tags → Teams channel, ServiceNow record type,
exec channel (sev1). On-call paging attaches through Datadog On-Call team
routing rules keyed on the same tags. Changing a destination is one line in
`teams.yaml`/`routing.yaml`, touching zero monitors.

## ADR-006 — Runbooks via versioned API publisher (provider gap)
**Gap.** The Datadog Terraform provider has no notebook resource (verified
against provider docs ≥3.60).
**Decision.** Runbooks are markdown in `platform/runbooks/` (PR-reviewed,
mandatory section template), rendered deterministically to notebook cells and
published via the Notebooks API with an embedded content hash: publish is
idempotent, `--check` fails CI on drift — the same guarantees Terraform gives
us (versioning, review, drift control), documented rather than improvised.
**Revisit.** Move to a `datadog_notebook` resource when the provider ships one.

## ADR-007 — Event correlation: deterministic keys + reference engine (partial gap)
**Gap.** Datadog Event Management's correlation rules have no GA Terraform
resource / public API for custom rule CRUD.
**Decision.** (1) The factory stamps every monitor with deterministic
`correlation_key` (failure_domain.env.service) and `dedup_key`
(service.env.archetype[.suffix]); native Event Management aggregation keys off
these tags with zero custom rules. (2) The intended grouping/suppression
policy is versioned in `platform/events/correlation-rules.yaml`, and
`tools/correlate_events.py` is its executable reference implementation, proven
in CI (6 related failures → 1 page, deployment context attached, recovery
closes the group). (3) When the correlation-rule API goes GA, the YAML becomes
its input with no monitor changes.

## ADR-008 — Automation is read-only first; remediation gated
All monitor-attached workflows start with diagnostics/enrichment. Any workflow
that can mutate production must declare `approval: owner|change-board`; the
module rejects a non-read-only workflow without a gate. Remediation actions
must be idempotent and auditable (run-as owner, execution log retained).

## ADR-009 — Four core roles + scoped security role
Platform Administrator (break-glass, ≤3 humans), Observability Maintainer
(the CI service account's role — humans get it temporarily via access
requests), Responder (ack/downtime/incident/workflow-run), Read Only.
Security Engineer exists as a separate scoped role because security-rule
write permissions (`security_monitoring_*`) cannot be represented by the core
four without over-granting. Role permissions are resolved by NAME against the
live permission catalog at plan time — a typo fails the plan instead of
silently no-oping. Humans never share automation identities.

## ADR-010 — Four dashboards, not four thousand
Enterprise overview, operations overview, on-call board, and one generated
drill-down per domain. Per-service views are Datadog-native (Service Catalog,
APM, Infrastructure). A custom dashboard per service at 100k services is
unmaintainable and redundant.

## ADR-011 — Adopt, don't replace, the surviving org assets
21 SLOs, 63 runbooks, 18 workflows, and 5 dashboards from the previous
platform generation remain in the org. They are adopted by ID (registries in
`platform/policy/{runbooks,workflows}.yaml`; gated Terraform `import` blocks
for SLOs/workflows) and the rebuilt monitors re-attach to them. Nothing
existing is deleted (migration plan, `docs/migration-rollback-plan.md`).
