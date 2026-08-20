<#
.SYNOPSIS  Upgrade in place, validate, and roll back automatically on failure.
.DESCRIPTION
  The rollback is the point. An upgrade that fails validation and stays failed
  is worse than one that never ran, because the host is now BOTH broken and
  different from its ring.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][version]$TargetVersion,
    [Parameter(Mandatory)][version]$RollbackVersion,
    [int]$ValidateTimeoutSeconds = 180
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'DDAgent.psm1') -Force

$before = Get-DDAgentVersion
Write-Output "upgrading $before -> $TargetVersion"

& (Join-Path $PSScriptRoot 'DD-Agent-Install.ps1') -Version $TargetVersion `
    -ApiKeyHandle 'datadog_api_key'

# Wait for telemetry rather than for the service. A service that starts and
# then fails every check would pass an "is it running" test instantly, which is
# how a bad Agent release reaches a whole ring before anyone notices.
$deadline = (Get-Date).AddSeconds($ValidateTimeoutSeconds)
$ok = $false
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 15
    $t = Test-DDTelemetryFlowing
    if ((Test-DDAgentHealthy) -and $t.ok) { $ok = $true; break }
}

if (-not $ok) {
    Write-Warning "validation failed at $TargetVersion; rolling back to $RollbackVersion"
    & (Join-Path $PSScriptRoot 'DD-Agent-Rollback.ps1') -Version $RollbackVersion
    # Non-zero so the ring's failure counter increments. A rollback that
    # reports success is a rollback the promotion logic never learns from, and
    # the bad version keeps being offered to the next host.
    exit 1
}
Write-Output "upgraded and validated at $TargetVersion"
