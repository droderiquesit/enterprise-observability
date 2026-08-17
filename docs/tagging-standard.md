# Tagging & Naming Standard

## Required tags (every monitor, SLO, service, and — via agent/integration
## config — every resource)

| Tag | Vocabulary | Meaning |
|---|---|---|
| `env` | prod, staging, dev, sandbox | Deployment environment |
| `service` | catalog service name | Owning service (catalog identity) |
| `team` | handle from `teams.yaml` | Responding team |
| `owner` | handle from `teams.yaml` | Accountable owner |
| `domain` | infrastructure, cloud, application, data, security | Platform domain |
| `platform` | per `domains.yaml` | Technology platform grouping |
| `resource_type` | e.g. host, kube_deployment, db_instance, pipeline | Archetype grouping dimension |
| `criticality` | tier1–tier4 | Business criticality |
| `region` | eastus2, centralus, westeurope, onprem-dc1/2, global | Location / shard dimension |
| `monitoring_profile` | observe_only, standard, critical, regulated, security_sensitive | Assigned profile |
| `managed_by` | terraform | IaC ownership marker — absence = click-ops (check C9) |

**Context tags (only where applicable):** `account`, `subscription`,
`project`, `cluster`, `data_classification`, `compliance_scope`,
`support_model`, `cost_center`.

**Platform-emitted governance tags (never hand-set):** `archetype`,
`severity` (sev1–sev3), `priority` (p1–p5), `slo_id`, `failure_domain`,
`routing_rule`, `snow_record`, `pages`, `runbook`, `automation_ref`,
`correlation_key`, `dedup_key`, `managed_source`, `request_id`.

## Normalization rules

- Keys and values lowercase; `[a-z0-9_.-]` only; `:` separates key from value.
- One value per governance key (first wins on conflict, flagged as violation).
- Vocabulary-controlled keys reject unknown values in CI
  (`tools/validate_policy.py`, `tools/validate_manifests.py`) and are flagged
  at runtime by the profile engine (`invalid_env:*`, `invalid_criticality:*`)
  and coverage check C3. Example caught in the synthetic estate: `env:production`
  (invalid; must be `prod`).

## Naming

| Object | Pattern | Example |
|---|---|---|
| Monitor | `[domain][env][sevN] Title` | `[application][prod][sev2] Application Error Rate Anomaly` |
| Burn monitor | `[domain][env][sevN] <SLO name> — error budget burn (window)` | `[application][prod][sev2] Application availability — error budget burn (fast)` |
| SLO | Descriptive name; identity lives in `slo_id` tag | `Application availability` (`slo_id:slo-app-availability`) |
| Notebook | `Runbook: <Archetype title>` | `Runbook: Db Replication Lag` |
| Workflow | registry name; identity in `automation_ref` tag | `enrich-latency-alert` (`automation_ref:auto-enrich-latency`) |
| Dashboard | Fixed set; see ADR-010 | `Domain — data` |

Names are stable: renames happen only through PRs, and object identity for
tooling always comes from tags (`slo_id`, `archetype`, `automation_ref`),
never from display names.
