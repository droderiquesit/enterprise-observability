# Current-State Assessment

Assessed 2026-08-17 against the live Datadog org (via the Datadog MCP/API) and
the `droderiquesit/enterprise-observability` repository.

## Repository

Greenfield: the repository contained only a LICENSE. No IaC, no CI, no
documentation. Everything in this repo is new.

## Datadog org — what exists

A previous generation of a Terraform-managed observability platform was
deployed to this org (creator `dd-ai-start`, created 2026-08-05..07, all
resources tagged `managed_by:terraform`). Its non-monitor assets survive:

| Asset | Count | State |
|---|---|---|
| Monitors | **0** | **All deleted.** The org has no alerting coverage at all. |
| SLOs | 21 | Present, tagged with a full governance tag set (`slo_id`, `archetype:slo-burn`, `correlation_key`, `dedup_key`, `routing_rule`, `snow_record`, …). |
| Runbook notebooks | 63 | Published, named `Runbook: <Archetype>`, 60–132 cells each. |
| Workflow Automation | 18 | Published; enrichment/remediation/ticket/incident kinds; tagged `automation_ref:auto-*`, `approval:*`, `read_only:true`. |
| Dashboards | 5 platform + stock | Executive Overview, Operations & Reliability, Service & Application Health, Platform Governance, Infrastructure & Cloud Health. |
| Service catalog | 22 services | Owned by `application-development` and `cloud-engineering`; includes app services, publishers/batch, DNS, PKI, Snowflake. |
| Hosts / infrastructure | 0 reporting | No agent or cloud-integration telemetry currently flowing. |

## Broken/at-risk items found

1. **Zero monitors** — the entire alerting layer must be rebuilt. Confirmed via
   monitor search and monitor-group search (`total_count: 0`).
2. **Orphaned monitor-type SLOs** — at least 4 SLOs reference deleted monitor
   IDs and report `"no valid monitors found"` / `"monitor not found"`:
   - `Azure platform reliability` (`slo-cloud-azure-platform`) → monitors 311841687, 311841681
   - `Database platform availability` (`slo-infra-database-availability`) → 6 deleted monitors
   - `Identity platform availability` (`slo-infra-identity-availability`) → 311841304
   - `Storage platform availability` (`slo-infra-storage-availability`) → 311841340
3. **Metric SLOs with silent numerators** — `Backup success rate`,
   `Certificate renewal timeliness`, `Security notification delivery` compute on
   custom metrics (`acme.backup.job.total`, `acme.identity.certs_due`,
   `acme.security.notifications_total`) that report no data
   (`denominator … is 0`). The SLOs are structurally fine; the telemetry
   producers are absent. This is a telemetry-gap finding, not an SLO defect.
4. **No telemetry** — no hosts report; time-slice SLOs on
   `azure.servicebus_namespaces.messages`, `trace.http.request.duration` etc.
   currently show 100%/no-data because nothing is flowing.
5. **No state** — the previous platform's Terraform state is not in this repo,
   so surviving org assets are currently **unmanaged** from this codebase's
   point of view until imported/adopted (see `docs/migration-rollback-plan.md`).

## Inherited standards worth preserving

The surviving assets encode a coherent tag scheme that this platform adopts and
formalizes (see `docs/tagging-standard.md`): `env`, `service`, `team`, `owner`,
`domain`, `platform`, `criticality:tierN`, `severity:sevN`, `priority:pN`,
`archetype`, `slo_id`, `correlation_key`, `dedup_key`, `failure_domain`,
`routing_rule`, `snow_record`, `support_model`, `pages`, `managed_by:terraform`,
`monitor_type`. Runbook naming (`Runbook: <Archetype>`) and workflow tagging
(`automation_ref:<id>`, `approval:<gate>`) are also adopted.

## Consequences for the target design

- The monitor layer is rebuilt from the archetype catalog and **re-attached to
  the surviving SLOs by `slo_id` tag** (`platform/policy/slos.yaml` records the
  existing SLO IDs so burn-rate monitors and monitor-type SLO membership can be
  restored without recreating the SLOs).
- Surviving notebooks/workflows/dashboards/SLOs are **adopted, not replaced**:
  imported into state or referenced by ID; nothing existing is deleted.
- Coverage reporting treats "custom metric produces no data" as a first-class
  gap category (it is the second-largest failure mode found in this org).
