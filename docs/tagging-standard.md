# Tagging standard

The monitors in this platform never name a service. They select by tag:

```
avg(last_15m):anomalies(sum:trace.http.request.errors{env:prod,alert_band:critical} by {service}...)
```

That is what lets 264 archetypes cover an estate of any size, and it is also the
catch: **a resource that is not tagged is not monitored, and nothing will say
so.** The monitor exists, evaluates, and returns no data — which looks
identical to healthy.

This document is the contract. Apply Tier 1 to your telemetry and the platform
does the rest.

---

## Tier 1 — you apply these

Six tags. Everything else in this document is either derived from them or
supplied by the integration you already run.

| Tag | Allowed values | Why it matters |
|---|---|---|
| `env` | `dev` `qa` `stage` `prod` | Every query scopes on it. `production`, `prd` and `PROD` all match nothing |
| `service` | your service-catalog identity | 41 archetypes group by it — it is how an alert tells you *which* thing broke |
| `team` | a handle from `platform/policy/teams.yaml` | Ownership and routing |
| `tier` | `tier0` `tier1` `tier2` `tier3` | Drives priority, renotify cadence, support model and whether you get an SLO |
| `service_archetype` | see the list below | **Selects which monitor packs apply.** Without it the platform guesses |
| `alert_band` | `none` `baseline` `standard` `critical` | Every query filters on it. See the note below — this one is special |

### `service_archetype` values

`api` · `web` · `worker` · `event_consumer` · `batch_job` · `scheduled_job` ·
`integration_flow` · `saas_dependency` · `external_endpoint` ·
`platform_service` · `datastore` · `infrastructure_resource`

Pick by **what the thing is**, not by what it's written in. A Java service
behind HTTP is `api`; the same codebase consuming a queue is `event_consumer`.

### The `alert_band` note

`alert_band` is *derived* by `tools/profile_engine.py` from `tier`, `env` and
your monitoring profile — you never choose it. But the derived value has to
land back on the **telemetry**, because that is where the query looks.

Today it does not. That is the single largest gap between this catalog and
working coverage, and it is why the estate currently reports 100% coverage
while the monitors return no data. Two ways to close it:

1. **Push the band onto the resource** — Azure resource tags, Agent tags,
   Kubernetes labels. Correct and explicit; needs a write-back step.
2. **Scope queries on `tier` instead** — one policy change, no telemetry work,
   but coarser: `tier0` and `tier1` share a band today.

Option 1 is the design intent. Option 2 is the pragmatic path if the tagging
pipeline is months away. Pick deliberately — do not leave it undecided, because
undecided reads as "covered".

---

## Tier 2 — grouping keys, per domain

These come from the integration, not from you, but **the integration has to be
configured to send them** or the alert cannot tell you which instance broke.

| Domain | Keys the archetypes group by |
|---|---|
| API | `service`, `peer.service`, `gateway`, `backend_pool` |
| Application | `service`, `version`, `pool`, `peer.service`, `check_id` |
| Kubernetes | `kube_cluster_name`, `kube_namespace`, `kube_deployment`, `node`, `hpa`, `kube_cronjob`, `persistentvolumeclaim` |
| Infrastructure | `host`, `cluster`, `device`, `process_name`, `component`, `backup_policy` |
| Cloud | `subscription_name`, `resource_group`, `name`, `region`, `endpoint_name`, `quota_name`, `backend_pool`, `cost_center` |
| Database | `host`, `db`, `db_instance`, `availability_group`, `replica_server_name`, `subscription_name`, `name`, `warehouse`, `task_name` |
| Messaging | `namespace`, `entity`, `consumer_group`, `stream`, `partition`, `service` |
| Network | `name`, `device`, `interface`, `site`, `peering_type`, `connection_name`, `bgp_peer_address`, `nsg_name`, `tunnel`, `zone` |
| Data | `pipeline`, `data_product`, `warehouse`, `stream`, `consumer_group`, `check_name` |
| Integration | `service`, `job_name`, `flow_name`, `partner`, `feed` |
| vSphere | `vsphere_cluster`, `vsphere_host`, `vsphere_datastore`, `vm_name` |
| Security | `log_source`, `control_id`, `certificate_cn`, `identity_provider`, `vault`, `secret_name` |

Two that need action rather than configuration:

- **`version`** — comes from `DD_VERSION` in the deployment pipeline. Two
  deployment archetypes group by it, and `deployment-version-tag-missing`
  exists specifically to catch services that never send it.
- **`cost_center`** — an Azure resource tag. It is what makes a cost alert
  routable to the people who can act on it instead of to a finance inbox.

### Cost data uses a different tag name

Cloud Cost Management tags cost series `subscriptionname` (no underscore),
while Azure Monitor resource metrics use `subscription_name`. This is not a
typo in the catalog — the two data sources genuinely differ.

---

## Tier 3 — derived and stamped. Never hand-set these

| Set by | Tags |
|---|---|
| `tools/profile_engine.py` | `owner` `domain` `monitoring_profile` `alert_band` `support_model` `managed_by` |
| `modules/monitor_factory` (on the monitor) | `priority` `archetype` `impact_class` `detection` `slo_id` `runbook` `runbook_notebook` `automation_ref` `notification_profile` `failure_domain` `correlation_key` `dedup_key` `managed_source` `monitor_id` `pages` |

Setting one by hand does not add coverage — it creates a disagreement between
what the platform believes and what the tag says, and coverage check C3 will
report it.

## Optional — carried when the source provides them

`region` · `subscription` · `account` · `cluster` · `datacenter` ·
`compliance_scope` · `data_classification` · `cost_center` · `request_id`

`compliance_scope` is worth setting deliberately: it promotes a service to the
`regulated` monitoring profile automatically.

## Never group by these

`host_ip` · `container_id` · `pod_name` · `request_id` · `trace_id` · `path` ·
`url` · `user_id` · `session_id` · `instance_id` · `uuid`

Each one turns a single alert into thousands. The limit is **3 group keys** per
monitor, enforced at plan time — a monitor that violates it cannot be created.

---

## How to apply Tier 1, by source

### Datadog Agent (hosts and VMs) — `datadog.yaml`

```yaml
tags:
  - env:prod
  - service:orders-sql
  - team:payments
  - tier:tier0
  - service_archetype:datastore
  - alert_band:critical
```

### Azure resources — resource tags, collected by the Azure integration

Set them on the resource (or, better, inherit them from the resource group via
Azure Policy so nothing new is created untagged):

```
env = prod
service = checkout-api
team = payments
tier = tier0
service_archetype = api
alert_band = critical
cost_center = cc-payments
```

Azure Policy with a `modify` effect is the only mechanism that keeps this true
over time. Tagging by hand at creation decays within a quarter.

### Kubernetes — Cluster Agent, via labels

```yaml
metadata:
  labels:
    tags.datadoghq.com/env: prod
    tags.datadoghq.com/service: checkout-api
    tags.datadoghq.com/version: "2026.08.19"
    team: payments
    tier: tier0
    service_archetype: api
    alert_band: critical
```

The `tags.datadoghq.com/*` labels are Datadog's unified service tagging and are
picked up automatically; the remaining four need
`DD_KUBERNETES_POD_LABELS_AS_TAGS`.

### APM and custom metrics — environment variables

```bash
DD_ENV=prod
DD_SERVICE=checkout-api
DD_VERSION=2026.08.19          # required for deployment correlation
DD_GIT_COMMIT_SHA=<sha>
DD_GIT_REPOSITORY_URL=<url>
DD_TAGS="team:payments,tier:tier0,service_archetype:api,alert_band:critical"
```

`DD_VERSION`, `DD_GIT_COMMIT_SHA` and `DD_GIT_REPOSITORY_URL` are what make
deployment → error → latency → SLO → incident correlation work. Without them
the deployment archetypes group by a tag nobody sends.

### Service registration — this repository

Registering a service is five fields and gives you the catalog entry, ownership
and — at tier0 — an SLO with burn-rate alerting:

```yaml
service:
  name: checkout-api
  team: payments
  tier: tier0
  service_archetype: api
  envs: [dev, qa, stage, prod]
  compliance_scope: pci      # optional; promotes to the regulated profile
```

Note this registers **ownership**. It does not tag the telemetry — the sections
above do that, and both are needed.

---

## Checking your work

```bash
cd tools
python build_inventory.py --live      # what Datadog can see
python profile_engine.py              # what the platform derives, with violations
python coverage_report.py --live      # C3 lists every missing or invalid tag
```

`profile_engine` reports a violation per resource, naming the tag:
`invalid_env:production`, `service_archetype_inferred`, `missing_tag:tier`.

### Where the estate stands today

The last live run graded 27 resources, all from the service catalog and zero
hosts:

| Finding | Count | Meaning |
|---|---|---|
| `invalid_env:production` | 22 | `production` is not in the vocabulary; the platform coerces it to `prod` and flags it |
| `service_archetype_inferred` | 27 | none carry the tag, so every one was guessed as `api` |
| `alert_band` present | 0 | nothing emits it, so every archetype query filters to an empty set |

Those 27 findings are the accepted exception `EXC-2026-006`, time-boxed and
owned — not a permanent waiver.

---

## The short version

Tag six things on your telemetry:

```
env  service  team  tier  service_archetype  alert_band
```

Add `version` from your deployment pipeline and `cost_center` on Azure
resources. Everything else — priority, routing, runbook, SLO, escalation,
on-call, auto-resolve — is derived, and adding a service creates zero new
monitors.
