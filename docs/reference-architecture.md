# Enterprise Datadog Monitoring Framework — Reference Architecture

> Sections 1–19 and 30 of the deliverable set. Implementation detail is in
> [`implementation-guide.md`](implementation-guide.md) (§20–27), migration in
> [`migration-strategy.md`](migration-strategy.md) (§28), and the quality model
> in [`quality-scorecard.md`](quality-scorecard.md) (§29). The full monitor
> coverage matrix is generated at
> [`monitor-coverage-matrix.md`](monitor-coverage-matrix.md).

---

## 1. Enterprise Monitor Strategy

### The invariant

> **The number of managed Datadog objects grows with the number of monitoring
> DECISIONS, not the number of monitored RESOURCES.**

The naive enterprise model is `services × environments × signals`. At the scale
this framework targets that is 100,000 × 4 × 20 = **8,000,000 monitors** — an
estate nobody can review, tune, cost, or trust.

This framework produces **474 monitors** for the same coverage:

| Layer | Count | Grows with |
|---|---|---|
| Archetype packs | 419 | monitoring decisions (archetype × env × band) |
| SLO burn-rate | 44 | number of objectives, not services |
| Composites | 7 | confirmed-impact patterns |
| Self-service | 4 | genuinely unique team requirements |
| **Total** | **474** | **never with resource count** |

Adding 50,000 services adds **zero** Datadog objects. Resources are *groups*
inside grouped multi-alert monitors, selected by tag.

### The eight-layer configuration hierarchy

```
L0  Global Standards      platform/policy/global.yaml
      ↓                   tag contract, monitor defaults, cardinality and
                          paging budgets, burn-rate windows, detection policy
L1  Domain                platform/policy/domains.yaml
      ↓                   14 technology domains, owner team, failure domains
L2  Service Archetype     platform/policy/service_archetypes.yaml
      ↓                   what KIND of thing this is → which monitor packs apply
L3  Monitoring Profile    platform/policy/profiles.yaml
      ↓                   5 profiles + 2 overlays → how strictly it is watched
L4  Environment Policy    platform/policy/environments.yaml
      ↓                   dev/qa/stage/prod: which bands exist, how loud
L5  Tier Policy           platform/policy/tiers.yaml
      ↓                   tier0–tier3: SLO scope, escalation, paging class
L6  Team Policy           platform/policy/teams.yaml
      ↓                   channels, ServiceNow groups, on-call, escalation
L7  Exception             platform/policy/exceptions.yaml
                          time-boxed, owned, approved, expiring
```

Terraform is a **pure interpreter** of these files. No monitoring decision is
made in HCL; every decision is reviewable YAML.

### How coverage actually happens

```
   Resource emits telemetry with 5 tags
   env · service · team · tier · service_archetype
                    ↓
   tools/profile_engine.py assigns owner, domain, profile, ALERT BAND
                    ↓
   Monitors select on  {env:prod, alert_band:critical, service_archetype:api}
                    ↓
   The resource becomes a GROUP inside monitors that already exist
```

There is no onboarding step. A service that starts emitting traces is inside
the API pack's `by {service}` grouping on its first trace.

### What is deliberately NOT in this framework

- **Per-service dashboards.** Datadog's Service Catalog, APM and Infrastructure
  views are better and free. Four boards plus one per domain (§10, ADR-010).
- **Threat detection.** Cloud SIEM detection rules are owned by the security
  team. This framework covers the *operational health of security controls*.
- **Per-resource thresholds.** Impossible by design. The escape hatch is one
  YAML file (§3), which is a reviewed, tracked, expiring decision.

---

## 2. Service Tier Model

Four tiers. A tier is a **business statement** made by the service owner and
reviewed by the platform team. It is the single input that decides how much
monitoring machinery a service receives.

| | **Tier 0 — Mission Critical** | **Tier 1 — Business Critical** | **Tier 2 — Standard Production** | **Tier 3 — Dev / Non-Critical** |
|---|---|---|---|---|
| Examples | auth, payments, checkout, API gateway, core network | order processing, customer portal, settlement | internal tools, reporting, back-office batch | sandboxes, experiments, decommissioning |
| Monitoring profile | `critical` | `critical` | `standard` | `observe_only` |
| **Alert band** | `critical` | `critical` | `standard` | `none` |
| **SLO scope** | **per service** | domain SLO | domain SLO | none |
| Availability objective | 99.95% | 99.9% | 99.5% | — |
| Latency objective | 99.5% | 99.0% | 98.0% | — |
| Burn windows | fast + medium + slow | fast + slow | slow | — |
| Paging | P1 + confirmed impact | P1 + confirmed impact | never | never |
| Incident creation | P1, P2 | P1, P2 | P1 only | none |
| Ack / escalate | 5 min / 10 min | 10 min / 20 min | 60 min / 4 h | — |
| Escalation chain | on-call → secondary → lead → IC | on-call → secondary → lead | team channel → lead | — |
| Renotify | 30 min | 60 min | 120 min | — |
| Support model | 24×7 | 24×7 | business hours | none |
| Error-budget policy | **feature freeze** until budget > 25% | reliability work next sprint | tracked in ops review | n/a |
| Review cadence | monthly | quarterly | quarterly | annual |

### Why tier0 and tier1 share an alert band

Bands are what monitor *queries* select on, and tier0 and tier1 want the same
detection. What differs is **SLO scope**: tier0 gets its own per-service SLO
and therefore its own error budget, burn-rate alerts, and freeze policy. That
distinction costs a handful of objects (one SLO + 3 burn monitors per tier0
service) instead of doubling the monitor estate.

### Tier 3 is a decision, not a gap

Every `observe_only` resource carries a recorded reason and appears in the
coverage report. "Not monitored" is never allowed to be an accident — check C10
fails on an `observe_only` resource with no reason.

---

## 3. Alert Priority Model (P1–P4)

Priority states the **required human response**, not how bad a metric looks. It
is derived, never hand-picked:

```
priority = clamp( matrix[impact_class][alert_band], environment ceiling )
```

### The matrix

| impact_class | `critical` band | `standard` band | `baseline` band |
|---|---|---|---|
| **customer_impact** — a customer-visible function is failing now | **P1** | P2 | P3 |
| **degradation** — measurably worse, or a subset failing | **P2** | P3 | P4 |
| **risk** — nothing broken yet, a boundary approaches | P3 | P3 | P4 |
| **hygiene** — our ability to observe or govern is reduced | P4 | P4 | P4 |

### Choosing an impact class

| Class | The test the archetype author applies |
|---|---|
| `customer_impact` | *"If this is real, is a customer already experiencing failure?"* |
| `degradation` | *"Is the experience worse, or is a subset of traffic failing?"* |
| `risk` | *"Is there still time to act before impact?"* |
| `hygiene` | *"Does this affect our ability to see, rather than the service itself?"* |

### The definitions

| | Meaning | Response | Ack | Pages | Incident | ServiceNow |
|---|---|---|---|---|---|---|
| **P1** | Confirmed or highly probable major business outage | Immediate, 24×7, IC on the bridge | 5 min | **yes** | SEV-1 | Incident P1 |
| **P2** | Serious degradation needing rapid engineering response | Rapid | 10 min | **only on confirmed impact** | SEV-2 | Incident P2 |
| **P3** | Real, actionable, not immediate | Next business day | 4 h | no | no | Task when sustained |
| **P4** | Informational, preventative, hygiene | Reviewed in aggregate | — | no | no | none |

### The paging rule — the most important rule in the framework

Priority decides *urgency*. A second, narrower rule decides *paging*, because
conflating them is the main cause of alert fatigue:

```
pages =  env == prod
     AND alert_band == critical
     AND ( priority == P1                              -- unambiguous outage
           OR source in (slo_burn, composite) )        -- confirmed impact
```

A **P2 raised by a single symptom archetype** — a deadlock, an OOMKill, a failed
cron, a retry storm — creates an incident, a ServiceNow record and a Teams
notification, and **does not wake anyone**. An SLO burn-rate alert is a
*measurement of customer harm*; a composite has already *confirmed two
independent conditions*. A lone symptom has established neither.

This one rule takes the paging estate from **96 patterns to 39**, plus 23
burn-rate monitors and 7 composites — **69 of 474 monitors (14%)** can page.
Both numbers are asserted at plan time (`max_paging_monitors`, `max_p1_monitors`
in `global.yaml`) so growth is a reviewed decision, never a drift.

### The only sanctioned uplift

| Rule | When | Effect |
|---|---|---|
| `multi-service-scope` | one correlation group spans >25% of a pack's services | parent raised one level (max P1) — breadth *is* business impact |
| `composite-confirmed` | a composite confirms symptom + impact | the composite carries the page; members demote to P4 |
| `sustained-p3` | a P3 stays alerting past 2 renotifications | ServiceNow task auto-created, channel re-notified |

Downgrades: the environment ceiling (always), an active maintenance window, and
an open parent correlation group.

---

## 4. DEV / QA / STAGE / PROD Alert Policy

The **same archetype definition** is used in every environment. The environment
never changes *what* is detected; it changes *how loud the result is*.

| | **DEV** | **QA** | **STAGE** | **PROD** |
|---|---|---|---|---|
| Alerting | **none** | release-blocking only | production-shaped | full |
| Bands instantiated | — | `baseline` | `standard`, `critical` | `baseline`, `standard`, `critical` |
| Monitors created | **0** | 19 | 119 | 285 |
| Priority ceiling | — | P3 | P3 | P1 |
| Paging | never | never | never | tier-driven |
| Incident creation | no | no | no | P1, P2 |
| ServiceNow | no | Task | Task | Incident |
| Teams | no | `<team>-nonprod` | `<team>-nonprod` | `<team>` |
| SLO impact | no | no | **no** | yes |
| Recovery notifications | no | yes | yes | yes |
| Threshold tolerance | — | recorded only | recorded only | ×1.0 |
| Evaluation window | — | ×2 | ×1.5 | ×1.0 |
| Escalation | none | none | none | full |
| Business hours only | — | yes | no | no |

### Design notes that matter

**DEV creates literally zero monitors.** Not muted, not low-priority — none.
`bands_instantiated: []`. Telemetry, dashboards and events all still work. A
CPU anomaly in dev is not an operational event, and the cheapest way to
guarantee it never becomes one is for the monitor not to exist.

**Environments can only ever make a signal quieter.** There is no code path
anywhere in this framework that raises a priority in a non-production
environment. This is asserted as a property test over the whole matrix.

**Evaluation windows widen instead of thresholds moving.** `last_15m` in prod
becomes `last_30m` in stage and QA via a lookup table. Non-production is noisier
and less important, so it waits longer before believing a signal.

**Thresholds are never rewritten — anywhere (ADR-014).** The
`sensitivity_multiplier` values in `environments.yaml` are *recorded intent*,
not applied math: scaling an anomaly threshold silently changes the algorithm
(it is a deviation count), scaling a forecast threshold moves the breach point
(it is a saturation ratio), and scaling a negative threshold makes it *more*
sensitive. Non-production gets quieter through wider evaluation windows and
priority ceilings only.

**The one sanctioned exception: the release gate.** A tier0 release-gate
archetype in stage may reach P2 and notify the release channel during an active
release window — so a bad release is stopped before production. It still never
pages. The policy is defined and reviewed; provisioning is gated behind the
release-window signal from the deployment pipeline (`provisioned: false`), so
no dead notification rules exist in the meantime.

---

## 5. Routing Matrix — Teams vs ServiceNow vs On-Call

Monitors contain **no destinations**. They carry tags; notification rules
resolve tags to people and systems:

```
notification_profile × priority × pages × team  →  Teams + ServiceNow + On-Call
```

Changing where a team's P1s go is **one line in `teams.yaml`** and touches zero
monitors.

### Six profiles for the entire enterprise

| Profile | Selected when | P1 | P2 | P3 | P4 |
|---|---|---|---|---|---|
| `production_critical` | prod + critical band | **Page** + SEV-1 + SNOW P1 + team channel + major-incident + exec | **Page**¹ + SEV-2 + SNOW P2 + team channel | Team channel, SNOW task when sustained | Low-noise channel |
| `production_standard` | prod + standard band | SEV-2 + SNOW P2 + team channel | SNOW P2 + team channel | Team channel, SNOW when sustained | Low-noise channel |
| `production_baseline` | prod + baseline band | — | — | Low-noise + SNOW when sustained | Low-noise channel |
| `nonprod_standard` | qa or stage | — | — | `<team>-nonprod` + SNOW **task** | Low-noise channel |
| `security_operational` | domain security | **Page security** + SEV-1 + SNOW P1, owner cc'd | **Page security** + SNOW P2, owner cc'd | Security channel + SNOW task | Security low-noise |
| `release_gate` | stage + tier0 + active release window | — | Release channel + SNOW task | Release channel | — |

¹ P2 pages only from SLO burn-rate monitors and composites — see §3.

### The security routing decision

Security signals route to the **security team regardless of who owns the
resource**, because the responder is not the owner. The owning team is notified
in parallel for context, never as the primary responder. This is expressed as a
domain-level `routing_override_team`, so it cannot be forgotten on an individual
monitor.

### Rule count

18 routing rows × the teams each applies to = **118 notification rules** for the
whole enterprise. Adding a team adds its routing automatically; adding a monitor
adds none.

---

## 6. Predictive Monitoring Strategy

**36% of the estate uses predictive detection.** Fixed thresholds survive only
where the number itself is the operational contract — and every one of them
carries a written rationale that CI enforces.

### When to use which technique

| Technique | Use when | Do **not** use when | In this framework |
|---|---|---|---|
| **Anomaly (`agile`)** | The signal has a stable short-term shape and you care about deviation from *its own* normal | The metric is bursty by design, or you need a hard boundary | error rates, CPU, memory, throughput, queue depth, restarts |
| **Seasonal anomaly (`robust`, weekly/daily)** | Traffic has genuine daily or weekly shape (business hours, month-end) | Fewer than ~2 seasons of history exist | API latency, auth failures, batch duration, security telemetry volume |
| **Forecast (`linear`)** | The signal moves monotonically toward a limit and lead time is what you want | The signal is cyclic or resets (it will forecast nonsense) | disk, inodes, quotas, connection pools, PVC, backlog, cluster capacity, SaaS quota |
| **Outlier (`DBSCAN`)** | Many peers do comparable work and divergence *is* the defect | Peers are legitimately heterogeneous | partition skew, dependency latency across peers |
| **Rate of change (`pct_change`)** | Speed of degradation matters more than level | The metric is naturally spiky | latency regressions, deploy regressions, packet errors, retry storms, ingest collapse |
| **SLO burn rate (multi-window)** | You want *customer impact*, weighted by what the objective allows | Non-production (there is no budget to burn) | every objective — the primary paging signal |
| **Composite** | Two independent conditions together mean something neither means alone | One signal is already unambiguous | 7 confirmed-impact patterns (§11) |
| **Fixed threshold** | The number is a contract: SLA, RPO, quota, protocol limit, expiry lead time | Anything behavioural | certs, backups, freshness, replication lag, DLQ depth, restart counts |

### The two canonical replacements

```
BEFORE   CPU > 80%
AFTER    anomalies(avg:system.cpu.user{...} by {cluster,host}, 'agile', 3)
         → a batch node at 95% on schedule is healthy;
           an API node at 55% when it normally runs at 20% is not.
         → P3 on its own. Only correlation with a service symptom escalates it.

BEFORE   disk > 90%
AFTER    forecast(avg:system.disk.in_use{...}, 'linear', 1) over next_3d > 0.95
         → a volume steady at 92% for two years is not an incident;
           a volume at 60% growing 8%/day is.
         → 3 days is the shortest window in which a human can reliably act.
```

### Enforcement

`tools/validate_policy.py` (section `DETECTION`) rejects:

- a fixed threshold on a behavioural signal with no `rationale_fixed_threshold`
- **any** fixed threshold with no rationale, behavioural or not
- a `detection:` label that the query does not actually implement
- `seasonal_anomaly` without a `seasonality=` parameter

The test suite additionally asserts that predictive instances outnumber fixed
ones by at least 0.6×, so the ratio cannot quietly erode.

---

## 7. Monitor Archetype Catalog

**151 archetypes → 419 monitor instances** across 14 domains. The complete
matrix — every column you asked for — is generated at
[`monitor-coverage-matrix.md`](monitor-coverage-matrix.md) and regenerated by CI
so it cannot drift.

| Domain | Archetypes | Instances | Owner |
|---|---|---|---|
| Application (web, worker, runtime, dependency, deploy) | 16 | 40 | `sre` |
| API | 9 | 24 | `application-development` |
| Kubernetes | 16 | 44 | `cloud-engineering` |
| Infrastructure (host / VM / storage / process) | 11 | 33 | `infrastructure-engineering` |
| VMware | 8 | 21 | `infrastructure-engineering` |
| Cloud (Azure PaaS) | 17 | 45 | `cloud-engineering` |
| Database | 13 | 35 | `data-engineering` |
| Data platform | 9 | 24 | `data-engineering` |
| Messaging / streaming | 9 | 22 | `cloud-engineering` |
| Network | 9 | 19 | `infrastructure-engineering` |
| Security (operational) | 9 | 21 | `security` |
| SaaS / external endpoints | 7 | 19 | `sre` |
| Integration / batch / scheduled | 11 | 31 | `application-development` |
| Platform services | 7 | 21 | `observability-platform` |

### Anatomy of an archetype

```yaml
k8s-pod-crashloop:
  title: Pods in CrashLoopBackOff
  signal: availability              # what is being measured
  impact_class: degradation         # → priority, with the band
  detection: threshold              # → how, and what CI demands of it
  monitor_type: query alert
  resource_type: kube_pod
  selector: ""                      # extra tag scope beyond env + band
  query: 'max(last_10m):sum:kubernetes_state.container.status_report.count.waiting{__SCOPE__,reason:crashloopbackoff} by {kube_cluster_name,kube_namespace,kube_deployment} >= 1'
  thresholds: { critical: 1 }
  group_by: [kube_cluster_name, kube_namespace, kube_deployment]
  notify_by: [kube_cluster_name]    # storm control: notify once per cluster
  evaluation_window: last_10m
  envs: [prod, stage, qa]           # where it is instantiated
  bands: [critical, standard, baseline]
  slo_id: slo-k8s-workload-availability
  runbook: k8s-pod-crashloop
  workflow: diag-k8s-workload
  failure_domain: kubernetes-workloads   # correlation key prefix
  mandatory: true                   # counts towards coverage
  rationale_fixed_threshold: "CrashLoopBackOff is a discrete Kubernetes state."
```

`__SCOPE__` is replaced at plan time with `env:<env>,alert_band:<band>[,<selector>]`.
That substitution is the whole trick: **one monitor, every matching resource.**

### Service archetypes → packs → archetypes

A team declares `service_archetype: api`. That selects packs, which select
archetypes:

| Service archetype | Packs |
|---|---|
| `api` | api-core, app-runtime, dependency, deployment |
| `web` | web-core, app-runtime, dependency, deployment, synthetic-endpoint |
| `worker` | worker-core, app-runtime, dependency |
| `event_consumer` | consumer-core, worker-core, app-runtime, messaging-client |
| `batch_job` | batch-core, dependency |
| `scheduled_job` | schedule-core |
| `integration_flow` | integration-core, dependency |
| `saas_dependency` | external-dependency |
| `external_endpoint` | synthetic-endpoint, certificate |
| `platform_service` | api-core, app-runtime, dependency, deployment |
| `datastore` | datastore-core |
| `infrastructure_resource` | host-core |

That declaration is the **only monitoring choice a team makes**.

---

## 8. Application Monitoring Standard

**Mandatory** (coverage is measured against these): availability, error-rate
anomaly, traffic-drop anomaly, telemetry loss, dependency failure, deployment
regression, worker stall.

| Signal | Detection | Impact | Env | Grouping | Why this shape |
|---|---|---|---|---|---|
| Availability (web) | synthetic ×3 failures | customer_impact | prod/stage/qa | `service, check_id` | Three failures across locations separates an outage from one unhappy probe |
| Origin 5xx | anomaly agile 3 | customer_impact | prod/stage | `service` | Absolute 5xx rates differ per service; deviation does not |
| Page load | pct_change 40% | degradation | prod/stage | `service` | Speed of regression, not absolute ms |
| Browser errors | anomaly agile 3 | degradation | prod | `service` | RUM error volume tracks traffic; only deviation is meaningful |
| Worker throughput | anomaly, direction below | degradation | prod/stage | `service` | A worker that *stops* looks identical to a healthy idle worker |
| Worker stalled | zero work in 30m | customer_impact | prod/stage/qa | `service` | Zero has no statistical interpretation — it is an absolute liveness boundary |
| Runtime saturation | anomaly on thread-pool utilisation | risk | prod | `service` | Pool sizes differ per service |
| Memory leak | forecast heap → 92% in 4h | risk | prod | `service` | Leaks are monotonic and therefore forecastable |
| Crash / fatal | anomaly agile 3 | degradation | prod | `service` | — |
| Telemetry loss | zero spans in 30m + no-data | hygiene | all | `service` | **The monitor that guarantees "no alerts" never silently means "no data"** |
| Dependency failure | anomaly on client errors | degradation | prod/stage | `service, peer.service` | — |
| Dependency latency | pct_change 100% | degradation | prod | `service, peer.service` | — |
| Deployment regression | pct_change 300% over 30m | degradation | prod/stage | `service` | Release gate |
| Post-deploy error spike | anomaly by version | customer_impact | prod | `service, version` | Version dimension isolates the bad release |

**Paging:** only availability-class P1s. Latency and error regressions raise
incidents and tickets; the *page* comes from the SLO burn or the
`deploy-induced-degradation` composite.

---

## 9. Infrastructure Monitoring Standard

**Infrastructure alerts exist to support diagnosis, not to page.** Only two
infrastructure conditions reach `customer_impact`: a host that is gone, and a
filesystem that has gone read-only.

| Signal | Detection | Impact | Grouping | Collapse | Rationale |
|---|---|---|---|---|---|
| Host unavailable | service check, 4 consecutive | customer_impact | `cluster, host` | `cluster` | 4 checks separates host loss from agent restart |
| CPU baseline deviation | anomaly agile 3 | **risk** | `cluster, host` | `cluster` | Replaces `CPU > 80%` |
| Memory pressure | anomaly, direction below | risk | `cluster, host` | `cluster` | — |
| Disk exhaustion | forecast → 95% within 3d | risk | `cluster, host, device` | `cluster` | Replaces `disk > 90%` |
| Inode exhaustion | forecast → 90% within 3d | risk | `cluster, host, device` | `cluster` | The failure nobody monitors until the first time |
| Filesystem read-only | service check | **customer_impact** | `cluster, host, device` | `cluster` | Binary kernel state |
| Process down | service check ×3 | degradation | `cluster, host, process_name` | `cluster` | — |
| Agent unhealthy | `datadog.agent.running < 1` | hygiene | `cluster, host` | `cluster` | **Protects the monitoring itself** |
| Clock drift | `abs(ntp.offset) > 15s` | hygiene | `cluster, host` | `cluster` | 15s is where Kerberos and TLS break |
| Storage latency | anomaly on `io.await` | degradation | `cluster, host, device` | `cluster` | — |
| Backup age | `> 26h` | risk | `service, backup_policy` | `service` | 24h RPO + 2h grace — the number *is* the control |

### The grouping decision that matters

Host archetypes group by `(cluster, host)` and collapse with
`notify_by: [cluster]`. Evaluating per host is what makes the alert actionable;
notifying per cluster is what stops a rack or hypervisor failure from sending
five hundred separate notifications. **A collapse key that is not also a group
key does nothing** — the policy linter enforces the subset relationship, and it
caught exactly this defect during construction.

---

## 10. Cloud / Azure Monitoring Standard

One archetype per Azure service **class**, never per resource. Grouping follows
how Azure incidents actually scope: subscription → resource group → resource.

| Azure service | Signals | Detection | Impact | Collapse |
|---|---|---|---|---|
| **App Service** | health check, 5xx, plan saturation | threshold / anomaly / forecast | customer_impact, customer_impact, risk | `subscription_name` |
| **Functions** | failure anomaly, execution stalled | anomaly / threshold | degradation, customer_impact | `subscription_name` |
| **SQL** | DTU forecast, connection failures | forecast / anomaly | risk, customer_impact | `subscription_name` |
| **Cosmos DB** | RU throttling (429) | threshold | degradation | `subscription_name` |
| **Service Bus** | see §Messaging | | | `namespace` |
| **Storage** | availability vs SLA, throttling | threshold / anomaly | customer_impact, degradation | `subscription_name` |
| **Load Balancer** | DIP availability < 50% | threshold | customer_impact | `subscription_name` |
| **Application Gateway** | healthy hosts, 5xx | threshold / anomaly | customer_impact | `subscription_name` |
| **Key Vault** | availability, throttling | threshold | customer_impact, degradation | `subscription_name` |
| **Virtual Machines** | power/provisioning state | threshold | degradation | `subscription_name` |
| **Subscription** | quota forecast, Service Health events, cost anomaly, integration gap | forecast / event / anomaly / threshold | risk, degradation, hygiene, hygiene | `subscription_name` |
| **AKS** | see §Kubernetes | | | `kube_cluster_name` |

### Three Azure-specific design decisions

**Quota exhaustion gets a one-week forecast.** Quota exhaustion is the most
common cause of "the deploy failed and nobody knows why" in a large Azure
estate, and quota increases take days to grant.

**Azure Service Health events are a correlation PARENT.** A Microsoft-declared
regional event is authoritative context: it adopts every correlated symptom in
that region rather than adding one more alert (§12).

**A silent Azure integration is a first-class alert.** `azure-integration-telemetry-gap`
fires when the integration stops delivering metrics at all — otherwise every
cloud monitor goes silently green and the estate looks perfect.

---

## 11. Kubernetes Monitoring Standard

Grouping is uniform and deliberate: **cluster → namespace → workload**. Never
`pod_name` or `container_id` — a 50-node rollout would create tens of thousands
of groups and turn a single deploy into an alert storm. Every archetype collapses
with `notify_by: [kube_cluster_name]`.

| Signal | Detection | Impact | Envs | Mandatory |
|---|---|---|---|---|
| Deployment has no available replicas | threshold `< 1` | **customer_impact** | prod/stage/qa | ✓ |
| Redundancy degraded (< 60% of desired) | threshold | risk | prod | |
| CrashLoopBackOff | threshold `>= 1` | degradation | prod/stage/qa | ✓ |
| Container restart anomaly | anomaly agile 3 | degradation | prod | |
| OOMKilled | threshold `>= 1` | degradation | prod/stage | ✓ |
| Memory saturation | forecast → 95% in 4h | risk | prod | |
| CPU throttling | anomaly on throttled periods | risk | prod | |
| Pods pending (scheduling failure) | threshold `>= 3` | degradation | prod/stage | ✓ |
| Node NotReady | threshold | degradation | prod/stage | ✓ |
| Node pressure (memory/disk/PID) | threshold | risk | prod | |
| Cluster capacity | forecast requests/capacity → 90% in 1w | risk | prod | ✓ |
| HPA pinned at max replicas | threshold | risk | prod | |
| PVC exhaustion | forecast → 90% in 1d | risk | prod | ✓ |
| CronJob failing | threshold | degradation | prod/stage | ✓ |
| API server latency | pct_change 150% | degradation | prod | |
| Cluster stopped reporting | zero pods + no-data | hygiene | all | ✓ |

**Only `deployment-unavailable` pages.** CrashLoopBackOff, OOMKill and pending
pods are P2/P3 — real, ticketed, notified, but a human is not woken for a pod
restart. The `redundancy-loss-confirmed` composite pages when redundancy loss
and CrashLoopBackOff appear together on the same workload.

---

## 12. VMware Monitoring Standard

VM-level alerting is deliberately absent: a VM is already covered by the
`host-core` pack through its guest agent. What only vCenter can tell us is what
is monitored here — **the virtualization layer beneath the guest**.

| Signal | Detection | Impact | Grouping | Rationale |
|---|---|---|---|---|
| ESXi host disconnected | threshold | customer_impact | `vsphere_cluster, vsphere_host` | Connection state is discrete |
| Cluster HA failover capacity < 1 | threshold | degradation | `vsphere_cluster` | The cluster can no longer survive a host loss — an HA design contract |
| Datastore capacity | forecast → 90% in 1w | risk | `vsphere_datastore` | A full datastore stops every VM on it simultaneously |
| Datastore latency | anomaly agile 3 | degradation | `vsphere_datastore` | — |
| CPU ready contention > 10% | threshold | risk | `vsphere_cluster, vsphere_host` | VMware's own published contention threshold |
| Memory ballooning / swap-in > 0 | threshold | degradation | `vsphere_cluster, vsphere_host` | Any host-level swap-in means overcommit past what guests absorb |
| VM powered off unexpectedly | event | degradation | `vsphere_cluster` | Discrete state change |
| Snapshot age > 7d | threshold | hygiene | `vsphere_cluster, vm_name` | Aged snapshots consume datastore and slow consolidation |

---

## 13. Database & Data Platform Standard

### Databases

Covers Azure SQL, Cosmos DB, PostgreSQL, MySQL, Redis and Mongo through one
catalog with engine selectors.

| Signal | Detection | Impact | Rationale |
|---|---|---|---|
| Instance unavailable | service check ×3 | customer_impact | Reachability is binary |
| Query latency | anomaly agile 3 | degradation | — |
| Connection pool | forecast → 90% in 2h | risk | One of the few DB failures with a reliable linear ramp — converts a 3am outage into a business-hours ticket |
| Replication lag > 300s | threshold | **customer_impact** | 300s is the declared RPO; past it a failover loses committed data |
| Storage | forecast → 90% in 1w | risk | — |
| Deadlocks | anomaly | degradation | — |
| Long-running query > 15m | threshold | degradation | Exceeds every documented OLTP statement timeout — it is holding locks, not working |
| Backup age > 26h | threshold | risk | 24h RPO + 2h grace |
| Cache hit ratio | pct_change −20% | risk | Redis only |
| Cosmos RU throttling (429) | threshold `> 0` | degradation | Hard provisioned-throughput boundary; any throttling is real customer latency |
| Azure SQL DTU | forecast → 90% in 1d | risk | — |
| Azure SQL connection failures | anomaly | customer_impact | — |
| Telemetry loss | zero + no-data | hygiene | — |

### Data platform

The data domain's customer impact is **freshness and correctness, not uptime**.
A pipeline that runs perfectly and produces stale or wrong data is a worse
outage than one that fails loudly — so freshness and volume are the
`customer_impact` signals here and job failure is only `degradation`.

| Signal | Detection | Impact | Why |
|---|---|---|---|
| Freshness breach > 2h | threshold | **customer_impact** | The threshold *is* the contract with the consuming business unit |
| Volume anomaly | seasonal anomaly, weekly | **customer_impact** | Catches the silent failure job-status monitoring cannot see: the job succeeds and writes 4 rows instead of 4 million |
| Pipeline job failure | threshold | degradation | Discrete outcome |
| Duration anomaly | seasonal anomaly, daily | risk | The earliest predictor of a freshness breach that has not happened yet |
| Data quality check failed | threshold | degradation | Failed assertion is discrete |
| Schema drift | event | risk | — |
| Warehouse queue | forecast | risk | — |
| Streaming consumer lag | forecast → 1M records in 2h | risk | — |
| Telemetry loss | zero runs + no-data | hygiene | — |

---

## 14. SLO & Burn-Rate Strategy

### The monitoring layer model

```
   Business / Service SLO   ← pages (burn rate)
            ↓
      Golden Signals        ← incidents + tickets
            ↓
      Dependencies          ← incidents + context
            ↓
      Infrastructure        ← diagnosis only, rarely pages
```

Paging concentrates at the top. Infrastructure alerts *support* diagnosis; they
almost never page on their own.

### Two SLO scopes keep the count bounded

| Scope | Count | Covers | Rationale |
|---|---|---|---|
| **Domain** | 21 | tier1 and tier2 across the whole estate | A grouped SLI query covers every service in the domain |
| **Per service** | one per tier0 service | tier0 only | A mission-critical service deserves its own error budget; an internal reporting tool does not |

Total today: **23 SLOs** (21 domain + 2 tier0) → **44 burn-rate monitors**.

### Multi-window burn rates

| Window | Long | Short | Factor | Budget consumed if sustained | Response |
|---|---|---|---|---|---|
| `fast` | 1h | 5m | 14.4× | 2% of a 30-day budget in one hour | **Page** |
| `medium` | 6h | 30m | 6× | 5% in six hours | **Page** |
| `slow` | 24h | 2h | 3× | 10% in a day | Ticket |
| `trend` | 72h | 6h | 1× | — | Informational |

The **long window** proves the burn is sustained rather than a spike. The
**short window** proves it is still happening now, which is also what makes the
alert recover quickly. A single-window burn alert either fires on every blip
(short only) or keeps paging long after recovery (long only).

**The slow window deliberately does not page.** A 24-hour burn is a real problem
with days of budget left; waking someone for it teaches them that pages are not
urgent — the most expensive lesson a platform can teach.

Which windows a service gets comes from its tier: tier0 gets all three, tier1
gets fast + slow, tier2 gets slow only.

### Error-budget policy

| Tier | On exhaustion |
|---|---|
| tier0 | **Feature freeze** for the owning team until the budget recovers above 25%; a documented exception is required to deploy |
| tier1 | Reliability work prioritised next sprint; change-advisory review for high-risk deploys |
| tier2 | Tracked in the team's operational review; no freeze |

---

## 15. Composite Monitor Strategy

A composite exists for exactly one reason: **to convert a noisy symptom into a
confirmed impact so that something can page which otherwise could not.**

### The rule that makes composites reduce noise

> Members are demoted to informational (P4, no routing); the composite carries
> the page.

Without the demotion a composite *adds* an alert instead of replacing several —
the most common way composite monitors make noise worse. The demotion happens
in Terraform before the monitors are rendered, and appears in the
`demoted_by_composite` output.

### The hard requirement

**Every member must share an identical `group_by`.** Datadog evaluates a
composite per group only when member groupings match; mismatched members degrade
to *"any group of A and any group of B"*, which correlates a database in
Frankfurt with an API in Virginia. Enforced by the policy linter *and* a
plan-time precondition.

This guardrail did real work during construction. The originally-designed
composite was "host CPU deviation AND application latency degradation" — CPU is
grouped by host, latency by service. It was **rejected**, and correctly: that
cause-and-symptom relationship is real, but it belongs to **event correlation**
(topology rules joining on env + region), not to a composite monitor.

### The seven composites

| Composite | Members | Demotes members | What it distinguishes |
|---|---|---|---|
| `storage-degradation-with-exhaustion-risk` | storage latency + disk forecast | ✓ | A slow disk *and* a filling disk on the same device = a filesystem degrading as it approaches its limit |
| `redundancy-loss-confirmed` | k8s redundancy degraded + CrashLoopBackOff | | An elastic instance disappearing is normal; losing declared replica count is not |
| `database-saturation-impacting-application` | connection saturation + query latency | | The pool is not just filling, it is failing to drain |
| `queue-backlog-with-consumer-failure` | queue depth anomaly + retry storm | ✓ | Backlog with a healthy consumer is capacity; with a failing consumer it is data loss in slow motion |
| `deploy-induced-degradation` | deployment regression + p99 latency | | **The highest-precision page in the framework** — remediation (roll back) is known before a human reads the alert |
| `data-freshness-with-pipeline-failure` | freshness breach + job failure | | "Late because upstream is slow" (wait) vs "late because the job died" (act now) |

### Cross-team composites are allowed, but never implicit

The most valuable composites join a cause in one team's domain to a symptom in
another's. Rather than banning them, the platform forces the ownership question
to be answered in the file: `owner_team` is mandatory, and whenever members span
teams the other teams must be named in `cc_teams`. **An alert with two owners has
none; an alert with one owner and named observers is a working escalation path.**

### Where composites are not worth it

- when one signal is already unambiguous (host down, certificate expired)
- when members fire on different timescales (a 3-day forecast and a 5-minute
  error spike will rarely overlap)
- more than 3 members — nobody can reason about why it fired

Budget: 12 composites maximum. More than that means the archetypes themselves
are badly tuned and should be fixed instead.

---

## 16. Event Correlation Strategy

**Goal: five alerts for one problem become one incident with four children and
the change that caused it attached as context.**

### Deterministic keys, stamped by the factory

```
correlation_key = <failure_domain>.<env>.<service>      grouping identity
dedup_key       = <service>.<env>.<archetype>[.<sfx>]   event identity
```

Native Datadog Event Management aggregation works off these tags with **zero
custom rules**. Everything below is versioned policy executed by
`tools/correlate_events.py`, which is both the specification and the test.

### The six rules

| Rule | Behaviour |
|---|---|
| `group-by-correlation-key` | Same failure domain + env + service → one case, max 200 members |
| `attach-change-context` | Deployments, Terraform applies, Kubernetes rollouts, cloud platform events, ServiceNow changes and scaling events join as **context**. They never page and never become the parent — they *explain* it. 30-minute lookback |
| `platform-cause-suppresses-app-symptom` | Infrastructure / network / cloud / VMware / Kubernetes / database failures adopt application and integration symptoms in the same env + region |
| `vendor-outage-suppresses-integration-symptoms` | A confirmed SaaS or Azure Service Health outage adopts every dependent integration and application error — *"it is them, not us"* as one statement instead of twelve tickets |
| `maintenance-window-suppression` | Events inside an active downtime are tagged `maintenance:true` and never open or join a group |
| `scope-uplift` | If a group's children span >25% of a pack's services, the parent rises one priority (max P1). **Breadth is business impact** |

### Root-cause ranking — who becomes the parent

Ordered most-causal to most-symptomatic; ties break on priority, then time:

```
availability → control_failure → replication_lag → schedule_miss → capacity
→ saturation → freshness → error_rate → latency → throughput → volume
→ telemetry_health → drift → cost → change
```

Latency is nearly always a symptom. Availability is nearly always a cause.

### Proven in CI

The test suite asserts, on every pull request:

- a six-alert database cascade (unavailable → saturation → app dependency
  errors → API latency → budget burn + a duplicate) collapses to **1 group,
  1 page, 1 incident, 4 suppressed children**
- a deployment attaches as context and never becomes the parent
- a Salesforce outage absorbs two downstream integration failures
- unrelated failures in different regions stay separate
- recovery closes the group, and only when **every** child has recovered
- maintenance-window events are dropped entirely
- a failure spanning 5 of 10 services in a pack escalates P2 → P1

---

## 17. Alert Grouping & Deduplication

Four independent mechanisms, applied in order. The failure they prevent: an
Azure region degrades, 4,000 pods restart, and 4,000 notifications arrive.

### 1. Multi-alert grouping

The monitor evaluates per group, not per resource. Grouping strategy per class:

| Class | Keys | Rationale |
|---|---|---|
| Service-level | `service` | The service is the unit of ownership and of impact |
| Kubernetes | `kube_cluster_name, kube_namespace, kube_deployment` | How Kubernetes ownership resolves |
| Host | `cluster, host` | Investigate per host, notify per cluster |
| Cloud | `subscription_name, resource_group, name` | Azure failures scope to a subscription or region |
| Datastore | `db_instance` | |
| Messaging | `namespace, entity, consumer_group` | |
| Pipeline | `pipeline` (+ `data_product` where composited) | |
| Job | `service, job_name` | |
| Network | `site, device` | |

Banned in every group_by: `host_ip`, `container_id`, `pod_name`, `request_id`,
`trace_id`, `path`, `url`, `user_id`, `session_id`, `instance_id`, `uuid`.
Enforced three times — policy lint, plan precondition, runtime check C11.

### 2. `notify_by` collapse — the single most effective control

A monitor grouped by `[kube_cluster_name, kube_namespace, kube_deployment]` with
`notify_by: [kube_cluster_name]` evaluates 4,000 groups and sends **one
notification per cluster**. Required on every archetype whose group count can
exceed ~50, and the collapse key **must be one of the group keys** — a collapse
key that is not a group key does nothing at all, which looks like storm control
while providing none.

### 3. Deduplication and flap suppression

- identical `dedup_key` within 15 minutes = one event
- a group transitioning more than 4 times in an hour is **flapping**: it is
  muted and a ticket is raised instead of paging again

### 4. Storm limits — the circuit breaker

| Scope | Limit | Action |
|---|---|---|
| Per monitor | 100 groups alerting | Collapse to a single "*N* groups alerting" notification |
| Per team per hour | 25 notifications | Suppress further, raise one storm event, page the platform team |
| Per correlation group | 200 children | Truncate the child list in the page; the full list stays in the event |
| Globally per hour | 50 pages | **Declare a major incident, stop paging, open the bridge** |

### Symptom over cause

When a service symptom and its infrastructure cause both fire, the **cause
becomes the parent** but the page carries the **symptom's business impact** —
because that is what the responder needs to communicate.

---

## 18. Notification Policy Architecture

Covered in §5. The architectural points:

- **Teams never configure routing.** There is no field for it in the
  self-service schema, and no destination string anywhere in a monitor.
- **Everything derives from tags:** `team`, `priority`, `pages`,
  `notification_profile`, `env`.
- **`pages` is part of the routing filter**, not just the priority — because
  priority alone does not decide whether a human is woken (§3).
- **Destinations are defined once**, org-wide, in `notification_profiles.yaml`.
- **Sustained-P3 promotion:** a P3 alerting past two renotifications
  automatically creates a ServiceNow task. This is how "actionable but not
  urgent" avoids becoming "quietly ignored forever".

---

## 19. RBAC Model

Four roles plus one scoped security role. Assignment is by **identity-provider
group only** — no individual user permissions, ever.

| Role | Can | Cannot |
|---|---|---|
| **Datadog Platform Admin** | Integrations, RBAC, org settings, API keys, all platform configuration | — (≤3 humans, break-glass, audit-logged, every use reconciled into code within 24h) |
| **Observability Engineer** | Manage monitors, SLOs, dashboards, notebooks, workflows, incident settings | Change organisation-level security or RBAC |
| **Engineering User** | View telemetry, investigate, acknowledge, schedule downtime, run approved workflows, propose YAML | Create or edit monitors directly |
| **Read Only** | View everything | Change anything |
| **Security Engineer (scoped)** | Security-monitoring rules and signals, incidents, run workflows | Everything else |

**Why the fifth role exists:** `security_monitoring_*` write permissions cannot
be expressed by the core four without over-granting. It is scoped, not general.

**Service accounts, never shared human identities:**

| Account | Role | Used by |
|---|---|---|
| `svc-observability-terraform` | Observability Engineer | CI deploys only |
| `svc-observability-coverage` | Read Only | Coverage reporting |

Permissions are resolved **by name** against the live permission catalog at plan
time, so a typo fails the plan instead of silently granting nothing.

---

## 30. Final Enterprise Reference Architecture

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  SOURCES OF TRUTH (PR-reviewed YAML — no monitoring logic lives in HCL)      │
│                                                                              │
│  platform/policy/       global · domains · service_archetypes · profiles     │
│                         environments · tiers · priorities · teams            │
│                         notification_profiles · grouping · composites        │
│                         slos · runbooks · workflows · exceptions             │
│                         archetypes/  ← 151 monitor definitions, 14 domains   │
│  platform/services/     service registrations (tier + archetype + owner)     │
│  platform/monitors/     self-service monitors — ONE YAML FILE each           │
│  platform/runbooks/     152 runbooks (generated skeleton + human sections)   │
│  platform/events/       correlation rules                                    │
└───────────────┬──────────────────────────────────────────┬───────────────────┘
                │                                          │
     ┌──────────▼───────────┐                  ┌───────────▼────────────┐
     │  TERRAFORM (declare) │                  │  PYTHON (measure)      │
     │                      │                  │                        │
     │ stacks/foundation    │                  │ build_inventory.py     │
     │   teams, on-call,    │                  │   Datadog + CMDB +     │
     │   118 routing rules, │                  │   cloud → inventory    │
     │   27 workflows,      │                  │          ↓             │
     │   18 dashboards,     │                  │ profile_engine.py      │
     │   RBAC, catalog      │                  │   owner · tier ·       │
     │        ↓             │                  │   profile · ALERT BAND │
     │ stacks/coverage      │                  │          ↓             │
     │   monitor_factory ───┼──► 419 packs     │ coverage_report.py     │
     │   slo            ───┼──► 23 SLOs       │   C1–C15 governance    │
     │                      │    44 burn       │ monitor_scorecard.py   │
     │   composite_monitor ─┼──► 7 composites  │   quality per team     │
     │   + 4 self-service   │                  │ generate_matrix.py     │
     └──────────┬───────────┘                  │ generate_runbooks.py   │
                │                              │ correlate_events.py    │
                ▼                              └───────────┬────────────┘
        ┌───────────────────────────────────────────────────▼──────────┐
        │  DATADOG                                                     │
        │  474 monitors · 23 SLOs · 118 notification rules ·            │
        │  27 workflows · 18 dashboards · 8 teams · on-call · catalog   │
        └───────────────────────────────────────────────────────────────┘
                │                                          ▲
                ▼                                          │
     ┌──────────────────────┐                  ┌───────────┴────────────┐
     │  RESPONSE            │                  │  GOVERNANCE LOOPS      │
     │  On-Call · Teams ·   │                  │  CI on every PR        │
     │  ServiceNow ·        │                  │  drift nightly         │
     │  Incidents · Runbooks│                  │  coverage weekdays     │
     │  · Workflow automation│                 │  scorecard monthly     │
     └──────────────────────┘                  └────────────────────────┘
```

### The three control loops

1. **Delivery (PR-driven).** Policy change → CI gate (schema, tests,
   terraform, security, live monitor validation) → approval → apply →
   post-deploy idempotency + coverage + scorecard.
2. **Discovery (scheduled).** Inventory rebuild → profile assignment → catalog
   convergence. New resources are covered by existing monitors *immediately*;
   the loop only updates ownership records and coverage accounting.
3. **Governance (scheduled).** Coverage report (C1–C15) + Terraform drift +
   runbook drift + quality scorecard. The nightly governance gate blocks on
   every finding and opens an issue; the deploy gate blocks only on
   platform-integrity findings (see docs/deployment.md).

### The numbers

| | |
|---|---|
| Monitors for a 100k-service estate | **474** (naive model: ~8,000,000) |
| Monitors created by adding 50,000 services | **0** |
| Monitors that can page a human | **67 (14%)** |
| Instances using predictive detection | **36%** |
| Fixed thresholds without a written rationale | **0** (CI-enforced) |
| Monitors without runbook + SLO + automation + routing | **0** (contract-enforced) |
| Monitors in DEV | **0** (policy) |
| Tags a team must apply | **5** |
| Terraform a team must write | **none** |
| Files a team writes for a custom monitor | **1** |
