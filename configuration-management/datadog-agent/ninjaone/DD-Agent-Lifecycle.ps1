<#
.SYNOPSIS
  The one script NinjaOne schedules. Everything else is a stage inside it.

.DESCRIPTION
  Discover -> desired state -> install -> upgrade -> configure -> validate ->
  restart only if needed -> verify telemetry -> report.

  WHY ONE SCRIPT AND NOT SEVEN SCHEDULES. Seven independently scheduled scripts
  race: configure runs while upgrade is mid-install, validate reports a version
  that install is about to change, and the resulting state depends on which
  finished first. One ordered pass has one outcome.

  IT IS SAFE TO RUN HOURLY. Every stage is a no-op when its precondition is
  already met — the Agent is installed, the version matches, the config hash
  matches. A run on a compliant host performs no writes and no restart, which
  is what makes "run it everywhere on a schedule" a reasonable thing to do.

  EXIT CODES are what NinjaOne conditions on:
    0  compliant, or successfully remediated
    1  remediation attempted and failed — actionable, routed
    2  skipped: this device is not in scope (DatadogEnabled is false)
#>
[CmdletBinding()]
param(
    # The rendered configuration for THIS node, produced by
    # tools/agent_config.py in CI and delivered as a NinjaOne script variable
    # or artifact. The script does not render — rendering here would put a
    # second implementation of the composition rules on ten thousand hosts.
    [Parameter(Mandatory)][string]$RenderedConfigJson,
    [switch]$WhatIf
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'DDAgent.psm1') -Force

$result = [ordered]@{
    stage = 'start'; installed = $false; upgraded = $false
    configured = $false; restarted = $false; healthy = $false
    config_version = $null; agent_version = $null; failures = @()
}

try {
    $desired = $RenderedConfigJson | ConvertFrom-Json

    # ---- 0. SCOPE -----------------------------------------------------------
    # A device outside scope exits 2 and writes nothing. Silently doing nothing
    # would be indistinguishable from the script failing to run at all.
    if ($desired.enabled -eq $false) {
        Write-DDNinjaField 'DatadogStatus' 'out-of-scope'
        exit 2
    }

    # ---- 1. DISCOVER --------------------------------------------------------
    $result.stage = 'discover'
    $installed = Get-DDAgentVersion
    $target    = [version]$desired.target_version
    $minimum   = [version]$desired.minimum_version

    # ---- 2. INSTALL ---------------------------------------------------------
    if (-not $installed) {
        $result.stage = 'install'
        if (-not $WhatIf) {
            & (Join-Path $PSScriptRoot 'DD-Agent-Install.ps1') `
                -Version $target -ApiKeyHandle $desired.api_key_handle
        }
        $installed = Get-DDAgentVersion
        $result.installed = $true
    }

    # ---- 3. UPGRADE ---------------------------------------------------------
    # Upgrade when BELOW the ring's target. Deliberately not "when different":
    # a host ahead of its ring is a canary that has not been promoted yet, and
    # downgrading it would undo the soak this whole ring model exists to run.
    if ($installed -and $installed -lt $target) {
        $result.stage = 'upgrade'
        if (-not $WhatIf) {
            & (Join-Path $PSScriptRoot 'DD-Agent-Upgrade.ps1') `
                -TargetVersion $target -RollbackVersion $desired.rollback_version
        }
        $result.upgraded = $true
        $installed = Get-DDAgentVersion
    }
    elseif ($installed -and $installed -lt $minimum) {
        # Below minimum and not below target means the target itself is stale.
        # A host cannot fix that; it is a policy problem, so it is reported
        # rather than remediated into a loop.
        $result.failures += "installed $installed is below minimum $minimum but target is $target"
    }

    # ---- 4. CONFIGURE -------------------------------------------------------
    $result.stage = 'configure'
    $changed = $false
    if (-not $WhatIf) {
        $changed = Set-DDConfiguration -Rendered @{
            datadog_yaml = $desired.datadog_yaml
            conf_d       = $desired.conf_d
        }
    }
    $result.configured = $changed

    # ---- 5. RESTART, ONLY IF SOMETHING CHANGED ------------------------------
    if (-not $WhatIf) { $result.restarted = Restart-DDAgentIfNeeded -ConfigChanged $changed }

    # ---- 6. VALIDATE --------------------------------------------------------
    $result.stage = 'validate'
    if (-not (Test-DDAgentHealthy)) {
        $result.failures += 'agent service is not running or status failed'
    }
    $telemetry = Test-DDTelemetryFlowing
    if (-not $telemetry.ok) { $result.failures += "telemetry: $($telemetry.reason)" }
    elseif ($telemetry.failed_checks) {
        # Reported, not failed. One broken integration on a host with twelve
        # working ones is a finding for the owning team, not a reason to mark
        # the host non-compliant and trigger a rollback.
        Write-DDNinjaField 'DatadogFailedChecks' ($telemetry.failed_checks -join ',')
    }

    if ($installed) { $result.agent_version = $installed.ToString() }
    $result.config_version = Get-DDConfigHash
    $result.healthy        = ($result.failures.Count -eq 0)
    $result.stage          = 'done'
}
catch {
    # The stage is recorded so a failure says WHERE it stopped. "The lifecycle
    # failed" sends someone reading the whole script; "failed at upgrade" does
    # not.
    $result.failures += "$($result.stage): $($_.Exception.Message)"
    $result.healthy = $false
}
finally {
    # Fields are written LAST and always, including on failure — a device whose
    # run threw is exactly the device whose status must not still read
    # "healthy" from yesterday.
    # Explicit rather than an inline conditional: this runs in a `finally`
    # after a possible throw, and the default must be the pessimistic one. If
    # anything about evaluating the condition fails, the field reads 'failed'
    # rather than being left at whatever it said yesterday.
    $status = 'failed'; if ($result.healthy) { $status = 'compliant' }
    Write-DDNinjaField 'DatadogStatus'         $status
    Write-DDNinjaField 'DatadogVersion'        $result.agent_version
    Write-DDNinjaField 'DatadogConfigVersion'  $result.config_version
    Write-DDNinjaField 'DatadogLastValidation' (Get-Date -Format 'o')
    $result | ConvertTo-Json -Depth 4
}

if ($result.healthy) { exit 0 } else { exit 1 }
