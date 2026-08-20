# Datadog Agent configuration management

Agent installation, configuration, upgrade and validation as code. Git holds
the desired state; **NinjaOne applies it**; Datadog receives the telemetry.

The property this exists to preserve: **adding the ten-thousandth server
creates no file here.** A node declares a handful of facts and its
configuration is composed from layers that were each reviewed once.

---

## The boundary, stated first

Two directories talk about agent profiles and they answer different questions.
Confusing them is how this becomes two competing systems.

| | Question | Owns |
|---|---|---|
| `platform/policy/agent_profiles.yaml` | **Which** profile does this host get, and why? | Profile catalog, `match` rules, what each profile enables, fleet compliance |
| `configuration-management/datadog-agent/` (here) | **What configuration** does that profile render to? | `datadog.yaml`, `conf.d`, log rules, rings, secrets handles, NinjaOne automation |

They are linked by profile id and `tools/validate_policy.py` fails the build if
the two disagree — including if the minimum agent version is declared
differently in each.

---

## How a configuration is composed

```
base → os → profile(s) → environment → criticality → node → exception
```

Later layers may add keys and may override a key an earlier one set. Nothing
reaches backwards. Two rules make this safe:

- **Lists concatenate, scalars replace.** A profile adding a `windows_service`
  instance must not erase the one the OS layer added, or composing two profiles
  would silently drop a check with nothing failing.
- **A feature needs policy AND capability.** The environment/criticality layers
  decide whether logs, APM or DBM are *allowed*; a profile's `supports:` list
  decides whether anything present can *use* them. Both must agree — which is
  why a tier1 VMware poller does not get APM enabled, and an APM host licence
  consumed, for an application it does not run.

```bash
make agent-render                       # render every representative node
python tools/agent_config.py --node win-app-01 --explain    # which layer set what
python tools/agent_config.py --check    # validate; non-zero on any problem
```

`--explain` answers "why does this host have that setting?" without reading
seven files in the right order.

---

## What is here

| Path | |
|---|---|
| `config/base.yaml` | Global agent configuration |
| `config/os/` | `windows`, `linux` baselines |
| `config/profiles/` | Workload profiles — sqlserver, iis, tomcat, serilog, application, vmware-poller, database-poller, synthetic-private-location |
| `config/profiles/azure-managed-databases.yaml` | Azure SQL and Cosmos DB — **installs nothing**; explains why there is no Agent and what carries the telemetry instead |
| `policies/` | environments, criticality, rollout rings + version pins, secret handles |
| `ninjaone/` | `DD-Agent-Lifecycle.ps1` and the stages it calls |
| `nodes/` | The representative examples CI renders. **Not an inventory** |
| `docs/` | Operational documentation |

---

## Adding things

**A server.** Nothing here. It appears in NinjaOne, its custom fields carry the
same facts a `nodes/` file carries, the lifecycle renders and applies. See
[docs/agent-lifecycle.md](docs/agent-lifecycle.md).

**An application to an existing host.** Add the profile to the node's
`DatadogProfile` field — `windows-standard,application,iis,serilog`. No new
file.

**A workload type nothing covers.** One file in `config/profiles/`, with a
`catalog_profile` pointing at its `agent_profiles.yaml` entry and a `supports:`
list. Add a node to `nodes/` **only** if you are adding a CI render test.

**A database to the central poller.** One instance block on the poller node, up
to the cap in `config/profiles/database-poller.yaml`. Past the cap, add a
poller — the cap is what bounds the failure domain, so raising it defeats its
purpose.

---

## Secrets

None, ever. Rendered configuration contains `ENC[handle]`; the Agent's secret
backend resolves it at start-up and is the only component that sees a value.
That is what makes a rendered config safe to commit, diff, hash for drift
detection and paste into a ticket. `policies/secrets.yaml` lists the handles,
their owners and rotation periods. CI greps every rendered config for key
material and fails on a hit.

---

## Known gaps

Recorded here rather than discovered later:

- **The PowerShell is statically checked, not parsed.** There is no PowerShell
  interpreter in CI, so `tests/test_agent_config.py` asserts specific
  properties (no 7.0-only syntax, StrictMode set, braces balanced, every check
  the ring gate claims is implemented). A PSScriptAnalyzer pass on a Windows
  runner would be strictly better.
- **No node has been reconciled against a real host.** The scripts are
  unexercised against a live Agent; the render pipeline and its guardrails are
  fully tested.
- **Synthetic private locations define no locations.** Fabricating one would
  produce tests that never run and report as healthy.
