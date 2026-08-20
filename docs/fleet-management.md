# Agent Operations Standard

The rest of this platform is written on an assumption: that the telemetry the
monitors read is being collected. 651 monitors, 22 SLOs and 261 runbooks are
all downstream of an agent process running somewhere with the right checks
enabled and the right tags attached.

Nothing in this repository put that agent there.

This document is the standard for how it gets there, how it is configured, and
how we prove it — and it is explicit about the line between what this repository
does and what it recommends, because a fleet standard that blurs that line is
how an organisation ends up believing it has coverage it does not have.

**Companion files**

| File | What it holds |
|---|---|
| `platform/policy/agent_profiles.yaml` | The five profiles: checks, integrations, telemetry emitted, archetypes enabled, and the eight compliance checks |
| `tools/fleet_compliance.py` | The measurement — compliant / required, offline or live |
| `docs/tagging-standard.md` | The tags the profiles read and the deployment metadata contract |
| `docs/telemetry-gaps.md` | Every signal an agent cannot produce, and what produces it instead |

---

## 1 · The five profiles

Composition, not a matrix. A host carries `base-infrastructure` always, exactly
one OS profile, and zero or more role profiles.

| Profile | Kind | Assigned when | Adds |
|---|---|---|---|
| `base-infrastructure` | base | every agent host | system, disk, ntp, process, agent self-health |
| `windows-server` | os | `os_family = windows` | windows_service, windows_event_log, wmi_check (+ iis where present) |
| `linux-server` | os | `os_family = linux` | systemd, journald (+ ipmi on bare metal) |
| `application` | role | `service_archetype` ∈ api, web, worker, event_consumer, batch_job, scheduled_job, integration_flow | APM, runtime metrics, DogStatsD, log collection, deployment metadata |
| `sqlserver` | role | `service_archetype = datastore` **and** `db_engine = sqlserver` | SQL Server integration + Database Monitoring |

There is **no Kubernetes profile**, because the audit found no Kubernetes in the
estate. `platform/policy/archetypes/kubernetes.yaml` exists and is correct and
covers nothing today. The conditional profile — its trigger, its shape and its
different delivery mechanism — is recorded in `agent_profiles.yaml` under
`conditional_profiles`, so the next person finds a decision rather than an
absence. Writing it now would have created a fleet in the documentation that
does not exist in the datacentre, and a compliance denominator of zero, which
reports as 100%.

### Assignment is from entity tags

The same rule that makes monitor onboarding zero-touch makes agent
configuration zero-touch: the profile is a **function of the entity's tags**,
never of a host list somebody maintains. A hand-kept host→profile mapping
decays the moment a VM is built by someone who does not know it exists.

Two facts feed assignment that do not come from the tagging standard's Tier 1:

- **`os_family`** is *derived*, from Datadog's own host metadata. It is not a
  tag anybody applies, because a hand-applied `os` tag would be a second and
  eventually wrong source of truth for something the agent already reports.
- **`db_engine`** is a new fleet tag, and it is required on datastore entities.
  `service_archetype: datastore` cannot tell SQL Server from Cosmos DB from
  Snowflake, and those need completely different agent configuration — or none
  at all. It selects a profile; no monitor query groups by it.

An entity missing the tags a profile matches on does **not** get that profile.
It gets `base-infrastructure` and a `tags_missing` finding. Guessing would be
worse: an untagged datastore silently assigned the SQL Server profile produces
a rollout that fails on hosts that were never SQL Server.

---

## 2 · How the agent reaches a host

Three delivery paths, by where the machine lives. Each one is chosen because
it is the mechanism that is *continuously true* rather than true on the day
somebody ran it.

### 2.1 Azure VMs — Azure Policy + the Datadog VM extension

**Mechanism.** A policy definition with a `deployIfNotExists` effect, assigned
at the **management group** scope, targeting `Microsoft.Compute/virtualMachines`
and installing the Datadog Agent extension (`DatadogWindowsAgent` /
`DatadogLinuxAgent`) when it is absent.

```jsonc
// Shape only — the definition itself lives in the landing-zone repository,
// which owns policy assignments and the managed identity that remediates.
{
  "if":  { "field": "type", "equals": "Microsoft.Compute/virtualMachines" },
  "then": {
    "effect": "deployIfNotExists",
    "details": {
      "type": "Microsoft.Compute/virtualMachines/extensions",
      "roleDefinitionIds": ["/providers/.../Virtual Machine Contributor"],
      "existenceCondition": { "field": "Microsoft.Compute/.../type",
                              "equals": "DatadogAgent" },
      "deployment": { /* ARM template; api_key from Key Vault reference */ }
    }
  }
}
```

**Why this and not a deployment script.** `deployIfNotExists` runs against VMs
that already exist (via a remediation task) *and* against every VM created
afterwards, forever, including ones created by teams who have never read this
document. A script covers the fleet as it was on the day it ran. Azure Policy is
also already the mechanism the tagging standard depends on for tag inheritance —
using one control plane for both is the difference between a rollout and a
permanent property.

**Prerequisites, in order.** Datadog API key in Key Vault (never in the
template, never in this repository) → a user-assigned managed identity with
Virtual Machine Contributor at the assignment scope → policy assigned in
**audit** mode first, so the population is known before anything is installed →
remediation task per subscription, in waves.

**Ownership.** cloud-engineering owns the assignment; observability-platform
owns the profile content and the compliance measurement.

### 2.2 VMware and on-prem — configuration management + golden image

Two halves, and both are needed.

**The golden image** carries the agent *binary* and nothing else — no API key,
no site, no tags. A key baked into a template is a credential you cannot rotate
and cannot revoke from a machine that has already been cloned a hundred times.
The image gets the package installed and the service **disabled**.

**Configuration management** (the estate's existing DSC / Ansible control) owns
everything specific to the machine: the API key from the secret store,
`datadog.yaml`, the `conf.d/*.d/conf.yaml` files for the assigned profile, and
the host tags. It runs on a schedule, which is what makes the configuration
converge rather than drift — an agent someone reconfigured by hand at 3am during
an incident is back on profile at the next run, and the change shows up as
remediated rather than as a mystery.

**Azure Arc is the preferred bridge.** On-prem servers onboarded to Azure Arc
accept the same VM extension as native Azure VMs, and the same Azure Policy
assignment covers them. Where Arc is available, use §2.1 and skip the
configuration-management path for installation — keep it for configuration.

**vCenter itself is not an agent target.** ESXi hosts run no third-party agent;
they are collected through the vSphere integration configured on one collector
host (which is itself a `linux-server`). `tools/fleet_compliance.py` therefore
excludes `esxi_host` from the denominator — counting them as agent-missing would
manufacture a permanent, unfixable gap and train people to ignore the number.

### 2.3 Manual installation — the exception, not a path

Manual installation is permitted only where §2.1 and §2.2 are both genuinely
unavailable: an isolated network, a vendor-managed appliance under support
constraints, a break-glass host during an incident.

When it happens, all four of these are required:

1. A recorded exception in `platform/policy/exceptions.yaml` with an owner and
   an expiry — the exception model already enforces a maximum lifetime.
2. The host tagged `install_method:manual`.
3. The same profile content as the automated path. A hand-installed agent that
   collects a different set of checks is worse than no agent, because the
   monitors covering it will return no data and look healthy.
4. A dated plan to bring the host onto an automated path, or into
   `fleet_exempt` with a reason.

A manual install with none of the above is not a fleet member. It is an agent
somebody put somewhere, and it will be the host nobody notices went silent.

---

## 3 · What the agent must be told

Independent of delivery path, every agent gets:

| Setting | Source | Why it is not optional |
|---|---|---|
| `api_key` | secret store, at configuration time | Never in an image, never in this repository |
| `tags` | the entity's Tier 1 tags | An untagged host is selected by no monitor, and no monitor will say so |
| `logs_enabled` | profile | Several archetypes read log-derived metrics |
| `apm_config.enabled` + `apm_non_local_traffic` | `application` profile | The application is a sibling process, not the agent's child |
| runtime metrics | `application` profile | The only source of `jvm.*` and `runtime.dotnet.*`; four archetypes read them |
| `dbm: true` + `tags: ["dbm:true"]` | `sqlserver` profile | Datadog exposes no host-level fact for "DBM is on", so the check configuration stamps one — otherwise the compliance report must guess about a capability the platform then claims |

The Windows agent runs under a managed service account. Local Administrator is
**not** required for any check in these profiles, and granting it turns a
monitoring agent into a lateral-movement path. On Linux the agent runs as
`dd-agent` with the `systemd-journal` supplementary group; running it as root
"so logs work" is the single most common Linux agent misconfiguration.

---

## 4 · Measuring it

```bash
cd tools
python fleet_compliance.py --fixtures ../tests/fixtures   # offline, CI and local
python fleet_compliance.py --live                          # the real estate
python fleet_compliance.py --live --min-compliance 95      # once it is a gate
```

**The denominator is the inventory, not the host list.** Computing agent
coverage from the hosts Datadog knows about always returns 100%, because a host
without an agent is not in that list. `build_inventory.py` supplies the required
set; the Datadog host list supplies evidence about the hosts that did report.

**A host counts once.** The eight checks in `agent_profiles.yaml` →
`compliance.checks` are:

| Check | What it catches |
|---|---|
| `agent_missing` | In the inventory, never reported. Nobody installed it |
| `agent_offline` | Reported once, silent for longer than `offline_after_minutes`. Somebody installed it and it stopped |
| `agent_out_of_date` | Below `minimum_agent_version`. Still reports, so nothing looks wrong — it just lacks checks the archetypes read |
| `integration_missing` | An assigned profile requires a check the host does not report. The most common real defect, and invisible to any rollout metric that counts installed agents |
| `dbm_missing` | SQL Server host with the integration but not Database Monitoring |
| `apm_missing` | Application host with no trace telemetry |
| `tags_missing` | Tier 1 tags absent or out of vocabulary |
| `ownership_missing` | No `team` resolving to `teams.yaml` — an alert with nowhere to go |

```
compliance % = hosts with ZERO findings / (inventory hosts − exempt) × 100
```

Per-finding weighting was rejected deliberately: it lets a fleet improve its
score without a single host becoming correct. The question the number answers is
"how much of the fleet is fully instrumented", and that question has a binary
answer per host.

**A denominator of zero is not 100%.** The report says `measured: false` and
states that nothing is known. Empty denominators have produced more false green
than any threshold ever has.

**It is report-only today, by decision.** The estate currently reports zero
agent-bearing hosts. Gating on a percentage before the first rollout wave would
produce a permanently red job that everybody learns to ignore, which costs more
than the gate is worth. `agent_profiles.yaml` → `compliance.ratio.report_targets`
records the target (95%), the current gate state (`false`) and the condition
under which it becomes a gate.

### Where it runs

The nightly governance loop (`.github/workflows/governance.yml`) rebuilds the
inventory and reports fleet compliance alongside the coverage report. The
offline path runs in CI on every pull request through `tests/test_fleet.py`,
against `tests/fixtures/fleet_inventory.json` + `fleet_hosts.json`.

---

## 5 · What this repository automates, and what it does not

The honest table. Everything in the left column is code in this repository that
runs and can fail; everything in the right column is a recommendation this
repository cannot execute.

| Automated here | Recommended, owned elsewhere |
|---|---|
| The five profiles as policy data, with the archetypes each one enables | Installing the agent on any machine |
| Profile assignment from entity tags (`fleet_compliance.assign_profiles`) | The Azure Policy definition and its assignment (landing-zone repo, cloud-engineering) |
| The eight compliance checks and the percentage | The configuration-management roles that render `datadog.yaml` and `conf.d/` |
| Detection of missing agents, stale agents, missing integrations, missing DBM/APM, missing tags and missing owners | The golden image build |
| The deployment-metadata contract, and this repository's own deployment events | Setting `DD_VERSION` in *application* pipelines (see `docs/tagging-standard.md` § Deployment metadata) |
| Alerting on agent health once telemetry exists (`host-agent-unhealthy`, `agent-version-drift`) | The API-key lifecycle in Key Vault |

**The load-bearing sentence:** this repository can tell you, precisely and by
name, which hosts are not instrumented and why. It cannot instrument them. Any
claim that "fleet management is implemented" that does not carry that
distinction is the same category of error as a monitor that returns no data and
reports healthy.

---

## 6 · Rollout

Waves, not a big bang, and each wave ends with a measurement rather than with a
declaration.

1. **Audit.** Assign the Azure Policy in audit mode. Run
   `fleet_compliance.py --live`. The output is the population and the baseline —
   the first honest number the platform has ever had for this.
2. **Non-production.** Remediate `dev`/`qa` subscriptions. Fix what the report
   says, not what the rollout plan assumed.
3. **Production infrastructure.** `base-infrastructure` + OS profiles only.
   Nothing that requires an application change.
4. **Roles.** `application` (needs the tracer and the pipeline variables) and
   `sqlserver` (needs the login and the DBM grants). These are the two waves
   that need another team's calendar, and they are where rollouts stall.
5. **Gate.** Once the measured percentage has exceeded 95% once, set
   `compliance.ratio.report_targets.gate: true` and add `--min-compliance` to
   the governance job.

Each wave's exit criterion is the same: the compliance report, not a change
ticket marked done.

---

## 7 · Ownership

| Concern | Owner |
|---|---|
| Profiles, compliance measurement, this standard | observability-platform |
| Azure Policy assignment, managed identity, Arc onboarding | cloud-engineering |
| Golden image, configuration management, on-prem installation | infrastructure-engineering |
| SQL login, DBM grants | data-engineering |
| `DD_VERSION` and git metadata in application pipelines | the owning application team |

Review cadence: quarterly, and on any change to `agent_profiles.yaml`. A fleet
standard nobody re-reads is a fleet standard that describes last year's estate.
