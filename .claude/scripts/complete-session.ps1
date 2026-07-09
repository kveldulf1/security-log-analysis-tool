# complete-session.ps1 - Signal that an orchestrated session finished (done / failed / aborted).
#
# The final wrap-up step every orchestrated session runs. It writes a single per-session sentinel
# file into the plan's orchestration state directory; the self-gating tab runners of dependent
# sessions poll those sentinels and auto-submit when all of their dependencies are .done. Writing a
# sentinel is a lock-free, single-writer, atomic operation (.tmp + Move-Item -Force).
#
# State directory layout (outside every repo - see the plan's Design contracts):
#   <stateDir>\manifest.json                  static DAG (written by the spawner)
#   <stateDir>\reports\<id>-report.md         per-session report
#   <stateDir>\<id>.done | .failed | .aborted sentinel (JSON; exactly one status per id)
#   <stateDir>\_all-done.fired                atomic claim marker - ALL-DONE toast fires once
#
# Sentinel JSON: { sessionId, status, utc, commitSha, branch, summary, reportFile, writer }.
# Writing a sentinel deletes the opposite-status sentinels for the same id (fix-then-done recovery).
#
# Behavior:
#   - Secret-scans Summary + CommitSha with the seeder credential regexes; on a hit prints the
#     pattern CLASS only (never the value) and exits 6.
#   - Creates the state dir if missing (warns, still writes - ad-hoc use works).
#   - -SkipIfFinished: no-op (exit 0) if a sentinel already exists for this id (used by the abort path).
#   - When a manifest is present: prints which dependents just unblocked, or on failed/aborted the
#     dead-blocked dependents plus a recovery hint. When every manifest id is .done, the winner of an
#     atomic _all-done.fired claim raises the distinct ALL-DONE toast.
#   - Raises a per-session desktop toast via the sibling notify-desktop.ps1 (unless -NoToast).
#
# Usage:
#   .\complete-session.ps1 -SessionId my-plan-session-1 -Status done   -CommitSha abc1234 -Summary "shipped X"
#   .\complete-session.ps1 -SessionId my-plan-session-2 -Status failed  -Summary "DoD not met: negative test red"
#   .\complete-session.ps1 -SessionId my-plan-session-3 -Status aborted -SkipIfFinished -Summary "claude exited"
#
# Exit codes: 0 = signaled (or skipped), 2 = session id unresolvable, 6 = secret-shaped input rejected.

param(
    [string]$SessionId = $env:CLAUDE_SESSION_LABEL,

    [Parameter(Mandatory = $true)]
    [ValidateSet('done', 'failed', 'aborted')]
    [string]$Status,

    [string]$CommitSha = '',

    [string]$Summary = '',

    [string]$Branch = '',

    [string]$ReportFile = '',

    [string]$StateDir = '',

    [switch]$SkipIfFinished,

    [switch]$NoToast
)

$ErrorActionPreference = 'Stop'

function Test-SecretShaped {
    # Returns the pattern CLASS name of the first match, or $null. Never returns the matched value.
    param([string]$Text)
    if ([string]::IsNullOrEmpty($Text)) { return $null }
    $patterns = [ordered]@{
        'GitHub PAT (classic)'    = 'ghp_[A-Za-z0-9]{36}'
        'GitHub fine-grained PAT' = 'github_pat_[A-Za-z0-9_]{22,}'
        'GitHub OAuth/app token'  = 'gh[ousr]_[A-Za-z0-9]{36}'
        'Anthropic API key'       = 'sk-ant-[A-Za-z0-9_-]{20,}'
        'AWS access key id'       = 'AKIA[0-9A-Z]{16}'
        'GitLab PAT'              = 'glpat-[A-Za-z0-9_-]{20,}'
        'Slack token'             = 'xox[bpars]-[A-Za-z0-9-]{10,}'
        'Private key block'       = '-----BEGIN [A-Z ]*PRIVATE KEY-----'
        'Inline basic-auth URL'   = 'https?://[^/@\s"]+:[^/@\s"]+@'
    }
    foreach ($class in $patterns.Keys) {
        if ([regex]::IsMatch($Text, $patterns[$class])) { return $class }
    }
    return $null
}

function Get-SlugFromSessionId {
    param([string]$Id)
    # Strip a trailing -session-<N> to recover the plan slug.
    return ($Id -replace '-session-\d+$', '')
}

# --- Resolve session id ---
if ([string]::IsNullOrWhiteSpace($SessionId)) {
    Write-Host "ERROR: -SessionId not provided and CLAUDE_SESSION_LABEL is unset. Cannot signal completion." -ForegroundColor Red
    exit 2
}

# --- Secret scan (class only, never the value) ---
foreach ($field in @($Summary, $CommitSha, $Branch)) {
    $class = Test-SecretShaped $field
    if ($class) {
        Write-Host "ERROR: refusing to write a sentinel - input matches credential pattern [$class]. Remove the secret from -Summary/-CommitSha/-Branch." -ForegroundColor Red
        exit 6
    }
}

# --- Clamp summary to 200 chars ---
if ($Summary.Length -gt 200) {
    Write-Host "WARN: -Summary exceeds 200 chars; truncating." -ForegroundColor Yellow
    $Summary = $Summary.Substring(0, 200)
}

# --- Resolve state dir ---
if ([string]::IsNullOrWhiteSpace($StateDir)) {
    if (-not [string]::IsNullOrWhiteSpace($env:CLAUDE_ORCH_STATE_DIR)) {
        $StateDir = $env:CLAUDE_ORCH_STATE_DIR
    }
    else {
        $slug = Get-SlugFromSessionId $SessionId
        $StateDir = Join-Path $env:USERPROFILE (".claude\orchestration\" + $slug)
    }
}

if (-not (Test-Path $StateDir)) {
    Write-Host "WARN: state dir '$StateDir' did not exist; creating it." -ForegroundColor Yellow
    New-Item -ItemType Directory -Path $StateDir -Force | Out-Null
}

$doneFile    = Join-Path $StateDir ($SessionId + '.done')
$failedFile  = Join-Path $StateDir ($SessionId + '.failed')
$abortedFile = Join-Path $StateDir ($SessionId + '.aborted')
$sentinelMap = @{ 'done' = $doneFile; 'failed' = $failedFile; 'aborted' = $abortedFile }
$targetFile  = $sentinelMap[$Status]

# --- -SkipIfFinished: no-op if any sentinel already exists ---
if ($SkipIfFinished) {
    foreach ($f in @($doneFile, $failedFile, $abortedFile)) {
        if (Test-Path $f) {
            Write-Host "SKIP: sentinel already present for '$SessionId' ($([System.IO.Path]::GetExtension($f).TrimStart('.'))). Not overwriting." -ForegroundColor DarkGray
            exit 0
        }
    }
}

# --- Derive report file if not supplied ---
if ([string]::IsNullOrWhiteSpace($ReportFile)) {
    $ReportFile = Join-Path (Join-Path $StateDir 'reports') ($SessionId + '-report.md')
}

# --- Build sentinel object ---
$sentinel = [ordered]@{
    sessionId  = $SessionId
    status     = $Status
    utc        = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
    commitSha  = $CommitSha
    branch     = $Branch
    summary    = $Summary
    reportFile = $ReportFile
    writer     = 'complete-session.ps1'
}
$json = ($sentinel | ConvertTo-Json -Depth 5)

# --- Atomic write: .tmp then Move-Item -Force ---
$tmp = $targetFile + '.tmp'
Set-Content -Path $tmp -Value $json -Encoding Ascii
Move-Item -Path $tmp -Destination $targetFile -Force

# --- Delete opposite-status sentinels for this id ---
foreach ($f in @($doneFile, $failedFile, $abortedFile)) {
    if ($f -ne $targetFile -and (Test-Path $f)) { Remove-Item $f -Force }
}

Write-Host "SIGNALED: $SessionId -> $Status  (sentinel: $targetFile)" -ForegroundColor Green

# --- Manifest-aware dependent reporting + ALL-DONE ---
$manifestPath = Join-Path $StateDir 'manifest.json'
$firedAllDone = $false
if (Test-Path $manifestPath) {
    try {
        $manifest = Get-Content $manifestPath -Raw | ConvertFrom-Json
        $sessions = @($manifest.sessions)

        # Dependents = sessions whose blockedBy contains this id.
        $dependents = @($sessions | Where-Object { $_.blockedBy -contains $SessionId })

        function Test-SentinelStatus {
            param([string]$Id, [string]$Ext)
            return (Test-Path (Join-Path $StateDir ($Id + '.' + $Ext)))
        }

        if ($Status -eq 'done') {
            $unblocked = @()
            foreach ($dep in $dependents) {
                $deps = @($dep.blockedBy)
                $allDone = $true
                $anyBad = $false
                foreach ($d in $deps) {
                    if (-not (Test-SentinelStatus $d 'done')) { $allDone = $false }
                    if ((Test-SentinelStatus $d 'failed') -or (Test-SentinelStatus $d 'aborted')) { $anyBad = $true }
                }
                if ($allDone -and -not $anyBad) { $unblocked += $dep.id }
            }
            if ($unblocked.Count -gt 0) {
                Write-Host ("UNBLOCKED: " + ($unblocked -join ', ') + " - their waiting tabs boot claude and self-submit.") -ForegroundColor Cyan
            }
        }
        else {
            # failed / aborted: dependents are now dead-blocked.
            if ($dependents.Count -gt 0) {
                $ids = @($dependents | ForEach-Object { $_.id })
                Write-Host ("DEAD-BLOCKED by this $Status : " + ($ids -join ', ')) -ForegroundColor Yellow
                Write-Host ("  Recovery: fix, then  complete-session.ps1 -SessionId $SessionId -Status done -CommitSha <sha>") -ForegroundColor Yellow
            }
        }

        # ALL-DONE: every manifest id has a .done sentinel.
        $allIds = @($sessions | ForEach-Object { $_.id })
        $allDoneNow = $true
        foreach ($id in $allIds) {
            if (-not (Test-SentinelStatus $id 'done')) { $allDoneNow = $false; break }
        }
        if ($allDoneNow -and $allIds.Count -gt 0) {
            $claimPath = Join-Path $StateDir '_all-done.fired'
            $won = $false
            try {
                $fs = [System.IO.File]::Open($claimPath, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
                $fs.Close()
                $won = $true
            }
            catch { $won = $false }
            if ($won) {
                $firedAllDone = $true
                Write-Host "ALL-DONE: every session is .done." -ForegroundColor Green
                if (-not $NoToast) {
                    $notify = Join-Path $PSScriptRoot 'notify-desktop.ps1'
                    if (Test-Path $notify) {
                        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $notify -Kind alldone -Title 'All sessions done' -Body ("$($allIds.Count)/$($allIds.Count) complete - $($manifest.planSlug)") | Out-Null
                    }
                }
            }
        }
    }
    catch {
        Write-Host "WARN: could not read manifest ($($_.Exception.Message)); skipped dependent/ALL-DONE reporting." -ForegroundColor Yellow
    }
}

# --- Per-session toast (skip if the ALL-DONE toast already fired for this call) ---
if (-not $NoToast -and -not $firedAllDone) {
    $notify = Join-Path $PSScriptRoot 'notify-desktop.ps1'
    if (Test-Path $notify) {
        $kind = if ($Status -eq 'done') { 'done' } else { 'failed' }
        $shaShort = if ($CommitSha) { $CommitSha.Substring(0, [Math]::Min(12, $CommitSha.Length)) } else { '(no sha)' }
        $body = if ($Summary) { "$shaShort - $Summary" } else { $shaShort }
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $notify -Kind $kind -Title "$SessionId $Status" -Body $body | Out-Null
    }
}

# --- Status pointer ---
$statusScript = Join-Path $PSScriptRoot 'orchestration-status.ps1'
if (Test-Path $statusScript) {
    $slug = Get-SlugFromSessionId $SessionId
    Write-Host ("Status: powershell -NoProfile -ExecutionPolicy Bypass -File `"$statusScript`" -PlanSlug $slug") -ForegroundColor DarkGray
}

exit 0
