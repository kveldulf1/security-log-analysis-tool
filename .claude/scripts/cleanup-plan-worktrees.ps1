# cleanup-plan-worktrees.ps1 - Remove stale per-session worktrees + branches
#
# Companion to spawn-plan-sessions.ps1 -PerSessionWorktrees. That spawner creates one git
# worktree + branch (sessions/<session-id>) per PARALLEL session under the sibling
# container <repoParent>\<repoName>.worktrees\. Once their branches have merged back, this
# script removes the merged worktrees and deletes their branches so stale worktrees don't
# accumulate. It is deliberately a SEPARATE script: cleanup runs days later, needs no plan
# file, and each created worktree carries a self-describing marker (.claude-spawn-worktree.json).
#
# Safety model (per git-safety rules):
#   - Only worktrees that are (a) under a *.worktrees\ container, (b) carry a valid marker,
#     and (c) sit on a sessions/* branch are ever candidates. The main worktree and any
#     foreign/unmarked worktree are always skipped.
#   - The DEFAULT pass removes only CLEAN + MERGED worktrees, with a plain `git worktree
#     remove` (no --force) and `git branch -d` (lowercase = refuses unmerged) as a 2nd net.
#   - DIRTY / UNMERGED worktrees are removed ONLY under -Force, and ONLY after an
#     individual per-item confirmation that -Yes does NOT bypass.
#   - LOCKED worktrees are never removed, even with -Force.
#
# Usage:
#   .\cleanup-plan-worktrees.ps1 -DryRun            # classify + show planned actions, remove nothing
#   .\cleanup-plan-worktrees.ps1                    # remove CLEAN+MERGED after one batch confirm
#   .\cleanup-plan-worktrees.ps1 -Yes               # ditto, no batch prompt
#   .\cleanup-plan-worktrees.ps1 -Slug ng-migration # only sessions whose id starts with the slug
#   .\cleanup-plan-worktrees.ps1 -Force             # also offer DIRTY/UNMERGED (per-item confirm)
#   .\cleanup-plan-worktrees.ps1 -KeepBranches      # remove worktrees but leave branches

param(
    [string]$RepoPath = (Get-Location).Path,   # any path inside the main repo
    [string]$Slug = "",                        # filter: session ids starting with this slug
    [string]$MergedInto = "",                  # merge target; default = current branch of main worktree
    [switch]$DryRun,
    [switch]$Yes,
    [switch]$Force,
    [switch]$KeepBranches
)

$MarkerName = ".claude-spawn-worktree.json"

function Test-SamePath {
    param([string]$A, [string]$B)
    if (-not $A -or -not $B) { return $false }
    $na = ($A -replace '/', '\').TrimEnd('\')
    $nb = ($B -replace '/', '\').TrimEnd('\')
    return [string]::Equals($na, $nb, [System.StringComparison]::OrdinalIgnoreCase)
}

# ---------------------------------------------------------------------------
# 1. Resolve repo root; hard error if not a git repo.
# ---------------------------------------------------------------------------

if (-not (Test-Path -LiteralPath $RepoPath)) {
    Write-Host "Path not found: $RepoPath" -ForegroundColor Red; exit 1
}
$RepoPath = (Resolve-Path -LiteralPath $RepoPath).Path

$top = (git -C $RepoPath rev-parse --show-toplevel 2>$null)
if ($LASTEXITCODE -ne 0 -or -not $top) {
    Write-Host "Not a git repository: $RepoPath" -ForegroundColor Red; exit 1
}
$repoRoot = (Resolve-Path -LiteralPath ($top.Trim())).Path

# The main worktree (never a candidate) is the top of the common dir's parent.
$mainTop = (git -C $repoRoot worktree list --porcelain 2>$null | Select-Object -First 1)
$mainWorktree = $repoRoot
if ($mainTop -match '^worktree\s+(.+)$') { $mainWorktree = $Matches[1].Trim() }

# Merge target: explicit -MergedInto or the current branch of the main worktree.
$target = $MergedInto
if (-not $target) {
    $target = (git -C $repoRoot rev-parse --abbrev-ref HEAD 2>$null)
    if ($target) { $target = $target.Trim() }
}
if (-not $target) {
    Write-Host "Could not determine a merge target branch; pass -MergedInto <branch>." -ForegroundColor Red; exit 1
}
$targetSha = (git -C $repoRoot rev-parse $target 2>$null)
if ($LASTEXITCODE -ne 0 -or -not $targetSha) {
    Write-Host "Merge target '$target' does not resolve to a commit." -ForegroundColor Red; exit 1
}
$targetSha = $targetSha.Trim()

# ---------------------------------------------------------------------------
# 2. Prune administrative records for already-deleted worktree dirs.
# ---------------------------------------------------------------------------

if ($DryRun) {
    git -C $repoRoot worktree prune --dry-run --verbose
} else {
    git -C $repoRoot worktree prune --verbose
}

# ---------------------------------------------------------------------------
# 3. Enumerate worktrees; keep only genuine session candidates.
# ---------------------------------------------------------------------------

function Get-WorktreeInventory {
    param([string]$RepoRoot)
    $out = (git -C $RepoRoot worktree list --porcelain 2>$null)
    $items = @()
    $cur = $null
    foreach ($ln in $out) {
        if ($ln -match '^worktree\s+(.+)$') {
            if ($cur) { $items += $cur }
            $cur = [PSCustomObject]@{ Path = $Matches[1].Trim(); Sha = ""; Branch = ""; Locked = $false }
        } elseif ($ln -match '^HEAD\s+(.+)$') {
            if ($cur) { $cur.Sha = $Matches[1].Trim() }
        } elseif ($ln -match '^branch\s+(.+)$') {
            if ($cur) { $cur.Branch = ($Matches[1].Trim() -replace '^refs/heads/', '') }
        } elseif ($ln -match '^locked') {
            if ($cur) { $cur.Locked = $true }
        }
    }
    if ($cur) { $items += $cur }
    return $items
}

$inv = Get-WorktreeInventory -RepoRoot $repoRoot
$candidates = @()
foreach ($w in $inv) {
    if (Test-SamePath $w.Path $mainWorktree) { continue }                 # never the main worktree
    if ($w.Path -notmatch '\.worktrees[\\/]') { continue }               # (a) under *.worktrees\
    $markerPath = Join-Path $w.Path $MarkerName
    if (-not (Test-Path -LiteralPath $markerPath)) { continue }          # (b) valid marker
    $marker = $null
    try { $marker = (Get-Content -Raw -LiteralPath $markerPath | ConvertFrom-Json) } catch { $marker = $null }
    if (-not $marker -or -not $marker.sessionId) { continue }
    if ($w.Branch -notmatch '^sessions/') { continue }                   # (c) sessions/* branch
    if ($Slug -and ($marker.sessionId -notlike "$Slug*")) { continue }   # -Slug filter
    $candidates += [PSCustomObject]@{
        SessionId = $marker.sessionId; Path = $w.Path; Branch = $w.Branch
        Sha = $w.Sha; Locked = $w.Locked; Marker = $marker
    }
}

# ---------------------------------------------------------------------------
# 4. Classify each candidate: LOCKED / DIRTY / UNMERGED / CLEAN+MERGED.
# ---------------------------------------------------------------------------

foreach ($c in $candidates) {
    if ($c.Locked) { $c | Add-Member State 'LOCKED' -Force; $c | Add-Member Unmerged 0 -Force; continue }

    # DIRTY = working tree changes other than the marker file itself.
    $statusLines = @(git -C $c.Path status --porcelain 2>$null | Where-Object {
        $_ -and ($_ -notmatch [regex]::Escape($MarkerName))
    })
    $isDirty = $statusLines.Count -gt 0

    # UNMERGED = branch tip is NOT an ancestor of the merge target.
    git -C $repoRoot merge-base --is-ancestor $c.Sha $targetSha 2>$null | Out-Null
    $isMerged = ($LASTEXITCODE -eq 0)
    $ahead = 0
    if (-not $isMerged) {
        $cnt = (git -C $repoRoot rev-list --count "$target..$($c.Branch)" 2>$null)
        if ($cnt) { $ahead = [int]($cnt.Trim()) }
    }
    $c | Add-Member Unmerged $ahead -Force

    if ($isDirty) { $c | Add-Member State 'DIRTY' -Force }
    elseif (-not $isMerged) { $c | Add-Member State 'UNMERGED' -Force }
    else { $c | Add-Member State 'CLEAN+MERGED' -Force }
}

# ---------------------------------------------------------------------------
# 5. Always print the classification table first.
# ---------------------------------------------------------------------------

Write-Host ""
Write-Host "=== Cleanup Plan Worktrees ===" -ForegroundColor Cyan
Write-Host "  Repo        : $repoRoot" -ForegroundColor DarkGray
Write-Host "  Merge target: $target ($($targetSha.Substring(0, [Math]::Min(12, $targetSha.Length))))" -ForegroundColor DarkGray
if ($Slug) { Write-Host "  Slug filter : $Slug" -ForegroundColor DarkGray }
Write-Host "  Candidates  : $($candidates.Count)" -ForegroundColor DarkGray
Write-Host ""

if ($candidates.Count -eq 0) {
    Write-Host "No session worktrees to clean up." -ForegroundColor Green
    exit 0
}

foreach ($c in $candidates) {
    $action = switch ($c.State) {
        'CLEAN+MERGED' { 'remove + delete branch' }
        'LOCKED'       { 'skip (locked)' }
        default        { if ($Force) { 'offer removal (-Force, per-item confirm)' } else { 'skip (needs -Force)' } }
    }
    if (-not $KeepBranches) { } else { if ($action -eq 'remove + delete branch') { $action = 'remove (keep branch)' } }
    $color = switch ($c.State) {
        'CLEAN+MERGED' { 'Green' }
        'LOCKED'       { 'DarkGray' }
        default        { 'Yellow' }
    }
    $extra = if ($c.State -eq 'UNMERGED') { " ($($c.Unmerged) unmerged commit(s))" } else { "" }
    Write-Host ("  [{0}] {1}" -f $c.State, $c.SessionId) -ForegroundColor $color
    Write-Host ("        {0} -> {1}{2}" -f $c.Branch, $c.Path, $extra) -ForegroundColor DarkGray
    Write-Host ("        action: {0}" -f $action) -ForegroundColor DarkGray
}
Write-Host ""

# ---------------------------------------------------------------------------
# 6. DryRun stops here.
# ---------------------------------------------------------------------------

if ($DryRun) {
    Write-Host "[DryRun] Nothing removed." -ForegroundColor Yellow
    exit 0
}

$removed = @(); $kept = @(); $failed = @()

function Remove-OneWorktree {
    param($Cand, [switch]$UseForce)
    $wtArgs = @('-C', $repoRoot, 'worktree', 'remove', $Cand.Path)
    if ($UseForce) { $wtArgs = @('-C', $repoRoot, 'worktree', 'remove', '--force', $Cand.Path) }
    git @wtArgs
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  [fail] worktree remove failed for $($Cand.SessionId)" -ForegroundColor Red
        return $false
    }
    if (-not $KeepBranches) {
        if ($UseForce) { git -C $repoRoot branch -D $Cand.Branch | Out-Null }
        else { git -C $repoRoot branch -d $Cand.Branch }
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  [warn] branch delete failed for $($Cand.Branch) (worktree removed)" -ForegroundColor Yellow
        }
    }
    return $true
}

# ---------------------------------------------------------------------------
# 7. Default pass: CLEAN+MERGED only, one batch confirm.
# ---------------------------------------------------------------------------

$cleanMerged = @($candidates | Where-Object { $_.State -eq 'CLEAN+MERGED' })
if ($cleanMerged.Count -gt 0) {
    $go = $true
    if (-not $Yes) {
        Write-Host "About to remove $($cleanMerged.Count) CLEAN+MERGED worktree(s)$(if (-not $KeepBranches) { ' and delete their branches' })." -ForegroundColor Yellow
        $answer = Read-Host "Continue? [y/N]"
        if ($answer -notmatch '^(y|yes)$') { $go = $false; Write-Host "Skipped clean removals." -ForegroundColor DarkGray }
    }
    if ($go) {
        foreach ($c in $cleanMerged) {
            Write-Host "Removing $($c.SessionId) ..." -ForegroundColor Green
            if (Remove-OneWorktree -Cand $c) { $removed += $c } else { $failed += $c }
        }
    } else {
        $kept += $cleanMerged
    }
}

# ---------------------------------------------------------------------------
# 8. -Force pass: DIRTY / UNMERGED, per-item confirm that -Yes does NOT bypass.
# ---------------------------------------------------------------------------

$risky = @($candidates | Where-Object { $_.State -eq 'DIRTY' -or $_.State -eq 'UNMERGED' })
foreach ($c in $risky) {
    if (-not $Force) { $kept += $c; continue }
    Write-Host ""
    Write-Host "[$($c.State)] $($c.SessionId)  $($c.Branch) -> $($c.Path)" -ForegroundColor Yellow
    if ($c.State -eq 'DIRTY') {
        Write-Host "  uncommitted changes:" -ForegroundColor DarkYellow
        git -C $c.Path status --short
    } else {
        Write-Host "  $($c.Unmerged) commit(s) not in ${target}:" -ForegroundColor DarkYellow
        git -C $repoRoot log "$target..$($c.Branch)" --oneline
    }
    # This confirm is intentionally NOT bypassable by -Yes (force-removing loses work).
    $answer = Read-Host "Force-remove this worktree and its branch? [y/N]"
    if ($answer -match '^(y|yes)$') {
        Write-Host "Force-removing $($c.SessionId) ..." -ForegroundColor Red
        if (Remove-OneWorktree -Cand $c -UseForce) { $removed += $c } else { $failed += $c }
    } else {
        Write-Host "  kept." -ForegroundColor DarkGray
        $kept += $c
    }
}

# Locked worktrees are always kept.
$kept += @($candidates | Where-Object { $_.State -eq 'LOCKED' })

# ---------------------------------------------------------------------------
# 9. Final prune; drop the container dir if now empty; summary.
# ---------------------------------------------------------------------------

git -C $repoRoot worktree prune | Out-Null

if ($removed.Count -gt 0) {
    $containers = $removed | ForEach-Object { Split-Path -Parent $_.Path } | Sort-Object -Unique
    foreach ($dir in $containers) {
        if (Test-Path -LiteralPath $dir) {
            $remaining = @(Get-ChildItem -LiteralPath $dir -Force -ErrorAction SilentlyContinue)
            if ($remaining.Count -eq 0) {
                Remove-Item -LiteralPath $dir -Force -ErrorAction SilentlyContinue
                Write-Host "Removed empty container: $dir" -ForegroundColor DarkGray
            }
        }
    }
}

Write-Host ""
Write-Host "[OK] Cleanup done. Removed $($removed.Count), kept $($kept.Count), failed $($failed.Count)." -ForegroundColor Green
if ($removed.Count -gt 0) { $removed | ForEach-Object { Write-Host "  removed: $($_.SessionId)" -ForegroundColor DarkGray } }
if ($kept.Count -gt 0)    { $kept    | ForEach-Object { Write-Host "  kept   : $($_.SessionId) [$($_.State)]" -ForegroundColor DarkGray } }
if ($failed.Count -gt 0)  { $failed  | ForEach-Object { Write-Host "  failed : $($_.SessionId)" -ForegroundColor Red } }
