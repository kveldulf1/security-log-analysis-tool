# check-transcript-stop.ps1 - Claude Code Stop hook.
#
# Fires at the end of every turn and verifies the session's transcript .jsonl actually exists on
# disk. This is the guard against the logwarden incident: spawned tabs whose main transcript was
# never written were only discovered post-crash. Now a miss is caught on the FIRST turn, while the
# session is still open and recoverable, and the operator is told to /export immediately.
#
# On a miss: append a TRANSCRIPT-MISSING line to the log, drop a <...>.transcript-missing marker,
# and fire ONE desktop toast (debounced by the marker's existence - re-armed only after recovery).
# All sinks live in the orchestration gate dir when orchestrated, else ~/.claude/logs.
#
# CONTRACTS:
#   - ALWAYS exit 0. A non-zero (especially 2) exit from a Stop hook interferes with stopping.
#   - Keep the happy path well under 2s: one Test-Path, no blocking on the detached toast.
#
# Params exist for the unit tests (mock notifier + redirected user log dir); production passes none.

param(
    [string]$NotifyScript = '',
    [string]$UserLogDir   = ''
)

try {
    $raw = [Console]::In.ReadToEnd()
    $p = $null
    try { $p = $raw | ConvertFrom-Json } catch { $p = $null }
    if ($null -eq $p) { exit 0 }

    $sid = [string]$p.session_id
    $tp  = [string]$p.transcript_path
    $cwd = [string]$p.cwd
    $label = $env:CLAUDE_SESSION_LABEL
    $stateDir = $env:CLAUDE_ORCH_STATE_DIR

    if ($label -and $stateDir) {
        $base    = Join-Path $stateDir 'gate'
        $marker  = Join-Path $base ($label + '.transcript-missing')
        $logFile = Join-Path $base ($label + '.gate.log')
        $display = $label
    } else {
        if (-not $UserLogDir) { $UserLogDir = Join-Path $env:USERPROFILE '.claude\logs' }
        $base    = $UserLogDir
        $marker  = Join-Path $base ('transcript-missing-' + $sid + '.marker')
        $logFile = Join-Path $base 'transcript-guard.log'
        $leaf = ''
        if ($cwd) { $leaf = Split-Path -Leaf $cwd }
        $uuid8 = ''
        if ($sid) { $uuid8 = $sid.Substring(0, [Math]::Min(8, $sid.Length)) }
        $display = ($leaf + '-' + $uuid8)
    }

    # Transcript present? Re-check once after a short grace: the transcript is written
    # asynchronously and may lag the in-memory conversation when the hook fires.
    $present = $false
    if ($tp) {
        $present = Test-Path -LiteralPath $tp
        if (-not $present) { Start-Sleep -Milliseconds 500; $present = Test-Path -LiteralPath $tp }
    }

    $utc = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
    if (-not (Test-Path -LiteralPath $base)) { New-Item -ItemType Directory -Path $base -Force | Out-Null }

    if ($present) {
        # Clear a stale alarm and re-arm, so a genuine later relapse toasts again.
        if (Test-Path -LiteralPath $marker) {
            Remove-Item -LiteralPath $marker -Force -ErrorAction SilentlyContinue
            try { Add-Content -LiteralPath $logFile -Value ("{0} TRANSCRIPT-RECOVERED uuid={1} path={2}" -f $utc, $sid, $tp) -Encoding Ascii } catch {}
        }
        exit 0
    }

    try { Add-Content -LiteralPath $logFile -Value ("{0} TRANSCRIPT-MISSING uuid={1} path={2}" -f $utc, $sid, $tp) -Encoding Ascii } catch {}

    if (-not (Test-Path -LiteralPath $marker)) {
        # First miss for this session -> record the debounce marker and fire one toast.
        try { Set-Content -LiteralPath $marker -Value ("{0} uuid={1} path={2}" -f $utc, $sid, $tp) -Encoding Ascii } catch {}

        if (-not $NotifyScript) {
            if ($env:CLAUDE_HOOK_NOTIFY_SCRIPT) {
                $NotifyScript = $env:CLAUDE_HOOK_NOTIFY_SCRIPT
            } else {
                $NotifyScript = Join-Path $PSScriptRoot 'notify-desktop.ps1'
                if (-not (Test-Path -LiteralPath $NotifyScript)) {
                    $NotifyScript = Join-Path $env:USERPROFILE '.claude\scripts\notify-desktop.ps1'
                }
            }
        }
        if ($NotifyScript -and (Test-Path -LiteralPath $NotifyScript)) {
            $body = "Not on disk: " + $tp + " . Type /export session-logs/<name>.txt NOW; do not close the tab."
            # Pass a single, explicitly-quoted command line: Start-Process -ArgumentList does NOT
            # quote array elements, so space-bearing titles/bodies would otherwise split into
            # separate tokens (and a stray '-' token breaks the child's parameter binding entirely).
            $q = { param($s) '"' + ([string]$s -replace '"', "'") + '"' }
            $argline = '-NoProfile -ExecutionPolicy Bypass -File {0} -Kind failed -Title {1} -Body {2}' -f `
                (& $q $NotifyScript), (& $q ('Transcript MISSING: ' + $display)), (& $q $body)
            Start-Process -FilePath 'powershell.exe' -WindowStyle Hidden -ArgumentList $argline | Out-Null
        }
    }
} catch {}

exit 0
