# capture-session-start.ps1 - Claude Code SessionStart hook.
#
# Records the session's real UUID and on-disk transcript path the moment Claude boots, so a
# session is always identifiable and resumable later. Two sinks:
#   (1) ~/.claude/logs/session-registry.log  - one line for EVERY session (orchestrated or not),
#       the durable "which UUID was which" record that did not exist before (a crash used to leave
#       no way to map an orchestration label to its Claude session id).
#   (2) <StateDir>\gate\<label>.session       - written only for orchestrated tabs (env
#       CLAUDE_SESSION_LABEL + CLAUDE_ORCH_STATE_DIR), consumed by spawn-session-tab.ps1 and
#       orchestration-status.ps1 to verify persistence and print a resume hint.
#
# CRITICAL CONTRACTS:
#   - A SessionStart hook's stdout is injected into the model's context. This script must print
#     NOTHING to stdout, ever.
#   - A broken capture must never break a session: the whole body is try/catch-wrapped and the
#     script ALWAYS exits 0.
#
# Registered (relative path) in a seeded project's .claude/settings.json under hooks.SessionStart.

try {
    $raw = [Console]::In.ReadToEnd()
    $p = $null
    try { $p = $raw | ConvertFrom-Json } catch { $p = $null }
    if ($null -eq $p) { exit 0 }

    $utc = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
    $sid = [string]$p.session_id
    $tp  = [string]$p.transcript_path
    $src = [string]$p.source
    $cwd = [string]$p.cwd

    # (1) Global registry - every session. Tab-separated: utc, uuid, source, cwd, transcript_path.
    # CLAUDE_SESSION_REGISTRY_DIR redirects the log (tests only); production leaves it unset.
    try {
        $logDir = $env:CLAUDE_SESSION_REGISTRY_DIR
        if (-not $logDir) { $logDir = Join-Path $env:USERPROFILE '.claude\logs' }
        if (-not (Test-Path -LiteralPath $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }
        $line = "{0}`t{1}`t{2}`t{3}`t{4}" -f $utc, $sid, $src, $cwd, $tp
        Add-Content -LiteralPath (Join-Path $logDir 'session-registry.log') -Value $line -Encoding Ascii
    } catch {}

    # (2) Orchestrated tab - atomic <gate>\<label>.session (latest wins; resume can change the UUID)
    #     plus a history line in the existing gate.log.
    $label = $env:CLAUDE_SESSION_LABEL
    $stateDir = $env:CLAUDE_ORCH_STATE_DIR
    if ($label -and $stateDir) {
        try {
            $gateDir = Join-Path $stateDir 'gate'
            if (-not (Test-Path -LiteralPath $gateDir)) { New-Item -ItemType Directory -Path $gateDir -Force | Out-Null }
            $obj = [ordered]@{
                label          = $label
                sessionId      = $sid
                transcriptPath = $tp
                cwd            = $cwd
                source         = $src
                utc            = $utc
                writer         = 'capture-session-start.ps1'
            }
            $target = Join-Path $gateDir ($label + '.session')
            $tmp    = $target + '.tmp'
            ($obj | ConvertTo-Json) | Set-Content -LiteralPath $tmp -Encoding Ascii
            Move-Item -LiteralPath $tmp -Destination $target -Force
            Add-Content -LiteralPath (Join-Path $gateDir ($label + '.gate.log')) `
                -Value ("{0} SESSION-START source={1} uuid={2} transcript={3}" -f $utc, $src, $sid, $tp) -Encoding Ascii
        } catch {}
    }
} catch {}

exit 0
