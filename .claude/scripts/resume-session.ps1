# resume-session.ps1 - Resolve a spawned/orchestrated session's Claude UUID and resume it.
#
# The transcript-persistence guard records every session's real Claude UUID + on-disk transcript
# path at boot (capture-session-start.ps1 -> <StateDir>\gate\<label>.session). This helper reads
# that capture, confirms the transcript actually exists on disk, and runs `claude --resume <uuid>`
# from the session's recorded cwd - turning the label you know (the orchestration id) back into a
# live, continuable conversation.
#
# Resolution order for the capture file (<gate>\<Id>.session):
#   -StateDir <path>  -> <path>\gate\<Id>.session          (explicit; also how the unit tests drive it)
#   -PlanSlug <slug>  -> ~/.claude\orchestration\<slug>\gate\<Id>.session
#   (neither)         -> scan ~/.claude\orchestration\*\gate\<Id>.session; unique match wins, an
#                        ambiguous match lists the plans and asks for -PlanSlug.
#
# -Uuid <uuid> bypasses the capture entirely and resumes a session by its Claude UUID, finding the
# transcript by globbing ~/.claude\projects\*\<uuid>.jsonl. This is the fallback for PRE-guard
# sessions that never got a gate\<id>.session capture (the guard did not exist when they ran).
#
# Exit codes: 0 = resumed (or -DryRun printed the command); 2 = not resumable (no capture, transcript
# never written to disk, or ambiguous/unknown selection).
#
# Usage:
#   .\resume-session.ps1 -Id guard-smoke-session-1 -PlanSlug guard-smoke
#   .\resume-session.ps1 -Id guard-smoke-session-1 -PlanSlug guard-smoke -DryRun
#   .\resume-session.ps1 -Uuid 04616a8e-....-....-....-............
#
# Windows PowerShell 5.1 compatible, ASCII-only.

param(
    [string]$Id = '',
    [string]$PlanSlug = '',
    [string]$StateDir = '',
    [string]$Uuid = '',
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$OrchRoot = Join-Path $env:USERPROFILE '.claude\orchestration'
# CLAUDE_PROJECTS_DIR redirects the transcript glob (tests only); production leaves it unset.
$ProjectsRoot = $env:CLAUDE_PROJECTS_DIR
if (-not $ProjectsRoot) { $ProjectsRoot = Join-Path $env:USERPROFILE '.claude\projects' }

# Glob ~/.claude\projects\*\<uuid>.jsonl for a transcript written by a (possibly pre-guard) session.
function Find-TranscriptByUuid {
    param([string]$U)
    if (-not $U) { return $null }
    if (-not (Test-Path -LiteralPath $ProjectsRoot)) { return $null }
    $hit = Get-ChildItem -Path $ProjectsRoot -Recurse -Filter ($U + '.jsonl') -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($hit) { return $hit.FullName }
    return $null
}

# Print the resume command and (unless -DryRun) exec it from the recorded cwd. Returns an exit code.
function Invoke-Resume {
    param([string]$U, [string]$Cwd, [string]$TranscriptPath)
    Write-Host ("[resume] transcript on disk: {0}" -f $TranscriptPath) -ForegroundColor Green
    if ($Cwd) { Write-Host ("[resume] cwd            : {0}" -f $Cwd) -ForegroundColor DarkGray }
    Write-Host ("[resume] claude --resume {0}" -f $U) -ForegroundColor Cyan
    if ($DryRun) {
        Write-Host "[resume] -DryRun: command not executed." -ForegroundColor DarkGray
        return 0
    }
    if ($Cwd -and (Test-Path -LiteralPath $Cwd)) { Set-Location -LiteralPath $Cwd }
    claude --resume $U
    return 0
}

# Honest verdict for a session whose transcript was never flushed to disk (unrecoverable via --resume).
function Write-NotResumable {
    param([string]$U, [string]$TranscriptPath, [string]$Cwd, [string]$StateDirForHint)
    Write-Host "[resume] NOT resumable - the transcript was never written to disk." -ForegroundColor Red
    if ($TranscriptPath) { Write-Host ("           expected: {0}" -f $TranscriptPath) -ForegroundColor Red }
    if ($U) { Write-Host ("           uuid    : {0} (no {0}.jsonl anywhere under {1})" -f $U, $ProjectsRoot) -ForegroundColor Red }
    Write-Host "           If you ran /export, the snapshot in session-logs\ IS the transcript:" -ForegroundColor Yellow
    if ($Cwd) { Write-Host ("             {0}" -f (Join-Path $Cwd 'session-logs')) -ForegroundColor Yellow }
    if ($StateDirForHint) { Write-Host ("           Boot trace: {0}" -f (Join-Path (Join-Path $StateDirForHint 'gate') ($Id + '.gate.log'))) -ForegroundColor DarkGray }
}

# --- Path 1: resume directly by UUID (pre-guard fallback) ---
if ($Uuid) {
    $tp = Find-TranscriptByUuid $Uuid
    if ($tp) { exit (Invoke-Resume -U $Uuid -Cwd '' -TranscriptPath $tp) }
    Write-NotResumable -U $Uuid -TranscriptPath '' -Cwd '' -StateDirForHint ''
    exit 2
}

# --- Path 2: resume by orchestration label via the gate\<Id>.session capture ---
if (-not $Id) {
    Write-Host "[resume] give -Id <orch-label> (with -PlanSlug/-StateDir) or -Uuid <uuid>." -ForegroundColor Red
    exit 2
}

$captureFile = $null
if ($StateDir) {
    $captureFile = Join-Path (Join-Path $StateDir 'gate') ($Id + '.session')
}
elseif ($PlanSlug) {
    $StateDir = Join-Path $OrchRoot $PlanSlug
    $captureFile = Join-Path (Join-Path $StateDir 'gate') ($Id + '.session')
}
else {
    # Scan every known plan for a gate\<Id>.session capture.
    $found = @()
    if (Test-Path -LiteralPath $OrchRoot) {
        $found = @(Get-ChildItem -Path $OrchRoot -Recurse -Filter ($Id + '.session') -ErrorAction SilentlyContinue |
            Where-Object { $_.Directory.Name -eq 'gate' })
    }
    if ($found.Count -eq 0) {
        Write-Host ("[resume] no capture found for '{0}' under any plan in {1}." -f $Id, $OrchRoot) -ForegroundColor Red
        Write-Host "         Pass -PlanSlug <slug>/-StateDir <path>, or -Uuid <uuid> if you know it." -ForegroundColor DarkGray
        exit 2
    }
    if ($found.Count -gt 1) {
        Write-Host ("[resume] '{0}' is ambiguous - captured under multiple plans. Re-run with -PlanSlug:" -f $Id) -ForegroundColor Yellow
        foreach ($f in $found) { Write-Host ("           -PlanSlug {0}" -f (Split-Path (Split-Path $f.DirectoryName -Parent) -Leaf)) }
        exit 2
    }
    $captureFile = $found[0].FullName
    $StateDir = Split-Path $found[0].DirectoryName -Parent
}

if (-not (Test-Path -LiteralPath $captureFile)) {
    Write-Host ("[resume] no capture: {0} does not exist." -f $captureFile) -ForegroundColor Red
    Write-Host "         The SessionStart hook never recorded this session (see gate\<id>.gate.log)." -ForegroundColor DarkGray
    exit 2
}

$cap = $null
try { $cap = Get-Content -LiteralPath $captureFile -Raw | ConvertFrom-Json } catch {}
if (-not $cap) {
    Write-Host ("[resume] capture unreadable: {0}" -f $captureFile) -ForegroundColor Red
    exit 2
}

$u   = [string]$cap.sessionId
$tp  = [string]$cap.transcriptPath
$cwd = [string]$cap.cwd

if ($tp -and (Test-Path -LiteralPath $tp)) {
    exit (Invoke-Resume -U $u -Cwd $cwd -TranscriptPath $tp)
}

# Recorded path is gone; the transcript may still be on disk under its UUID (moved project dir).
$alt = Find-TranscriptByUuid $u
if ($alt) { exit (Invoke-Resume -U $u -Cwd $cwd -TranscriptPath $alt) }

Write-NotResumable -U $u -TranscriptPath $tp -Cwd $cwd -StateDirForHint $StateDir
exit 2
