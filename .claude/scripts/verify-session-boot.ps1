# verify-session-boot.ps1 - Detached one-shot transcript-persistence watcher.
#
# Spawned hidden by spawn-session-tab.ps1 for every orchestrated tab, right before claude boots.
# Covers the two failure modes the Stop hook cannot:
#   (1) the SessionStart hook never fired (not registered / wrong cwd) -> no <Id>.session ever
#       appears. Without this watcher that silence is invisible.
#   (2) a session that boots but never completes a turn (so Stop never fires) yet whose transcript
#       was never written.
#
# Waits for <StateDir>\gate\<Id>.session, then (after a grace period) confirms the recorded
# transcript path exists. Emits gate-log lines, a marker, and one desktop toast on trouble.
# Shares the <Id>.transcript-missing debounce marker with the Stop hook, so the two never
# double-toast. Runs to a single verdict and exits; always exit 0.

param(
    [Parameter(Mandatory = $true)] [string]$Id,
    [Parameter(Mandatory = $true)] [string]$StateDir,
    [int]$TimeoutSec = 120,
    [int]$GraceSec   = 20,
    [int]$RecheckSec = 20,
    [string]$NotifyScript = ''
)

$gateDir = Join-Path $StateDir 'gate'

function Write-Log {
    param([string]$Message)
    try {
        if (-not (Test-Path -LiteralPath $gateDir)) { New-Item -ItemType Directory -Path $gateDir -Force | Out-Null }
        $stamp = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
        Add-Content -LiteralPath (Join-Path $gateDir ($Id + '.gate.log')) -Value ("{0} {1}" -f $stamp, $Message) -Encoding Ascii
    } catch {}
}

function Resolve-Notify {
    param([string]$Explicit)
    if ($Explicit) { return $Explicit }
    if ($env:CLAUDE_HOOK_NOTIFY_SCRIPT) { return $env:CLAUDE_HOOK_NOTIFY_SCRIPT }
    $sib = Join-Path $PSScriptRoot 'notify-desktop.ps1'
    if (Test-Path -LiteralPath $sib) { return $sib }
    return (Join-Path $env:USERPROFILE '.claude\scripts\notify-desktop.ps1')
}

function Send-Toast {
    param([string]$Title, [string]$Body)
    try {
        $ns = Resolve-Notify $NotifyScript
        if ($ns -and (Test-Path -LiteralPath $ns)) {
            # Single explicitly-quoted command line: Start-Process -ArgumentList does not quote
            # array elements, so space-bearing values (and stray '-' tokens) would corrupt or break
            # the child invocation.
            $q = { param($s) '"' + ([string]$s -replace '"', "'") + '"' }
            $argline = '-NoProfile -ExecutionPolicy Bypass -File {0} -Kind failed -Title {1} -Body {2}' -f `
                (& $q $ns), (& $q $Title), (& $q $Body)
            Start-Process -FilePath 'powershell.exe' -WindowStyle Hidden -ArgumentList $argline | Out-Null
        }
    } catch {}
}

try {
    $sessFile = Join-Path $gateDir ($Id + '.session')

    # (1) Wait for the SessionStart capture to appear.
    $waited = 0
    while ((-not (Test-Path -LiteralPath $sessFile)) -and ($waited -lt $TimeoutSec)) {
        Start-Sleep -Seconds 2
        $waited += 2
    }
    if (-not (Test-Path -LiteralPath $sessFile)) {
        Write-Log ("HOOK-SILENT after {0}s - SessionStart hook not registered or not firing (no .session)" -f $waited)
        $hm = Join-Path $gateDir ($Id + '.hook-missing')
        if (-not (Test-Path -LiteralPath $hm)) {
            try { Set-Content -LiteralPath $hm -Value ((Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')) -Encoding Ascii } catch {}
            Send-Toast ('Session capture NOT running: ' + $Id) 'SessionStart hook never fired - transcript is unmonitored. Check .claude/settings.json hooks.'
        }
        exit 0
    }

    # (2) Capture exists - give the async transcript writer time, then confirm the file.
    $tp = ''
    try { $tp = [string]((Get-Content -LiteralPath $sessFile -Raw | ConvertFrom-Json).transcriptPath) } catch {}
    Start-Sleep -Seconds $GraceSec

    $present = $false
    for ($i = 0; $i -lt 3; $i++) {
        if ($tp -and (Test-Path -LiteralPath $tp)) { $present = $true; break }
        Start-Sleep -Seconds $RecheckSec
    }

    if ($present) {
        Write-Log ("TRANSCRIPT-OK boot path={0}" -f $tp)
        exit 0
    }

    Write-Log ("TRANSCRIPT-MISSING boot path={0}" -f $tp)
    $marker = Join-Path $gateDir ($Id + '.transcript-missing')
    if (-not (Test-Path -LiteralPath $marker)) {
        try { Set-Content -LiteralPath $marker -Value ((Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ') + " boot uuid path=" + $tp) -Encoding Ascii } catch {}
        Send-Toast ('Transcript MISSING: ' + $Id) ('Not on disk: ' + $tp + ' . Open the tab and /export session-logs/logs/<name>.txt NOW.')
    }
} catch {}

exit 0
