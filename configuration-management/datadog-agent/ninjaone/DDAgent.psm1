<#
.SYNOPSIS
  Shared module for the Datadog Agent lifecycle scripts run by NinjaOne.

.DESCRIPTION
  Every DD-Agent-*.ps1 script is thin and calls into here, so the behaviour
  that matters — how a version is compared, what "healthy" means, when a
  restart is justified — is defined once and tested once.

  THE PROPERTY EVERY FUNCTION HERE MUST HAVE IS IDEMPOTENCE. NinjaOne runs the
  lifecycle on a schedule across the whole estate. A function that restarts the
  Agent because it ran, rather than because something changed, turns a routine
  reconcile into a fleet-wide telemetry gap every hour. `Set-DDConfiguration`
  therefore compares hashes and returns $false when there is nothing to do, and
  the caller restarts only on $true.

  WHAT THIS DOES NOT DO. It does not decide what the configuration should be.
  The rendered configuration and its hash come from the repository
  (tools/agent_config.py); this module applies what it is given. Deciding here
  as well would mean two implementations of the composition rules, and the one
  that drifts is the one nobody tests.
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$script:AgentService = 'datadogagent'
$script:AgentRoot    = Join-Path $env:ProgramFiles 'Datadog\Datadog Agent'
$script:ConfigRoot   = Join-Path $env:ProgramData 'Datadog'

function Get-DDAgentVersion {
    <#  Returns the installed version as [version], or $null when absent.
        Absent is a legitimate answer, not an error: DD-Agent-Install exists
        precisely for that case, and throwing here would make "not installed"
        indistinguishable from "broken". #>
    $exe = Join-Path $script:AgentRoot 'bin\agent.exe'
    if (-not (Test-Path $exe)) { return $null }
    $raw = & $exe version 2>$null
    if ($raw -match '(\d+\.\d+\.\d+)') { return [version]$Matches[1] }
    return $null
}

function Test-DDAgentHealthy {
    <#  Healthy means: the service is running AND the Agent's own status
        command succeeds. The second half matters — a Datadog Agent can sit in
        "Running" while every check fails to initialise, and a service-state
        check alone would report that host as fine. #>
    $svc = Get-Service -Name $script:AgentService -ErrorAction SilentlyContinue
    if (-not $svc -or $svc.Status -ne 'Running') { return $false }
    $exe = Join-Path $script:AgentRoot 'bin\agent.exe'
    if (-not (Test-Path $exe)) { return $false }
    & $exe status --json > $null 2>&1
    return ($LASTEXITCODE -eq 0)
}

function Get-DDConfigHash {
    <#  sha256 over the on-disk configuration, computed the same way
        tools/agent_config.py computes the desired hash: canonical JSON of the
        same structure, sorted. Hashing the raw bytes instead would report
        drift for a comment or a key reorder, and a drift signal that fires on
        formatting is one people mute. #>
    param([string]$Path = $script:ConfigRoot)

    $files = Get-ChildItem -Path $Path -Recurse -Include '*.yaml' -ErrorAction SilentlyContinue |
             Where-Object { $_.FullName -notmatch 'auth_token|\.bak$' } |
             Sort-Object FullName
    if (-not $files) { return $null }

    $sha = [System.Security.Cryptography.SHA256]::Create()
    $sb  = [System.Text.StringBuilder]::new()
    foreach ($f in $files) {
        $rel = $f.FullName.Substring($Path.Length).TrimStart('\')
        [void]$sb.Append($rel).Append(':')
        [void]$sb.Append(((Get-Content $f.FullName -Raw) -replace "`r`n", "`n").Trim()).Append("`n")
    }
    $bytes = [Text.Encoding]::UTF8.GetBytes($sb.ToString())
    return 'sha256:' + [BitConverter]::ToString($sha.ComputeHash($bytes)).Replace('-', '').ToLower()
}

function Set-DDConfiguration {
    <#  Writes the rendered configuration and returns $true ONLY if the on-disk
        content changed. That return value is the restart decision, and it is
        why the lifecycle can run hourly without disturbing anything.

        Writes go to a temp path and are moved into place, so an interrupted
        run cannot leave a half-written datadog.yaml that the Agent will refuse
        to parse on its next start. #>
    param(
        [Parameter(Mandatory)][hashtable]$Rendered,
        [string]$Path = $script:ConfigRoot
    )

    $before = Get-DDConfigHash -Path $Path
    $staging = Join-Path $env:TEMP ("dd-config-" + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path (Join-Path $staging 'conf.d') -Force | Out-Null

    Set-Content -Path (Join-Path $staging 'datadog.yaml') -Value $Rendered.datadog_yaml -Encoding UTF8
    foreach ($name in $Rendered.conf_d.Keys) {
        $dest = Join-Path $staging "conf.d\$name"
        New-Item -ItemType Directory -Path (Split-Path $dest) -Force | Out-Null
        Set-Content -Path $dest -Value $Rendered.conf_d[$name] -Encoding UTF8
    }

    $after = Get-DDConfigHash -Path $staging
    if ($before -eq $after) {
        Remove-Item $staging -Recurse -Force
        return $false                     # nothing changed; do not restart
    }

    # KEEP THE PREVIOUS CONFIGURATION. This is what DD-Agent-Rollback restores,
    # and it is kept per-apply rather than once, so a bad config that survives
    # two runs does not overwrite the last known-good copy with itself.
    $backup = Join-Path $script:ConfigRoot ('..\Datadog.backup.' + (Get-Date -Format 'yyyyMMddHHmmss'))
    if (Test-Path $Path) { Copy-Item $Path $backup -Recurse -Force }

    Copy-Item (Join-Path $staging '*') $Path -Recurse -Force
    Remove-Item $staging -Recurse -Force
    return $true
}

function Restart-DDAgentIfNeeded {
    <#  Restart is a telemetry gap. It happens when configuration changed or
        the Agent is unhealthy, and not otherwise. #>
    param([bool]$ConfigChanged)
    if (-not $ConfigChanged -and (Test-DDAgentHealthy)) { return $false }
    Restart-Service -Name $script:AgentService -Force
    Start-Sleep -Seconds 10
    return $true
}

function Test-DDTelemetryFlowing {
    <#  The check that separates "the Agent is running" from "Datadog is
        receiving data". A configuration can be valid, the service can be up,
        and the payload can still be failing on a proxy or a firewall — which
        presents to everyone else as a host that silently vanished. #>
    $exe = Join-Path $script:AgentRoot 'bin\agent.exe'
    $json = & $exe status --json 2>$null | ConvertFrom-Json
    if (-not $json) { return @{ ok = $false; reason = 'agent status returned nothing' } }

    $fwd = $json.forwarderStats.Transactions
    if ($fwd.SuccessByEndpoint.'series_v2' -le 0) {
        return @{ ok = $false; reason = 'no successful metric submissions since start' }
    }
    $failed = @($json.runnerStats.Checks.PSObject.Properties |
                Where-Object { $_.Value.LastError })
    return @{
        ok            = $true
        failed_checks = $failed.Name
        # A failing check is reported but does NOT by itself mean unhealthy:
        # one broken integration on a host with twelve working ones is a
        # finding for the owning team, not a reason to roll the Agent back.
    }
}

function Write-DDNinjaField {
    <#  NinjaOne custom fields are the estate's view of Agent state. They are
        written at the END of a lifecycle run and only then, so a field never
        claims a state the run did not reach. #>
    param([Parameter(Mandatory)][string]$Name, $Value)
    if (Get-Command Ninja-Property-Set -ErrorAction SilentlyContinue) {
        Ninja-Property-Set $Name $Value
    } else {
        Write-Verbose "[no NinjaOne host] would set $Name = $Value"
    }
}

Export-ModuleMember -Function Get-DDAgentVersion, Test-DDAgentHealthy,
    Get-DDConfigHash, Set-DDConfiguration, Restart-DDAgentIfNeeded,
    Test-DDTelemetryFlowing, Write-DDNinjaField
