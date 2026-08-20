<#
.SYNOPSIS  Return an Agent to a known-good version AND its previous config.
.DESCRIPTION
  Both halves matter. Rolling the binary back while leaving a new
  configuration in place produces a combination that was never tested
  anywhere — an old Agent reading config written for a newer one.
#>
[CmdletBinding()]
param([Parameter(Mandatory)][version]$Version)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'DDAgent.psm1') -Force

# The most recent backup Set-DDConfiguration took, if there is one. Absence is
# not fatal: a first-install failure has no previous config to restore, and
# refusing to roll the binary back for that reason would strand the host.
$backup = Get-ChildItem (Join-Path $env:ProgramData '.') -Directory `
            -Filter 'Datadog.backup.*' -ErrorAction SilentlyContinue |
          Sort-Object Name -Descending | Select-Object -First 1

& (Join-Path $PSScriptRoot 'DD-Agent-Install.ps1') -Version $Version `
    -ApiKeyHandle 'datadog_api_key'

if ($backup) {
    Copy-Item (Join-Path $backup.FullName '*') (Join-Path $env:ProgramData 'Datadog') `
        -Recurse -Force
    Write-Output "restored configuration from $($backup.Name)"
} else {
    Write-Warning 'no previous configuration to restore; binary rolled back only'
}

Restart-Service -Name 'datadogagent' -Force
Start-Sleep -Seconds 15
if (-not (Test-DDAgentHealthy)) { throw "rollback to $Version did not produce a healthy Agent" }
Write-Output "rolled back to $Version"
