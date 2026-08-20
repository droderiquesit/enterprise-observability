# Telemetry gaps and their emission contracts

Every monitor in this platform reads a metric that exists. When the business
asked for a signal that no integration publishes, the answer was never a
plausible-looking proxy — it was to name the gap, classify it, and implement the
cleanest mechanism that produces the real signal.

This document is that register. It is the companion to
`platform/policy/archetypes/`: if an archetype queries an `acme.*` metric, its
emission contract is here.

## Classification used throughout

| Class | Meaning |
|---|---|
| **Native Datadog metric** | An Agent or integration metric. Nothing to build. |
| **Azure metric** | Published by Azure Monitor, collected by the Datadog Azure integration. Nothing to build; the integration must be enabled for the subscription. |
| **Log-derived metric** | The signal exists only in logs. A Datadog log-based metric turns it into a series. |
| **Custom metric** | Nothing observes it today. Something must emit it. |
| **Synthetic** | Only observable from outside the system. |
| **RUM / APM instrumentation** | Requires the application to be instrumented or a collection flag enabled. |
| **Inventory source** | A fact about configuration, not about behaviour. Comes from CMDB / configuration management. |

---

## 1. Database recoverability — `acme.database.restore_verification_*`

**Class:** custom metric · **Consumed by:** `sqlserver-restore-verification-stale`,
`sqlserver-restore-verification-failed`

Backup age proves a file was written. It proves nothing about whether that file
can be read, whether the restore completes, or how long it takes. Treating age
as recoverability evidence is how organisations discover their backups are
useless during an incident — which is exactly when there is no time to find out.

Neither the SQL Server integration nor Azure Monitor can close this gap: no
product knows whether a restore would succeed, because nothing tries.

**Contract.** The restore-verification job — which restores the latest backup to
an isolated target and runs `DBCC CHECKDB` — emits two metrics at the end of
every run:

| Metric | Type | Tags | Meaning |
|---|---|---|---|
| `acme.database.restore_verification_age_hours` | gauge | `db`, `env`, `service`, `alert_band` | Hours since the last SUCCESSFUL verified restore of this database |
| `acme.database.restore_verification_failed` | count | `db`, `env`, `service`, `alert_band`, `failure_stage` | Emitted once per failed verification; `failure_stage` is `restore` or `checkdb` |

The age metric must be emitted on every run, including failed ones — a job that
stops reporting because it is broken must not look like a job whose age is
frozen at "recent".

## 2. Snowflake task and pipeline failures — `acme.snowflake.task_failures`

**Class:** custom metric · **Consumed by:** `snowflake-task-failure`

The Datadog Snowflake integration publishes account- and warehouse-level
aggregates from `SNOWFLAKE.ACCOUNT_USAGE`. It does not publish per-task or
per-pipeline outcomes, and no aggregate can be decomposed back into them.

**Contract.** A scheduled exporter queries
`SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY` on the same cadence as the integration
and emits:

| Metric | Type | Tags |
|---|---|---|
| `acme.snowflake.task_failures` | count | `task_name`, `database`, `schema`, `env`, `alert_band` |

`ACCOUNT_USAGE` latency means this signal is minutes-to-hours behind reality.
That is a property of Snowflake, not of the exporter, and the archetype's
evaluation window accounts for it.

## 3. Message age — `acme.messaging.oldest_message_age_seconds`

**Class:** custom metric · **Consumed by:** `servicebus-message-age`

Azure Service Bus publishes queue DEPTH but never message AGE. Depth cannot
distinguish a thousand messages arriving and draining quickly from a thousand
messages nobody has touched for an hour — and only the second one is an
incident.

**Contract.** The consumer emits the age of the message it is currently
processing, derived from the broker's `EnqueuedTimeUtc`:

| Metric | Type | Tags |
|---|---|---|
| `acme.messaging.oldest_message_age_seconds` | gauge | `namespace`, `entity`, `env`, `service`, `alert_band` |

A consumer that is not running emits nothing, which is why `consumer-absent`
exists alongside this: absence of the age metric is not evidence of a healthy
queue.

## 4. NSG denied flows — `acme.network.nsg_denied_flows`

**Class:** log-derived metric · **Consumed by:** `nsg-denied-flow-anomaly`

Network security groups publish **no Azure Monitor metrics at all**. NSG
observability is flow logs, full stop. Any product claiming an NSG "metric" is
deriving it from those logs.

**Contract.** NSG flow logs land in a storage account, are forwarded to Datadog
Logs, and a log-based metric counts denied flows:

```
Filter    source:azure.network @evt.name:NetworkSecurityGroupFlowEvent @flow.decision:D
Metric    acme.network.nsg_denied_flows   (count)
Group by  @nsg_name -> nsg_name, @env -> env, alert_band
```

## 5. Budget, forecast and burn rate — `acme.finops.*`

**Class:** custom metric (from an API that is not a metric source) ·
**Consumed by:** `azure-budget-utilization`, `azure-budget-breach`,
`azure-cost-forecast-overrun`, `azure-cost-burn-rate`

Datadog Cloud Cost Management publishes spend (`azure.cost.actual`,
`azure.cost.amortized`). It does not publish the BUDGET, which lives in the
Azure Consumption API and changes whenever finance re-plans. Hard-coding a
budget number into a monitor query would have been quicker and would have been
wrong within one planning cycle.

**Contract.** A scheduled exporter reads Azure Budgets and month-to-date actual
spend, and emits:

| Metric | Type | Tags | Meaning |
|---|---|---|---|
| `acme.finops.budget_utilization_pct` | gauge | `subscription_name`, `cost_center`, `team`, `env`, `alert_band` | Month-to-date spend / monthly budget x 100 |
| `acme.finops.budget_burn_rate` | gauge | `subscription_name`, `cost_center`, `team`, `env`, `alert_band` | Current spend pace / the pace that exactly consumes the budget by month-end. 1.0 is on plan by construction |

The `cost_center` and `team` tags are what make cost routable to the people who
can change it, rather than to a central finance inbox.

## 6. Application connection pools — `acme.app.db_pool.*`

**Class:** APM instrumentation (custom metric) · **Consumed by:**
`app-connection-pool-saturation`, `app-connection-acquisition-latency`

The pool lives inside the application process. Database integrations see
server-side sessions; APM runtime metrics see threads and heap. Neither can see
a pool that is full — which is why pool exhaustion presents as "the database
looks fine and the application is timing out".

**Contract.** Applications emit from their pool implementation (HikariCP,
Npgsql, `Microsoft.Data.SqlClient`, `node-mssql`):

| Metric | Type | Tags |
|---|---|---|
| `acme.app.db_pool.active` | gauge | `service`, `pool`, `env`, `alert_band` |
| `acme.app.db_pool.idle` | gauge | `service`, `pool`, `env`, `alert_band` |
| `acme.app.db_pool.max` | gauge | `service`, `pool`, `env`, `alert_band` |
| `acme.app.db_pool.waiters` | gauge | `service`, `pool`, `env`, `alert_band` |
| `acme.app.db_pool.acquire_wait_ms` | gauge | `service`, `pool`, `env`, `alert_band` |

`pool` distinguishes multiple pools in one service (primary, read replica,
reporting). Without it the numbers add up to something meaningless.

## 7. Hardware health — `acme.hardware.*`

**Class:** Agent IPMI check, normalised to a custom metric · **Consumed by:**
`hardware-component-fault`, `hardware-thermal-trend`

IPMI sensor names are hardware-specific: "Inlet Temp" on one vendor, "Ambient
Temp" on another, "Temp_01" on a third. A monitor written against a raw sensor
name works on one fleet and silently covers nothing on the next — the worst
possible failure mode, because the monitor exists and is green.

**Contract.** The Agent's IPMI check collects the sensors; a mapping in the
check configuration normalises them:

| Metric | Type | Tags | Meaning |
|---|---|---|---|
| `acme.hardware.component_health` | gauge | `host`, `component`, `env`, `alert_band` | 0 healthy, 1 non-critical, 2 critical — mirroring IPMI severity |
| `acme.hardware.temperature_celsius` | gauge | `host`, `sensor`, `env`, `alert_band` | Normalised temperature reading |

`component` is one of `fan`, `psu`, `disk`, `memory`, `chassis`, `thermal`.

## 8. Patch and lifecycle state — `acme.compliance.*`

**Class:** inventory source · **Consumed by:** `os-critical-patch-missing`,
`os-patch-age-excessive`, `os-end-of-life`, `agent-version-drift`

Patch level and OS support dates are not observable from telemetry at all. They
are facts about configuration, and they belong to the configuration-management
inventory. Building a "Datadog monitor" that pretends to see them would be
inventing a data source.

**Contract.** A daily export from configuration management emits:

| Metric | Type | Tags |
|---|---|---|
| `acme.compliance.missing_critical_patches` | gauge | `host`, `cluster`, `env`, `alert_band` |
| `acme.compliance.days_since_patch` | gauge | `host`, `cluster`, `env`, `alert_band` |
| `acme.compliance.os_support_days_remaining` | gauge | `host`, `cluster`, `os`, `env`, `alert_band` |
| `acme.compliance.agent_versions_behind` | gauge | `cluster`, `env`, `alert_band` |

## 9. Control-M in-flight job state — `controlm.job.*`

**Class:** custom metric · **Consumed by:** `controlm-job-inflight-overrun`,
`controlm-job-runtime-drift`, `controlm-job-late-start`,
`controlm-job-not-executed`, `controlm-job-abnormally-short`,
`controlm-job-failure`, `controlm-dependency-failure`,
`controlm-job-last-success-stale`, `controlm-exporter-telemetry-loss`

**Control-M has no native Datadog integration for in-flight job state.** This is
the whole reason this section exists. What the ecosystem offers is completion
and log oriented: end-of-job events pushed after a run finishes, and Control-M
logs forwarded into Datadog Logs. Neither can answer the question this domain is
actually judged on — *is the job that is running right now going to finish in
time?* A run that is 20 minutes into a 5-minute job has produced no completion
event, no end status, and nothing to log except that it started. Every
completion-based signal is, by construction, an obituary.

The active job pool is only readable from the **Control-M Automation API**
(`/automation-api/run/jobs/status`, Control-M/EM), which returns each ordered
job's current state, actual start time and the conditions it is waiting on. So
the mechanism is an exporter that polls that API and publishes metrics.

**Polling interval: 60 seconds.** The number is a deliberate trade, not a
default:

* **Why not slower.** The detection lag of every in-flight archetype is bounded
  below by the poll interval. At 60s a job whose baseline is 5 minutes is
  flagged at roughly 10–11 minutes elapsed (ratio 2.0 plus one poll plus the
  5-minute evaluation window) — while there is still time to act. At 5-minute
  polling the same job is flagged after the window it was supposed to protect.
* **Why not faster.** The Automation API is served by Control-M/EM, the same
  component that serves the operators' GUI during the night batch; sub-minute
  polling of a large active pool competes with the people running the batch, and
  the API's session tokens are re-issued rather than long-lived, so aggressive
  polling multiplies authentication traffic too. It also multiplies custom
  metric volume linearly — one gauge per active job per poll — for a signal
  whose subject is measured in minutes.
* **Emission is per active job, per poll.** Jobs not in the active order pool
  emit nothing except `controlm.job.last_success`, which is emitted for every
  job in the current order date whether or not it ran.

**Contract.**

| Metric | Type | Tags | Meaning |
|---|---|---|---|
| `controlm.job.running` | gauge | `folder`, `job_name`, `application`, `controlm_server`, `env`, `service`, `alert_band` | `1` while the execution is in a running state, `0` on any end state. The in-flight **gate**: monitors multiply by it so they cannot fire on a finished run |
| `controlm.job.elapsed_seconds` | gauge | above + `job_state` (`running`\|`completed`) | Seconds since the execution's actual start time. Emitted every poll while running, and once at end with the final value |
| `controlm.job.expected_duration` | gauge | above + `baseline_source` (`history`\|`controlm_average`) | The job's learned baseline in seconds: P95 of its last 30 **successful** runs. Falls back to Control-M's own `AVERAGE_RUNTIME` when fewer than 5 successful runs exist, which is flagged by `baseline_source` so a monitor firing on a cold baseline is recognisable |
| `controlm.job.duration_ratio` | gauge | above + `job_state` | `elapsed_seconds / expected_duration`. Dimensionless, so one monitor threshold is correct for every job in the estate. Emitted every poll while running and once at completion with the final ratio |
| `controlm.job.status` | count | above + `job_status` (`running`\|`completed`\|`failed`\|`late`\|`blocked`\|`not_started`) | One observation per polled state. `late` is Control-M's own verdict against the job's "must start by" time — never re-derived from a schedule copy. `blocked` is emitted only when the job is in Wait Condition **and** a job posting one of its in-conditions ended Not OK in the same order date, i.e. a real dependency failure rather than ordinary queueing |
| `controlm.job.last_success` | gauge | `folder`, `job_name`, `application`, `controlm_server`, `env`, `service`, `alert_band` | **Hours** since this job last completed successfully. Emitted as an age, not a timestamp, because a Datadog query has no concept of "now" to subtract one from |

**Why the baseline is computed in the exporter and not by `anomalies()`.**
Datadog anomaly detection learns from a continuous series with history. An
in-flight series is a ramp that exists only while the job runs and restarts at
zero on the next run; anomaly detection over it learns the shape of the ramp,
not the job's normal duration. Publishing `expected_duration` moves the
per-job baseline off the query path, which is what lets a single archetype cover
thousands of jobs whose runtimes differ by four orders of magnitude.

**The exporter must be watched.** An expired API token or a stopped poller turns
every Control-M monitor green simultaneously — indistinguishable from a quiet
night. `controlm-exporter-telemetry-loss` exists for exactly that, and it is the
reason `controlm.job.status` is emitted on every poll rather than only on state
change: a heartbeat that only fires when something happens cannot prove nothing
is happening.

---

## Gaps that are NOT closed here, and why

| Signal asked for | Status | Reason |
|---|---|---|
| Event Hubs consumer lag (native) | **Not available** | Azure publishes no consumer-lag metric. Lag comes from the checkpoint store and is emitted as `acme.messaging.consumer_lag`, which `consumer-lag-forecast` already reads. `eventhub-egress-stalled` is the native approximation. |
| Front Door / CDN 4xx-5xx ratio (Standard/Premium SKU) | **Log-derived, not implemented** | `Microsoft.Cdn/profiles` publishes `Percentage4XX`/`Percentage5XX`, but the estate's SKU mix is not confirmed. Front Door Classic error behaviour is covered through origin health and latency; the response-code ratio should come from Front Door access logs once the SKU is confirmed. |
| Private Endpoint connection state | **Partially available** | Azure publishes only `PEBytesIn`/`PEBytesOut`. `private-endpoint-traffic-loss` uses the byte counters as the native signal; a Synthetic TCP check against the private FQDN is the definitive test and is recommended per critical endpoint. |
| Azure Firewall rule-processing errors | **Not available** | No metric. Rule-evaluation problems surface in firewall logs; `firewall-denied-traffic-anomaly` catches the behavioural consequence. |
| SQL Server per-query latency | **Requires DBM** | The integration's query-level metrics need Database Monitoring enabled. Until then, blocking, lock waits, long-running transactions and log-flush waits are the covered contention signals. |
| Snowflake query failure rate | **Not available natively** | Same shape as task failures; extend the `acme.snowflake.*` exporter to `QUERY_HISTORY` if the signal is wanted. |

## Prerequisites that are configuration, not code

| Requirement | Needed by |
|---|---|
| RUM enabled with view metrics generated (`rum.view.*`) | `web-vitals-lcp-degradation`, `web-vitals-inp-degradation`, `web-vitals-cls-degradation` |
| `DD_RUNTIME_METRICS_ENABLED=true` on JVM services | `app-jvm-gc-pause-degradation`, `app-jvm-heap-pressure` |
| `DD_RUNTIME_METRICS_ENABLED=true` on .NET services | `app-dotnet-gc-pause-degradation`, `app-dotnet-gen2-collection-anomaly` |
| `DD_VERSION`, `DD_GIT_COMMIT_SHA`, `DD_GIT_REPOSITORY_URL` set by the deployment pipeline | `deployment-regression`, `deployment-error-spike`, and the deployment-to-incident correlation chain. `deployment-version-tag-missing` detects services where this has not been done. |
| Database Monitoring enabled for SQL Server and Azure SQL | DBM query-level signals |
| Azure integration enabled per subscription | every `azure.*` archetype |
| Cloud Cost Management enabled for Azure | `azure-cost-anomaly` |
| Control-M Automation API enabled on Control-M/EM, with a read-only service account for the exporter | every `controlm-*` archetype (§9) |
