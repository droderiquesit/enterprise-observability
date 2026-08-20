<#
.SYNOPSIS  Prove this host is compliant. Changes nothing.
.DESCRIPTION
  The read-only half of the lifecycle, separated so it can be scheduled more
  often than reconciliation and run during a change freeze. Its check list is
  policies/rollout-rings.yaml -> upgrade_validation, and a name there that this
  script does not implement fails the repository lint — so the promotion gate
  cannot quietly be weaker than it claims.
#>
[CmdletBinding()]
param([string]$ExpectedConfigVersion, [version]$ExpectedAgentVersion)
Set-StrictMode -Version Latest
Import-Module (Join-Path $PSScriptRoot 'DDAgent.psm1') -Force

$checks = [ordered]@{}
$v = Get-DDAgentVersion

$checks['agent_service_running']   = (Test-DDAgentHealthy)
$checks['agent_version_matches']   = (-not $ExpectedAgentVersion) -or ($v -eq $ExpectedAgentVersion)
$checks['config_valid']            = $null -ne (Get-DDConfigHash)

$t = Test-DDTelemetryFlowing
$checks['datadog_connectivity']    = $t.ok
$checks['expected_checks_healthy'] = $t.ok -and (-not $t.failed_checks)
$checks['host_metrics_arriving']   = $t.ok

# Config drift (§22): the desired hash comes from Git, the installed hash from
# disk. A mismatch is not an error here — it is the signal DD-Agent-Reconcile
# acts on — so it is reported separately from the pass/fail set.
$installedHash = Get-DDConfigHash
$drift = $ExpectedConfigVersion -and ($installedHash -ne $ExpectedConfigVersion)

$failed = @($checks.GetEnumerator() | Where-Object { -not $_.Value } | ForEach-Object { $_.Key })
[ordered]@{
    healthy         = ($failed.Count -eq 0)
    failed_checks   = $failed
    drift           = [bool]$drift
    installed_hash  = $installedHash
    expected_hash   = $ExpectedConfigVersion
    agent_version   = $(if ($v) { $v.ToString() })
} | ConvertTo-Json -Depth 3

if ($failed.Count -eq 0) { exit 0 } else { exit 1 }
