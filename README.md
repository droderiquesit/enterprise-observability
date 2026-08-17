# Enterprise Observability Platform (Datadog)

Inventory-driven, profile-based Datadog observability delivered entirely through
Terraform and policy-as-data. Designed for 100,000+ services and 1M+ resources
with a **bounded number of managed objects**: monitors are grouped multi-alert
archetypes, never one-monitor-per-resource.

## What this repository does

- **100% inventory-based coverage** — every discovered service/resource gets an
  owner, environment, criticality, and monitoring profile assigned by policy,
  and is covered by grouped archetype monitors automatically. Application teams
  write **no** baseline monitors.
- **Predictive-first detection** — SLO burn-rate alerts are the primary
  customer-impact signal; anomaly, forecast, outlier, and rate-of-change
  detection cover behavior, capacity, peer-group, and degradation-speed risk.
  Fixed thresholds only where an absolute boundary is meaningful (certificates,
  backups, hard capacity).
- **Mandatory monitor contract** — every alerting monitor carries an SLO
  association, runbook notebook, workflow automation, ownership, severity,
  routing, recovery behavior, correlation metadata, and Terraform ownership
  tags. Enforced in CI, verified post-deploy.
- **Self-service by manifest** — a team that needs a specialized monitor
  submits one small YAML file under `platform/requests/`. CI validates it
  against the platform standards and Terraform generates compliant resources.
- **Continuous governance** — automated coverage reporting finds unmonitored
  resources, missing owners/tags, services without SLOs, monitors without
  runbooks/workflows/routing, duplicates, click-ops monitors, cardinality
  risks, and expired exceptions.

## Repository layout

```
platform/
  policy/            Policy-as-data: the configuration hierarchy
    global.yaml        Global standards (tag set, contract, defaults)
    domains.yaml       Domain overlays (infrastructure, cloud, application, data, security)
    profiles.yaml      Monitoring profiles (observe_only, standard, critical, regulated, security_sensitive)
    environments.yaml  Environment policy (prod, staging, dev, sandbox)
    criticality.yaml   Criticality tiers (tier1..tier4) and severity mapping
    teams.yaml         Teams, ownership, on-call, routing destinations
    routing.yaml       Severity model and notification routing matrix
    slos.yaml          Platform SLO catalog (incl. adopted existing SLOs)
    exceptions.yaml    Approved exceptions (owner, justification, approval, expiry)
    archetypes/        Monitor archetype catalog per domain
  requests/          Self-service monitor request manifests (one YAML per request)
  runbooks/          Versioned runbook notebook templates (API-published; see ADR-006)
  events/            Event-management correlation configuration (see ADR-007)
modules/             Reusable, versioned Terraform modules
stacks/              Deployable root modules (foundation, coverage)
tools/               Inventory discovery, profile engine, validators, coverage report
tests/               Python test suite (includes 1.2M-resource scale test)
docs/                Assessment, architecture, ADRs, standards, runbooks for humans
.github/workflows/   CI/CD: validate, plan, deploy, drift, coverage reporting
```

## Quickstart

```bash
make setup          # install python deps, terraform init all stacks
make validate       # fmt + terraform validate + policy lint + manifest validation + pytest
make plan           # terraform plan (requires DD_API_KEY/DD_APP_KEY of the CI service account)
make coverage       # generate the coverage & compliance report from the live org
```

CI runs the same targets; deployment happens only from `main` through
`.github/workflows/deploy.yml` with a manual approval gate. See
`docs/operating-model.md`.

## Where to start

| I want to… | Read |
|---|---|
| Understand what exists today in the org | `docs/current-state-assessment.md` |
| Understand the design | `docs/architecture.md`, `docs/decision-records.md` |
| Request a specialized monitor | `docs/self-service-guide.md` |
| See tagging/naming rules | `docs/tagging-standard.md` |
| Run/operate the platform | `docs/operating-model.md` |
| Migrate existing org assets | `docs/migration-rollback-plan.md` |
| See validation evidence | `docs/evidence-report.md` |
