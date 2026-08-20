<#
.SYNOPSIS  Apply rendered configuration and restart only if it changed.
.DESCRIPTION
  Exists as its own entry point so a configuration change can be pushed
  without running install/upgrade — the common case during an incident, when
  the last thing anyone wants is an Agent version changing as well.
#>
[CmdletBinding()]
param([Parameter(Mandatory)][string]$RenderedConfigJson)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'DDAgent.psm1') -Force

$desired = $RenderedConfigJson | ConvertFrom-Json
$changed = Set-DDConfiguration -Rendered @{
    datadog_yaml = $desired.datadog_yaml
    conf_d       = $desired.conf_d
}
$restarted = Restart-DDAgentIfNeeded -ConfigChanged $changed

Write-DDNinjaField 'DatadogConfigVersion' (Get-DDConfigHash)
[ordered]@{ changed = $changed; restarted = $restarted;
            config_version = (Get-DDConfigHash) } | ConvertTo-Json
