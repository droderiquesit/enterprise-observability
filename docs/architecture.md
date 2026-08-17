# Target Architecture

## The scaling problem, and the answer

100,000 services and 1M+ resources cannot be monitored with per-resource
monitors: the object count, plan time, API quota, and human review burden all
explode. This platform holds one invariant:

> **The number of managed Datadog objects grows with the number of monitoring
> *decisions*, not the number of monitored *resources*.**

Resources live in **monitor groups** (multi-alert `by {…}` clauses), not in
monitors. The managed estate is `archetypes × environments (+ SLO burn pairs
+ self-service requests)` — currently 89 monitors covering an arbitrarily
large estate. A new service that starts emitting traces is covered on first
trace by the existing `by {service}` application pack, with zero configuration
and zero new Datadog objects.

```
                     ┌────────────────────────────────────────────────┐
   Datadog APIs      │ platform/policy/  (policy-as-data, PR-reviewed)│
   CMDB / cloud ─┐   │  global → domains → archetypes → profiles →    │
                 ▼   │  environments → criticality → teams → routing  │
        tools/build_inventory.py            │        ▲ exceptions      │
                 │                          ▼        │                 │
        generated/inventory.json   stacks/coverage locals (hierarchy   │
                 │                  merge, pure Terraform)             │
                 ▼                          │                          │
        tools/profile_engine.py             ▼                          │
                 │                 modules/monitor_factory ──► monitors│
   assignments.json ──────────►    modules/slo_with_burn  ──► SLOs +  │
   services.auto.tfvars.json       burn-rate monitors                  │
                 │                 stacks/foundation ──► teams, on-call,│
                 ▼                  routing rules, RBAC, dashboards,    │
        tools/coverage_report.py    workflows, downtimes               │
        (11+ governance checks,     tools/publish_runbooks.py ──►      │
         evidence, CI gate)         notebooks (ADR-006 API path)       │
                     └────────────────────────────────────────────────┘
```

## Control loops

1. **Delivery loop (PR-driven):** policy/manifest change → CI validation
   (policy lint, manifest gates, terraform validate, tests, offline plan,
   determinism diff, credentialed plan with live monitor validation) → manual
   approval → apply → post-deploy idempotency plan + coverage report.
2. **Discovery loop (scheduled):** inventory rebuild → profile assignment →
   service-catalog tfvars → next apply converges the catalog. New resources
   are covered by existing grouped monitors *immediately*; the loop only
   updates ownership records and coverage accounting.
3. **Governance loop (scheduled):** coverage report (C1–C13) + Terraform
   drift + runbook drift. Any finding turns CI red and pages/tickets the
   observability-platform team via the platform-governance path.

## Predictive-first detection

| Layer | Technique | Where |
|---|---|---|
| Customer impact (primary) | SLO burn rate, multi-window (14.4x/1h+5m, 6x/6h+30m, 3x/24h+2h) | `slo_with_burn` + burn instances |
| Behavior over time | `anomalies()` agile | error rate, traffic, CPU, storage latency, auth failures, cost |
| Capacity exhaustion | `forecast()` linear | disk, queues, quotas, DB connections |
| Peer comparison | `outliers()` DBSCAN | pipeline throughput |
| Degradation speed | `pct_change()` | latency, packet errors, telemetry volume, deploy regression |
| Absolute boundaries only | fixed thresholds **with recorded rationale** | cert expiry, backup age, freshness contract, hard K8s conditions |

The policy linter rejects a fixed threshold on a behavioral signal without a
`rationale_fixed_threshold`; the manifest validator applies the same rule to
self-service requests (`justification`).

## The monitor contract

Every monitor the factory emits carries, enforced by variable validation and
plan-time preconditions, and re-verified post-deploy by the coverage report:
stable name (`[domain][env][sevN] Title`), SLO association (`slo_id` tag +
message link), ownership (`team`/`owner`), severity + criticality + priority,
the 11 required tags plus correlation metadata (`correlation_key`,
`dedup_key`, `failure_domain`), runbook notebook (tag + deep link), workflow
automation (`automation_ref`), routing tags consumed by the central
notification rules, recovery + warning + no-data message sections, evaluation
delay / new-group delay / renotify behavior, and Terraform ownership markers
(`managed_by:terraform`, `managed_source`, optional `request_id`).

## Cardinality control

- ≤ 3 group-by keys per monitor; identity keys (`container_id`, `path`, …)
  banned. Enforced three times: policy lint (CI), factory precondition (plan),
  coverage check C11 (runtime).
- Archetypes carrying `shard_by: region` declare the sharding dimension used
  to split a monitor when a fleet approaches the 1,000-groups budget — the
  shard becomes a new instance (`region:eastus2` filter), not a new pattern.
- Tag values come from controlled vocabularies (`global.yaml`); free-text tag
  values fail validation.

## Component inventory

| Concern | Mechanism | Datadog surface |
|---|---|---|
| Monitors | `modules/monitor_factory` (for_each instances) | `datadog_monitor` |
| SLOs + burn | `modules/slo_with_burn` + burn instances | `datadog_service_level_objective`, `slo alert` monitors |
| Runbooks | `tools/publish_runbooks.py` (ADR-006 gap path) | Notebooks API v1 |
| Workflows | `modules/workflow_automation` + adoption imports | `datadog_workflow_automation` |
| Routing | `modules/notification_rules` (team × severity) | `datadog_monitor_notification_rule` |
| Teams/On-call | `modules/team_oncall` | `datadog_team`, `datadog_on_call_schedule`, `datadog_on_call_escalation_policy`, `datadog_on_call_team_routing_rules` |
| Downtimes | `modules/downtime` (tag-scoped, recurring) | `datadog_downtime_schedule` |
| Event correlation | tags + `platform/events/` rules + reference engine (ADR-007) | Event Management |
| Dashboards | `modules/dashboard` (4 total + domain template) | `datadog_dashboard_json` |
| RBAC | `modules/rbac` (name→ID resolution at plan) | `datadog_role`, `datadog_service_account` |
| Ownership | `modules/service_catalog` from inventory | `datadog_service_definition_yaml` |
