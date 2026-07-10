#requires -Version 5.1
# resolve-export-name.ps1 - Compute the correct /export filename for a Claude Code session.
#
# The model CANNOT invoke /export (it is a REPL built-in with no tool), so this script does the one
# thing the model can't do reliably by hand: derive the canonical snapshot name and print the exact
# line for the human to type. Naming follows the session spawner's own scheme:
#
#   orchestrator / planning session : <slug>-master-plan
#   spawned worker session          : <N><s|p>-<slug>-session-<N>
#                                       N     = session number (from '-session-N')
#                                       s | p = SEQUENTIAL | PARALLEL, read from the orchestration
#                                               manifest's tagType (the same tag spawn-plan-sessions.ps1
#                                               assigns from each session's **Parallelization:** line)
#   examples: 1s-logwarden-session-1, 2s-logwarden-session-2, 3p-logwarden-session-3, logwarden-master-plan
#
# Identity resolution order (worker sessions): -SessionId arg, then the worktree marker
# (.claude-spawn-worktree.json), then the git branch (sessions/<id>). The caller (Claude) should also
# feed -SessionId from its own cold-start prompt context when it knows it.

[CmdletBinding()]
param(
    [string]$SessionId,                    # e.g. logwarden-session-3; omit to auto-detect
    [string]$Slug,                         # e.g. logwarden; derived from SessionId when omitted
    [switch]$MasterPlan,                   # orchestrator/planning session -> <slug>-master-plan
    [ValidateSet('s', 'p')] [string]$Type, # override the sequential/parallel letter (skips manifest)
    [int]$Interim,                         # interim milestone snapshot -> -vN suffix
    [switch]$Final,                        # wrap-up snapshot -> -final suffix
    [string]$ProjectPath,                  # repo root (defaults to CWD); session-logs\logs\ lives here
    [string]$OrchestrationRoot,            # defaults to ~/.claude/orchestration
    [string]$ManifestPath,                 # explicit manifest.json (overrides OrchestrationRoot lookup)
    [switch]$Raw                           # print only the bare name (no /export line) - for scripting/tests
)

$ErrorActionPreference = 'Stop'
# PS 5.1 Get-Content defaults to the system codepage; force UTF-8 so a manifest is never mis-decoded.
$PSDefaultParameterValues['Get-Content:Encoding'] = 'UTF8'

if (-not $ProjectPath) { $ProjectPath = (Get-Location).Path }
if (-not $OrchestrationRoot) { $OrchestrationRoot = Join-Path $env:USERPROFILE '.claude\orchestration' }
if ($Final -and $Interim) { throw "-Final and -Interim are mutually exclusive." }

function Get-MarkerSessionId([string]$root) {
    $marker = Join-Path $root '.claude-spawn-worktree.json'
    if (Test-Path -LiteralPath $marker) {
        try {
            $j = Get-Content -LiteralPath $marker -Raw | ConvertFrom-Json
            if ($j.sessionId) { return [string]$j.sessionId }
        } catch { }
    }
    return $null
}

function Get-BranchSessionId([string]$path) {
    try {
        $prev = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        $b = & git -C $path rev-parse --abbrev-ref HEAD 2>$null
        $ErrorActionPreference = $prev
        if ($b) { $b = ($b | Select-Object -First 1).ToString().Trim() }
        if ($b -and $b -match '^sessions/(?<id>.+-session-\d+)$') { return $Matches['id'] }
    } catch { }
    return $null
}

function Resolve-ManifestPath([string]$slug) {
    if ($ManifestPath) { return $ManifestPath }
    if (-not $slug) { return $null }
    $p = Join-Path (Join-Path $OrchestrationRoot $slug) 'manifest.json'
    if (Test-Path -LiteralPath $p) { return $p }
    return $null
}

function Get-TagLetterFromManifest([string]$slug, [string]$id) {
    $mf = Resolve-ManifestPath $slug
    if (-not $mf) { return $null }
    try {
        $m = Get-Content -LiteralPath $mf -Raw | ConvertFrom-Json
        $entry = $m.sessions | Where-Object { $_.id -eq $id } | Select-Object -First 1
        if ($entry) {
            if ($entry.tagType -eq 'PARALLEL') { return 'p' }
            return 's'
        }
    } catch { }
    return $null
}

# --- Resolve identity -------------------------------------------------------------------------------
if (-not $MasterPlan -and -not $SessionId) {
    $SessionId = Get-MarkerSessionId $ProjectPath
    if (-not $SessionId) { $SessionId = Get-BranchSessionId $ProjectPath }
}
if (-not $Slug -and $SessionId -and $SessionId -match '^(?<slug>.+)-session-\d+$') {
    $Slug = $Matches['slug']
}

# --- Build the base name ----------------------------------------------------------------------------
if ($MasterPlan) {
    if (-not $Slug) {
        throw "master-plan export needs the plan slug: pass -Slug <slug> (e.g. -Slug logwarden)."
    }
    $base = "$Slug-master-plan"
}
else {
    if (-not $SessionId) {
        throw "Could not determine the session id. Pass -SessionId <slug>-session-N (or -MasterPlan -Slug <slug> for the planning session)."
    }
    if ($SessionId -notmatch '^(?<slug>.+)-session-(?<n>\d+)$') {
        throw "Session id '$SessionId' is not in '<slug>-session-N' form."
    }
    $n = [int]$Matches['n']
    if (-not $Slug) { $Slug = $Matches['slug'] }

    $letter = $Type
    if (-not $letter) { $letter = Get-TagLetterFromManifest $Slug $SessionId }
    if (-not $letter) {
        Write-Warning "No manifest tagType found for '$SessionId'; defaulting to 's' (sequential). Pass -Type s|p to override."
        $letter = 's'
    }
    $base = "{0}{1}-{2}" -f $n, $letter, $SessionId
}

# --- Suffix (interim / final) ----------------------------------------------------------------------
if ($Final) { $base = "$base-final" }
elseif ($Interim) { $base = "{0}-v{1}" -f $base, $Interim }

# --- Never overwrite an existing snapshot ----------------------------------------------------------
$logDir = Join-Path (Join-Path $ProjectPath 'session-logs') 'logs'
$name = $base
if (Test-Path -LiteralPath (Join-Path $logDir "$name.txt")) {
    $i = 2
    while (Test-Path -LiteralPath (Join-Path $logDir "$name-$i.txt")) { $i++ }
    $name = "$name-$i"
}

# --- Output ----------------------------------------------------------------------------------------
$relPath = "session-logs/logs/$name.txt"
if ($Raw) {
    Write-Output $name
}
else {
    Write-Output ("/export {0}" -f $relPath)
    Write-Output ("USER ACTION - type the line above in this tab to save the transcript snapshot to $relPath")
}
