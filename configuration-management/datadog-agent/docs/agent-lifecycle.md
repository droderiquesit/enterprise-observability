# Agent lifecycle

One scheduled script, `DD-Agent-Lifecycle.ps1`, runs every stage in order.

```
discover → desired state → install → upgrade → configure → validate
         → restart ONLY if config changed → verify telemetry → report
```

**Why one script rather than seven schedules.** Seven independently scheduled
scripts race each other: configure runs while upgrade is mid-install, validate
reports a version install is about to change, and the end state depends on
which finished first. One ordered pass has one outcome.

**Why it is safe to run hourly across the whole estate.** Every stage is a
no-op when its precondition is already met. On a compliant host the lifecycle
performs no writes and no restart, because `Set-DDConfiguration` compares
hashes and returns `$false` when nothing changed. A restart on every run would
be a fleet-wide telemetry gap every hour, dressed up as reconciliation.

## Exit codes

| | |
|---|---|
| `0` | Compliant, or successfully remediated |
| `1` | Remediation attempted and failed — actionable, routed by NinjaOne |
| `2` | Out of scope (`DatadogEnabled` false). Exits explicitly rather than doing nothing silently, which would be indistinguishable from the script never running |

## Where the rendered configuration comes from

CI renders it (`tools/agent_config.py`) and NinjaOne delivers it as a script
variable. **The script does not render.** Rendering on the host would put a
second implementation of the composition rules on ten thousand machines, and
the one that drifts is the one nobody tests.

## Upgrades

`DD-Agent-Upgrade.ps1` installs the target, then waits for **telemetry**, not
for the service. A service that starts and then fails every check would pass an
"is it running" test instantly — which is how a bad Agent release reaches a
whole ring before anyone notices. If validation does not pass within the
timeout it rolls back automatically and **exits non-zero**, so the ring's
failure counter increments; a rollback that reported success would be one the
promotion logic never learns from, and the bad version would keep being offered
to the next host.

Rollback restores **both** the binary and the previous configuration. Rolling
the binary back alone leaves an old Agent reading config written for a newer
one — a combination that was never tested anywhere.

## Self-healing is bounded

`DD-Agent-Reconcile.ps1` retries up to `MaxAttempts` (3) with linear backoff,
then stops and reports. An unbounded retry on a host that cannot be fixed — a
corrupt MSI cache, a locked file — restarts the Agent every cycle forever,
which is a permanent telemetry gap presented as self-healing. Backoff is linear
rather than exponential so the third attempt still fits inside the window
NinjaOne allows a script to run.

## Drift

`config_version` is a sha256 over the canonical rendered configuration.
Desired lives in Git, installed is computed on the host from the same
structure, and a mismatch is what `DD-Agent-Reconcile` acts on. The hash is
computed over sorted canonical content rather than raw bytes, so a comment or a
key reorder does not report as drift — a drift signal that fires on formatting
is one people mute.
