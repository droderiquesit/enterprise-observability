<#
.SYNOPSIS  Bring one host back to its desired configuration.
.DESCRIPTION
  Self-healing (§12) with a BOUNDED number of attempts. An unbounded retry on a
  host that cannot be fixed — a corrupt MSI cache, a locked file, a missing
  dependency — restarts the Agent every cycle forever, which is a permanent
  telemetry gap dressed up as remediation.

  After MaxAttempts it stops trying and reports, so a human sees one actionable
  failure instead of a host that has been "self-healing" for three weeks.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$RenderedConfigJson,
    [int]$MaxAttempts = 3
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'DDAgent.psm1') -Force

$attempt = 0
$healthy = $false
while ($attempt -lt $MaxAttempts -and -not $healthy) {
    $attempt++
    Write-Output "reconcile attempt $attempt/$MaxAttempts"
    try {
        & (Join-Path $PSScriptRoot 'DD-Agent-Lifecycle.ps1') `
            -RenderedConfigJson $RenderedConfigJson | Out-Null
        $healthy = ($LASTEXITCODE -eq 0)
    } catch {
        Write-Warning "attempt $attempt failed: $($_.Exception.Message)"
    }
    # Linear backoff. Exponential would push the third attempt past the window
    # NinjaOne allows a script to run, turning a bounded retry into a timeout.
    if (-not $healthy) { Start-Sleep -Seconds (20 * $attempt) }
}

Write-DDNinjaField 'DatadogReconcileAttempts' $attempt
if (-not $healthy) {
    Write-DDNinjaField 'DatadogStatus' 'remediation-failed'
    # Exit 1 is what NinjaOne conditions on to raise a ticket. The platform
    # routes it the same way any other actionable finding is routed; this
    # script does not talk to ServiceNow or Teams directly.
    throw "reconciliation failed after $MaxAttempts attempts"
}
Write-Output "reconciled after $attempt attempt(s)"
