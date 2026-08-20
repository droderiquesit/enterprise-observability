<#
.SYNOPSIS  Install the Datadog Agent at a pinned version.
.DESCRIPTION
  Idempotent: if the requested version is already installed it exits 0 without
  touching anything, because the lifecycle calls this whenever the Agent is
  absent and "absent" can be a race with a previous run still finishing.

  THE API KEY IS NEVER AN ARGUMENT. The installer needs one, and a key passed
  on a command line lands in the NinjaOne activity log, the local event log and
  the process table. It is fetched from the secrets backend into a variable
  that lives for the length of the call and is cleared after.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][version]$Version,
    [Parameter(Mandatory)][string]$ApiKeyHandle,
    [string]$Site = 'datadoghq.com'
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'DDAgent.psm1') -Force

$installed = Get-DDAgentVersion
if ($installed -eq $Version) { Write-Output "already at $Version"; exit 0 }

$msi = Join-Path $env:TEMP "datadog-agent-$Version.msi"
$url = "https://s3.amazonaws.com/ddagent-windows-stable/ddagent-cli-$Version.msi"

# Downloaded to a versioned filename so a partial download from a previous run
# cannot be mistaken for a complete one.
Invoke-WebRequest -Uri $url -OutFile $msi -UseBasicParsing

$apiKey = $null
try {
    $apiKey = & (Join-Path $env:ProgramFiles 'Datadog\secrets\datadog-secrets.exe') $ApiKeyHandle
    if (-not $apiKey) { throw "secrets backend returned nothing for $ApiKeyHandle" }

    # /qn silent, and APIKEY passed as an MSI property rather than written into
    # a config file the installer then reads — the property is scrubbed from
    # the MSI log by the installer itself.
    $args = @('/i', "`"$msi`"", '/qn', "APIKEY=$apiKey", "SITE=$Site",
              'HOSTNAME_FQDN_ENABLED=true')
    $p = Start-Process msiexec.exe -ArgumentList $args -Wait -PassThru -NoNewWindow
    if ($p.ExitCode -ne 0) { throw "msiexec exited $($p.ExitCode)" }
}
finally {
    # Clear the key from memory and remove the installer. Neither is perfect
    # protection, but leaving either behind is a finding nobody should have to
    # write up twice.
    if ($apiKey) { $apiKey = $null; [GC]::Collect() }
    Remove-Item $msi -Force -ErrorAction SilentlyContinue
}

$now = Get-DDAgentVersion
if ($now -ne $Version) { throw "install reported success but version is $now" }
Write-Output "installed $Version"
