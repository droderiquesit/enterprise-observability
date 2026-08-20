<#
.SYNOPSIS  Report what this host runs, so a profile can be chosen for it.
.DESCRIPTION
  Detection only — it assigns nothing. What it finds becomes NinjaOne custom
  fields; the profile decision is made against
  platform/policy/agent_profiles.yaml, which is the catalog the whole platform
  shares.

  OWNERSHIP IS NOT INFERRED. Detecting IIS tells you a host serves HTTP; it
  does not tell you which service or team owns it, and guessing that from a
  hostname is how two applications end up merged in the Service Catalog.
  Those stay manual fields, deliberately.
#>
[CmdletBinding()] param()
Set-StrictMode -Version Latest
# Stop on error even though this script only reads. A discovery run that hits
# an unexpected failure and CONTINUES reports partial findings as complete —
# and a missing `sqlserver` because one Get-Service threw is a host that
# silently never gets the SQL profile.
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'DDAgent.psm1') -Force

$found = [ordered]@{
    os               = 'windows'
    iis              = [bool](Get-Service W3SVC -ErrorAction SilentlyContinue)
    sqlserver        = [bool](Get-Service MSSQLSERVER -ErrorAction SilentlyContinue)
    tomcat           = [bool](Get-Service -Name 'Tomcat*' -ErrorAction SilentlyContinue)
    java_process     = [bool](Get-Process java -ErrorAction SilentlyContinue)
    agent_installed  = [bool](Get-DDAgentVersion)
    agent_version    = $(if (Get-DDAgentVersion) { (Get-DDAgentVersion).ToString() })
}

# Suggested profiles, as a RECOMMENDATION written to a field a human can see
# and override. Auto-applying would mean a detection false positive silently
# changes what a production host collects.
$suggested = @('windows-standard')
if ($found.iis)       { $suggested += @('application', 'iis') }
if ($found.sqlserver) { $suggested += 'sqlserver' }
if ($found.tomcat)    { $suggested += @('application', 'tomcat') }

$found['suggested_profiles'] = ($suggested | Select-Object -Unique) -join ','
Write-DDNinjaField 'DatadogDiscoveredWorkloads' ($found | ConvertTo-Json -Compress)
$found | ConvertTo-Json -Depth 3
