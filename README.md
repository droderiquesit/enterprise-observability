# Enterprise Datadog Monitoring Framework

Inventory-driven, predictive-first, policy-as-data monitoring for **tens of
thousands of services and hundreds of thousands of resources** — delivered
entirely through Terraform, with a bounded number of managed Datadog objects.

```
476 monitors cover a 100,000-service estate.
Adding 50,000 more services creates ZERO new Datadog objects.
69 of those 476 (14%) are permitted to wake a human.
Teams write 5 tags. For anything unique, they write one YAML file.
```

---

## The invariant

> **The number of managed Datadog objects grows with the number of monitoring
> DECISIONS, not the number of monitored RESOURCES.**

The naive model is `services × environments × signals` — 100,000 × 4 × 20 =
**~8,000,000 monitors**. This framework produces **476**, with the same coverage,
because resources are *groups* inside grouped multi-alert monitors, selected by
tag.

| | |
|---|---|
| Archetypes → instances | 151 → 419 (archetype × environment × alert band) |
| SLOs | 21 domain + one per tier0 service → 46 burn-rate monitors |
| Composites | 7 confirmed-impact patterns |
| Self-service | 4 (one YAML file each) |
| Monitors in **dev** | **0** — by policy, not by muting |
| Predictive detection | 36% of instances |
| Fixed thresholds with no written rationale | **0** (CI-enforced) |
| Monitors missing runbook / SLO / automation / routing | **0** (contract-enforced) |

---

## Quickstart

```bash
make setup            # venv + terraform init
make validate         # everything CI checks: policy, manifests, docs, scorecard, tests, tf
make plan-offline     # full plan, no credentials — exercises every guardrail
make matrix           # regenerate the coverage matrix from the catalog
make coverage         # coverage & compliance report against the live org
```

---

## The 30 deliverables

| # | Deliverable | Where |
|---|---|---|
| 1 | Enterprise Monitor Strategy | [reference-architecture §1](docs/reference-architecture.md#1-enterprise-monitor-strategy) |
| 2 | Service Tier Model | [§2](docs/reference-architecture.md#2-service-tier-model) · [`tiers.yaml`](platform/policy/tiers.yaml) |
| 3 | P1–P4 Priority Model | [§3](docs/reference-architecture.md#3-alert-priority-model-p1p4) · [`priorities.yaml`](platform/policy/priorities.yaml) |
| 4 | DEV/QA/STAGE/PROD Alert Policy | [§4](docs/reference-architecture.md#4-dev--qa--stage--prod-alert-policy) · [`environments.yaml`](platform/policy/environments.yaml) |
| 5 | Teams / ServiceNow / On-Call Routing Matrix | [§5](docs/reference-architecture.md#5-routing-matrix--teams-vs-servicenow-vs-on-call) · [`notification_profiles.yaml`](platform/policy/notification_profiles.yaml) |
| 6 | Predictive Monitoring Strategy | [§6](docs/reference-architecture.md#6-predictive-monitoring-strategy) |
| 7 | Monitor Archetype Catalog | [§7](docs/reference-architecture.md#7-monitor-archetype-catalog) · [`archetypes/`](platform/policy/archetypes/) |
| 8 | Application Monitoring Standard | [§8](docs/reference-architecture.md#8-application-monitoring-standard) |
| 9 | Infrastructure Monitoring Standard | [§9](docs/reference-architecture.md#9-infrastructure-monitoring-standard) |
| 10 | Cloud / Azure Monitoring Standard | [§10](docs/reference-architecture.md#10-cloud--azure-monitoring-standard) |
| 11 | Kubernetes Monitoring Standard | [§11](docs/reference-architecture.md#11-kubernetes-monitoring-standard) |
| 12 | VMware Monitoring Standard | [§12](docs/reference-architecture.md#12-vmware-monitoring-standard) |
| 13 | Database / Data Monitoring Standard | [§13](docs/reference-architecture.md#13-database--data-platform-standard) |
| 14 | SLO / Burn-Rate Strategy | [§14](docs/reference-architecture.md#14-slo--burn-rate-strategy) · [`slos.yaml`](platform/policy/slos.yaml) |
| 15 | Composite Monitor Strategy | [§15](docs/reference-architecture.md#15-composite-monitor-strategy) · [`composites.yaml`](platform/policy/composites.yaml) |
| 16 | Event Correlation Strategy | [§16](docs/reference-architecture.md#16-event-correlation-strategy) · [`correlation-rules.yaml`](platform/events/correlation-rules.yaml) |
| 17 | Alert Grouping / Deduplication | [§17](docs/reference-architecture.md#17-alert-grouping--deduplication) · [`grouping.yaml`](platform/policy/grouping.yaml) |
| 18 | Notification Policy Architecture | [§18](docs/reference-architecture.md#18-notification-policy-architecture) |
| 19 | RBAC Model | [§19](docs/reference-architecture.md#19-rbac-model) |
| 20 | YAML Schema | [implementation-guide §20](docs/implementation-guide.md#20-yaml-schema--the-single-file-developer-interface) · [`schemas/`](platform/schemas/) |
| 21 | Terraform Module Architecture | [§21](docs/implementation-guide.md#21-terraform-module-architecture) |
| 22 | Repository Structure | [§22](docs/implementation-guide.md#22-repository-structure) |
| 23 | CI/CD Pipeline | [§23](docs/implementation-guide.md#23-cicd-pipeline) · [`.github/workflows/`](.github/workflows/) |
| 24 | Policy-as-Code Validation | [§24](docs/implementation-guide.md#24-policy-as-code-validation) · [`tools/`](tools/) |
| 25 | Example Monitor Definitions | [§25](docs/implementation-guide.md#25-example-monitor-definitions) · [`monitors/`](platform/monitors/) · [golden path](docs/golden-path.md) |
| 26 | Example Notification Policies | [§26](docs/implementation-guide.md#26-example-notification-policies) |
| 27 | Example Terraform | [§27](docs/implementation-guide.md#27-example-terraform) |
| 28 | Migration Strategy | [migration-strategy.md](docs/migration-strategy.md) |
| 29 | Monitor Quality Scorecard | [quality-scorecard.md](docs/quality-scorecard.md) |
| 30 | Final Reference Architecture | [§30](docs/reference-architecture.md#30-final-enterprise-reference-architecture) |
| — | **Monitor Coverage Matrix** (generated) | [monitor-coverage-matrix.md](docs/monitor-coverage-matrix.md) |
| — | Decision records | [decision-records.md](docs/decision-records.md) |
| — | Operating model | [operating-model.md](docs/operating-model.md) |
| — | **Live validation evidence** | [live-validation-evidence.md](docs/live-validation-evidence.md) |
| — | **Live estate reconciliation & deployment readiness** | [live-estate-reconciliation.md](docs/live-estate-reconciliation.md) |
| — | **Repository audit — how it works, what was verified, how it deploys** | [repository-audit.md](docs/repository-audit.md) |

---

## Repository layout

```
platform/
  policy/          the eight-layer configuration hierarchy (PR-reviewed YAML)
    archetypes/      151 monitor definitions across 14 domains
  services/        service registrations — the golden path, step 1
  monitors/        self-service monitors, ONE YAML file each
  runbooks/        152 runbooks (generated frame + human sections)
  events/          correlation policy
  schemas/         JSON Schema for the two hand-written formats
modules/           10 reusable Terraform modules
stacks/            foundation (routing, on-call, RBAC) · coverage (monitors, SLOs)
tools/             11 Python tools: validate · discover · measure · generate
tests/             85 tests, including a 1.2M-resource scale test
docs/              this documentation, plus the GENERATED coverage matrix
```

---

## The three ideas that do most of the work

**1. Resources are groups, not monitors.** A query scoped to
`{env:prod, alert_band:critical, service_archetype:api}` and grouped
`by {service}` covers every API in production. A new service joins on its first
trace. This is the whole scalability argument.

**2. Priority is derived; paging is narrower still.**
`priority = clamp(matrix[impact_class][band], env ceiling)` — and paging
additionally requires production, the critical band, and either P1 or a source
with *confirmed* impact (an SLO burn-rate alert or a composite). A P2 symptom
raises an incident and a ticket and wakes nobody. That single rule took the
paging estate from 96 patterns to 39.

**3. Every standard is a command.** If a rule cannot be checked mechanically it
does not belong in the standard. Twelve rule families in the policy linter,
seven plan-time preconditions, three budget assertions, fifteen runtime coverage
checks, an eight-dimension quality score, and a credentialed stage that asks
Datadog itself.

---

## Verified

Against the live Datadog organisation, read-only, on 2026-08-17:

- **423/423** planned monitors accepted by `POST /api/v1/monitor/validate`
  (53 SLO burn monitors validated by shape against a real SLO)
- **85/85** tests passing, including 1.2M resources / 100k services assigned in
  bounded time
- Offline plans clean: **476 monitors + 23 SLOs**, **178** foundation resources
- Live governance loop end-to-end: inventory → profiles → coverage report

Live validation caught **six classes of defect** that survived `terraform
validate`, a twelve-family policy linter, 85 unit tests and a clean offline
plan — including one that invalidated a feature and changed the design
(ADR-014). Details and honest limitations:
[live-validation-evidence.md](docs/live-validation-evidence.md).
