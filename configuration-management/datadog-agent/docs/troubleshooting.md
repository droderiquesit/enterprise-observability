# Troubleshooting

## The Agent is unhealthy

```powershell
& "$env:ProgramFiles\Datadog\Datadog Agent\bin\agent.exe" status
.\DD-Agent-Validate.ps1 -ExpectedConfigVersion <hash> -ExpectedAgentVersion 7.66.1
```

`DD-Agent-Validate` changes nothing, so it is safe during a change freeze.

**"Running" is not "healthy."** An Agent can sit in Running while every check
fails to initialise. `Test-DDAgentHealthy` requires the service state *and* a
successful `agent status`, and `Test-DDTelemetryFlowing` additionally requires
a successful submission — a valid config with a blocked proxy presents to
everyone else as a host that silently vanished.

## Drift

```powershell
Get-DDConfigHash                      # installed
python tools/agent_config.py --node <name> | grep config_version   # desired
```

Different → `DD-Agent-Reconcile.ps1`. The hash covers canonical content, so a
comment or key reorder is not drift.

## A check is failing but the host is compliant

Deliberate. One broken integration on a host with twelve working ones is a
finding for the owning team, not a reason to mark the host non-compliant and
trigger a rollback. The failing check names land in `DatadogFailedChecks`.

## An upgrade rolled back

Expected behaviour, and the ring's failure counter has incremented. Look at
whether the same version failed on other hosts in the ring: one host is a host
problem, several is a release problem and the ring should not be promoted.

## Reconciliation keeps failing

After 3 attempts it stops and sets `DatadogStatus: remediation-failed`. It does
not keep trying — an unbounded retry is a permanent telemetry gap presented as
self-healing. Usual causes: a corrupt MSI cache (`msiexec /unregister` then
re-register), a locked `datadog.yaml` from a running process, or a secrets
backend that cannot authenticate (check the managed identity's Key Vault
access, not the Agent).

## Known limitation

The PowerShell in `ninjaone/` is checked statically, not parsed — there is no
PowerShell interpreter in CI. Tests assert no 7.0-only syntax, StrictMode set,
balanced braces, and that every check the ring gate claims is implemented. A
PSScriptAnalyzer pass on a Windows runner would be strictly better and is not
in place.
