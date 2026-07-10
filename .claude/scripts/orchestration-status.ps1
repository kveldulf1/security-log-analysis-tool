# orchestration-status.ps1 - Render the live state of an orchestrated plan from disk.
#
# Reads a plan's manifest.json + sentinel files and prints an ASCII table of every session's state.
# State is derived PURELY from the manifest DAG plus the sentinels - the script writes nothing, so it
# is safe to run at any time and from any tab (including the product-owner console).
#
# STATE column:
#   DONE       .done sentinel present
#   FAILED     .failed sentinel present
#   ABORTED    .aborted sentinel present
#   DEP-FAILED no own sentinel, but a dependency is .failed/.aborted (this session can never release)
#   GATED      no own sentinel, still waiting on one or more not-yet-.done dependencies
#   READY      no own sentinel, all dependencies .done (or none) - eligible to run / already running
#
# UUID / TRANSCRIPT columns (from the transcript-persistence guard's gate\<id>.session capture):
#   UUID        first 8 chars of the real Claude session id recorded at boot ('-' if not captured)
#   TRANSCRIPT  yes = the .jsonl is on disk; MISSING = captured/marked but no transcript file (data
#               loss - snapshot with /export immediately); '-' = no capture recorded
#
# Selection:
#   -PlanSlug <slug>   -> ~/.claude/orchestration/<slug>
#   -StateDir <path>   -> explicit state directory
#   (neither)          -> enumerate every ~/.claude/orchestration/*/manifest.json, one summary line each
#
# Exit codes: 0 = rendered clean, 1 = at least one FAILED/ABORTED session OR a MISSING transcript
#             (scriptable gate), 2 = no manifest / unknown slug.
#
# Usage:
#   .\orchestration-status.ps1 -PlanSlug my-plan
#   .\orchestration-status.ps1 -StateDir C:\Users\me\.claude\orchestration\my-plan
#   .\orchestration-status.ps1                      # overview of all known plans

param(
    [string]$PlanSlug = '',
    [string]$StateDir = ''
)

$ErrorActionPreference = 'Stop'
$OrchRoot = Join-Path $env:USERPROFILE '.claude\orchestration'

function Get-SessionState {
    param($Session, [string]$Dir, [hashtable]$SentinelIndex)
    $id = $Session.id
    if ($SentinelIndex["$id.done"])    { return 'DONE' }
    if ($SentinelIndex["$id.failed"])  { return 'FAILED' }
    if ($SentinelIndex["$id.aborted"]) { return 'ABORTED' }
    $deps = @($Session.blockedBy)
    $depFailed = $false
    $allDone = $true
    foreach ($d in $deps) {
        if ($SentinelIndex["$d.failed"] -or $SentinelIndex["$d.aborted"]) { $depFailed = $true }
        if (-not $SentinelIndex["$d.done"]) { $allDone = $false }
    }
    if ($depFailed) { return 'DEP-FAILED' }
    if ($allDone)   { return 'READY' }
    return 'GATED'
}

function Read-Sentinel {
    param([string]$Dir, [string]$Id, [string]$Ext)
    $path = Join-Path $Dir ($Id + '.' + $Ext)
    if (-not (Test-Path $path)) { return $null }
    try { return (Get-Content $path -Raw | ConvertFrom-Json) } catch { return $null }
}

function Read-SessionCapture {
    # The SessionStart hook records the real Claude UUID + transcript path here (gate\<id>.session).
    param([string]$Dir, [string]$Id)
    $path = Join-Path (Join-Path $Dir 'gate') ($Id + '.session')
    if (-not (Test-Path -LiteralPath $path)) { return $null }
    try { return (Get-Content -LiteralPath $path -Raw | ConvertFrom-Json) } catch { return $null }
}

function Show-Plan {
    param([string]$Dir)
    $manifestPath = Join-Path $Dir 'manifest.json'
    if (-not (Test-Path $manifestPath)) {
        Write-Host "No manifest.json in $Dir" -ForegroundColor Red
        return 2
    }
    $manifest = Get-Content $manifestPath -Raw | ConvertFrom-Json
    $sessions = @($manifest.sessions)

    # Index sentinels once.
    $index = @{}
    foreach ($f in (Get-ChildItem -Path $Dir -File -ErrorAction SilentlyContinue)) {
        if ($f.Name -match '\.(done|failed|aborted)$') { $index[$f.Name] = $true }
    }

    Write-Host ''
    Write-Host ("PLAN: " + $manifest.planSlug) -ForegroundColor White
    Write-Host ("  stateDir : " + $Dir)
    Write-Host ("  planFile : " + $manifest.planFile)
    Write-Host ("  generated: " + $manifest.generatedUtc + "  effort=" + $manifest.effort + "  permissions=" + $manifest.permissions)

    $rows = @()
    $anyFailed = $false
    $anyMissing = $false
    $missingList = @()
    $waiting = @()
    foreach ($s in $sessions) {
        $state = Get-SessionState -Session $s -Dir $Dir -SentinelIndex $index
        if ($state -eq 'FAILED' -or $state -eq 'ABORTED') { $anyFailed = $true }
        if ($state -ne 'DONE') { $waiting += $s.id }

        # Transcript-persistence columns: UUID captured at boot + whether the .jsonl is on disk.
        $uuid8 = '-'
        $transcript = '-'
        $cap = Read-SessionCapture -Dir $Dir -Id $s.id
        $gp = Join-Path $Dir 'gate'
        $marked = (Test-Path -LiteralPath (Join-Path $gp ($s.id + '.transcript-missing'))) -or (Test-Path -LiteralPath (Join-Path $gp ($s.id + '.hook-missing')))
        if ($cap) {
            if ($cap.sessionId) { $uuid8 = ([string]$cap.sessionId).Substring(0, [Math]::Min(8, ([string]$cap.sessionId).Length)) }
            if ($cap.transcriptPath -and (Test-Path -LiteralPath $cap.transcriptPath)) { $transcript = 'yes' } else { $transcript = 'MISSING' }
        }
        if ($marked) { $transcript = 'MISSING' }
        if ($transcript -eq 'MISSING') {
            $anyMissing = $true
            $capUuid = if ($cap) { [string]$cap.sessionId } else { '' }
            $capPath = if ($cap) { [string]$cap.transcriptPath } else { '' }
            $missingList += [pscustomobject]@{ id = [string]$s.id; uuid = $capUuid; path = $capPath }
        }

        $sha = '-'
        $fin = '-'
        $report = '-'
        $ext = switch ($state) { 'DONE' { 'done' } 'FAILED' { 'failed' } 'ABORTED' { 'aborted' } default { '' } }
        if ($ext) {
            $sent = Read-Sentinel -Dir $Dir -Id $s.id -Ext $ext
            if ($sent) {
                if ($sent.commitSha) { $sha = ([string]$sent.commitSha).Substring(0, [Math]::Min(12, ([string]$sent.commitSha).Length)) }
                if ($sent.utc) { $fin = [string]$sent.utc }
                if ($sent.reportFile -and (Test-Path $sent.reportFile)) { $report = 'yes' }
            }
        }
        $deps = @($s.blockedBy)
        $depStr = if ($deps.Count -gt 0) { ($deps -join ',') } else { '-' }

        $rows += [pscustomobject]@{
            ID    = [string]$s.id
            MODEL = [string]$s.model
            ROLE  = [string]$s.role
            DEPS  = $depStr
            STATE = $state
            UUID  = $uuid8
            TRANSCRIPT = $transcript
            SHA   = $sha
            FIN   = $fin
            REPORT = $report
        }
    }

    # Render an ASCII table with dynamic column widths.
    $headers = [ordered]@{ ID='ID'; MODEL='MODEL'; ROLE='ROLE'; DEPS='DEPS'; STATE='STATE'; UUID='UUID'; TRANSCRIPT='TRANSCRIPT'; SHA='SHA'; FIN='FINISHED-UTC'; REPORT='REPORT' }
    $widths = @{}
    foreach ($k in $headers.Keys) { $widths[$k] = $headers[$k].Length }
    foreach ($r in $rows) {
        foreach ($k in $headers.Keys) {
            $len = ([string]$r.$k).Length
            if ($len -gt $widths[$k]) { $widths[$k] = $len }
        }
    }
    function Format-Row {
        param($Cells, $Widths, $Keys)
        $parts = @()
        foreach ($k in $Keys) { $parts += ([string]$Cells[$k]).PadRight($Widths[$k]) }
        return ($parts -join ' | ')
    }
    $keys = @($headers.Keys)
    $headerCells = @{}
    foreach ($k in $keys) { $headerCells[$k] = $headers[$k] }
    Write-Host ''
    Write-Host ('  ' + (Format-Row -Cells $headerCells -Widths $widths -Keys $keys))
    $sep = @()
    foreach ($k in $keys) { $sep += ('-' * $widths[$k]) }
    Write-Host ('  ' + ($sep -join '-+-'))
    foreach ($r in $rows) {
        $cells = @{}
        foreach ($k in $keys) { $cells[$k] = $r.$k }
        Write-Host ('  ' + (Format-Row -Cells $cells -Widths $widths -Keys $keys))
    }

    # Footer.
    Write-Host ''
    if ($waiting.Count -eq 0) {
        Write-Host "  ALL-DONE: every session is DONE." -ForegroundColor Green
    }
    elseif ($anyFailed) {
        Write-Host ("  ATTENTION: failures present. waiting on: " + ($waiting -join ', ')) -ForegroundColor Red
    }
    else {
        Write-Host ("  waiting on: " + ($waiting -join ', ')) -ForegroundColor Yellow
    }

    if ($anyMissing) {
        Write-Host ''
        Write-Host "  TRANSCRIPT ALERT - these sessions have no transcript on disk (conversation unrecoverable if lost):" -ForegroundColor Red
        foreach ($m in $missingList) {
            $u = if ($m.uuid) { $m.uuid } else { '?' }
            $p = if ($m.path) { $m.path } else { '?' }
            Write-Host ("    {0}  uuid={1}  path={2}" -f $m.id, $u, $p) -ForegroundColor Red
        }
        Write-Host "    Open the tab and /export session-logs/logs/<id>-vN.txt now; investigate gate\<id>.gate.log." -ForegroundColor Red
    }

    if ($anyFailed -or $anyMissing) { return 1 } else { return 0 }
}

# --- Dispatch ---
$exit = 0

if ($StateDir) {
    $exit = Show-Plan -Dir $StateDir
}
elseif ($PlanSlug) {
    $dir = Join-Path $OrchRoot $PlanSlug
    if (-not (Test-Path $dir)) {
        Write-Host "No orchestration state for slug '$PlanSlug' (looked in $dir)." -ForegroundColor Red
        exit 2
    }
    $exit = Show-Plan -Dir $dir
}
else {
    # Overview: one summary line per known plan.
    if (-not (Test-Path $OrchRoot)) {
        Write-Host "No orchestration state yet ($OrchRoot does not exist)." -ForegroundColor DarkGray
        exit 0
    }
    $manifests = @(Get-ChildItem -Path $OrchRoot -Recurse -Filter 'manifest.json' -ErrorAction SilentlyContinue)
    if ($manifests.Count -eq 0) {
        Write-Host "No plans found under $OrchRoot." -ForegroundColor DarkGray
        exit 0
    }
    Write-Host "Known orchestration plans:" -ForegroundColor White
    foreach ($m in $manifests) {
        $dir = Split-Path $m.FullName -Parent
        try {
            $man = Get-Content $m.FullName -Raw | ConvertFrom-Json
            $sessions = @($man.sessions)
            $index = @{}
            foreach ($f in (Get-ChildItem -Path $dir -File -ErrorAction SilentlyContinue)) {
                if ($f.Name -match '\.(done|failed|aborted)$') { $index[$f.Name] = $true }
            }
            $doneN = 0; $failN = 0
            foreach ($s in $sessions) {
                $st = Get-SessionState -Session $s -Dir $dir -SentinelIndex $index
                if ($st -eq 'DONE') { $doneN++ }
                if ($st -eq 'FAILED' -or $st -eq 'ABORTED') { $failN++ }
            }
            $tag = if ($failN -gt 0) { 'FAILURES' } elseif ($doneN -eq $sessions.Count) { 'ALL-DONE' } else { 'in-progress' }
            Write-Host ("  {0,-28} {1,3}/{2,-3} done  {3}" -f $man.planSlug, $doneN, $sessions.Count, $tag)
            if ($failN -gt 0) { $exit = 1 }
        }
        catch {
            Write-Host ("  {0}  (unreadable manifest)" -f $dir)
        }
    }
    Write-Host ''
    Write-Host "Run with -PlanSlug <slug> for the full table." -ForegroundColor DarkGray
}

exit $exit
