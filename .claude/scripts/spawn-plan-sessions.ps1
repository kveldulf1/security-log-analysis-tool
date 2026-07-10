# spawn-plan-sessions.ps1 - Open one named Windows Terminal tab per plan session
#
# Reads a plan file produced by the /split-plan-into-sessions skill, and for each
# "### <slug>-session-N" entry opens a named Windows Terminal tab running an
# interactive Claude session in the chosen worktree, then delivers that session's
# cold-start prompt by injecting it into the tab (via spawn-session-tab.ps1).
#
# WHY inject (not a positional prompt): interactive `claude "<prompt>"` does NOT
# auto-submit the positional prompt - it only runs in -p/print mode (which exits).
# So each tab launches interactive Claude and injects the prompt into its own
# console input buffer (WriteConsoleInput) once the TUI is up. That is
# foreground-independent, so tabs don't fight over focus and can all open at once.
#
# Auto-submit is driven by each session's "**Parallelization:**" line:
#   - "blocked by none"      -> AUTO: safe to start now -> inject prompt + Enter.
#   - "blocked by <ids>"     -> GATED: the tab lazy-boots (waits in plain PowerShell, no claude
#                               process) until every prerequisite signals .done, then self-boots
#                               and self-submits - zero tokens, no manual Enter.
#   - "blocked by <prose>" with no parseable session id, or no Parallelization line
#                            -> HELD: inject prompt only; you press Enter yourself.
#
# Orchestration state lives OUTSIDE the repo under
# $env:USERPROFILE\.claude\orchestration\<plan-slug>\ : a manifest.json (static DAG), per-session
# prompt files, reports, and .done/.failed/.aborted sentinels. -Reset archives prior state (never
# deletes it); -Resume skips sessions already marked .done. Progress: orchestration-status.ps1.
#
# Titles are pinned with `wt --title <id> --suppressApplicationTitle` so Claude's TUI
# cannot repaint them.
#
# PARALLEL isolation (-PerSessionWorktrees): by default every tab shares ONE git
# worktree/branch, so a session's end-of-session `git add`/`commit` can sweep up a
# concurrent session's half-finished edits. Pass -PerSessionWorktrees to give each
# PARALLEL session its own git worktree + branch (sessions/<session-id>) under the
# sibling container <repoParent>\<repoName>.worktrees\. SEQUENTIAL/solo sessions
# keep the shared main worktree (they need prior sessions' commits visible). Before
# spawning, each fresh worktree path is pre-registered as trusted in ~/.claude.json
# (rolling backup .claude.json.spawn-trust.bak) so claude's first-run trust dialog
# cannot swallow the injected prompt - see Register-SpawnWorktreeTrust.
#
# FRESH-ALWAYS: every run starts each PARALLEL session from a clean worktree created
# off the base ref - it never silently reattaches to a previous run's leftover. A stale
# spawn-managed worktree/branch is discarded and recreated automatically and SILENTLY
# (no per-worktree prompt). The one exception, for safety, is a leftover that still holds
# uncommitted changes or commits not merged into the base ref: that aborts with a message
# (merge it, run cleanup-plan-worktrees.ps1, or pass -Force to discard it anyway). A
# directory or branch that is NOT spawn-managed is never touched - it aborts instead.
#
# Usage:
#   .\spawn-plan-sessions.ps1 -PlanFile 'C:\Users\me\.claude\plans\ng-migration.md'
#   .\spawn-plan-sessions.ps1 -PlanFile '...' -WorktreePath 'C:\...\worktrees\my-branch' -Yes
#   .\spawn-plan-sessions.ps1 -PlanFile '...' -DryRun
#   .\spawn-plan-sessions.ps1 -PlanFile '...' -PerSessionWorktrees        # isolate PARALLEL sessions (fresh)
#   .\spawn-plan-sessions.ps1 -PlanFile '...' -PerSessionWorktrees -NoTabs # create worktrees, no wt.exe
#   .\spawn-plan-sessions.ps1 -PlanFile '...' -PerSessionWorktrees -Force  # discard even unmerged leftovers
#   .\spawn-plan-sessions.ps1 -PlanFile '...' -BootDelaySeconds 8   # raise if Claude is slow to boot
#   .\spawn-plan-sessions.ps1 -PlanFile '...' -Permissions auto     # tabs use --permission-mode auto
#   .\spawn-plan-sessions.ps1 -PlanFile '...' -Reset               # archive prior state, start fresh
#   .\spawn-plan-sessions.ps1 -PlanFile '...' -Resume              # skip sessions already .done

param(
    [Parameter(Mandatory = $true)] [string]$PlanFile,
    [string]$WorktreePath = (Get-Location).Path,
    [switch]$Yes,
    [switch]$DryRun,
    [switch]$PerSessionWorktrees,
    [switch]$NoTabs,
    [switch]$Force,
    [string]$BaseRef = "",
    [int]$BootDelaySeconds = 15,
    [ValidateSet('low', 'medium', 'high', 'xhigh', 'max')] [string]$Effort = 'high',
    [switch]$Reset,
    [switch]$Resume,
    [ValidateSet('skip', 'auto')] [string]$Permissions = ''
)

# ---------------------------------------------------------------------------
# Validate inputs
# ---------------------------------------------------------------------------

if (-not (Test-Path -LiteralPath $PlanFile)) {
    Write-Host "Plan file not found: $PlanFile" -ForegroundColor Red; exit 1
}
$PlanFile = (Resolve-Path -LiteralPath $PlanFile).Path

if (-not (Test-Path -LiteralPath $WorktreePath)) {
    Write-Host "Worktree path not found: $WorktreePath" -ForegroundColor Red; exit 1
}
$WorktreePath = (Resolve-Path -LiteralPath $WorktreePath).Path

# wt.exe is only needed when we will actually open tabs (not under -DryRun or -NoTabs).
if (-not $DryRun -and -not $NoTabs) {
    if (-not (Get-Command wt.exe -ErrorAction SilentlyContinue)) {
        Write-Host "wt.exe (Windows Terminal) not found on PATH. Install it or use -DryRun / -NoTabs." -ForegroundColor Red; exit 1
    }
}

# ---------------------------------------------------------------------------
# Per-session git worktree support (-PerSessionWorktrees)
# ---------------------------------------------------------------------------

$MarkerName = ".claude-spawn-worktree.json"

function Test-SamePath {
    param([string]$A, [string]$B)
    if (-not $A -or -not $B) { return $false }
    $na = ($A -replace '/', '\').TrimEnd('\')
    $nb = ($B -replace '/', '\').TrimEnd('\')
    return [string]::Equals($na, $nb, [System.StringComparison]::OrdinalIgnoreCase)
}

# Resolve repo root / name / sibling container / base SHA / current branch from a path
# inside the target repo. Hard error (exit 1) if the path is not inside a git repo.
function Get-RepoInfo {
    param([string]$Path, [string]$BaseRef)
    $top = (git -C $Path rev-parse --show-toplevel 2>$null)
    if ($LASTEXITCODE -ne 0 -or -not $top) {
        Write-Host "-PerSessionWorktrees requires a git repository, but '$Path' is not inside one." -ForegroundColor Red
        exit 1
    }
    $repoRoot = (Resolve-Path -LiteralPath ($top.Trim())).Path
    $repoName = Split-Path -Leaf $repoRoot
    $repoParent = Split-Path -Parent $repoRoot
    $container = Join-Path $repoParent ($repoName + ".worktrees")

    $commonDir = (git -C $repoRoot rev-parse --git-common-dir 2>$null)
    if ($LASTEXITCODE -ne 0 -or -not $commonDir) {
        Write-Host "Could not resolve the git common dir for '$repoRoot'." -ForegroundColor Red; exit 1
    }
    $commonDir = $commonDir.Trim()
    if (-not [System.IO.Path]::IsPathRooted($commonDir)) {
        $commonDir = Join-Path $repoRoot $commonDir
    }
    $commonDir = (Resolve-Path -LiteralPath $commonDir).Path

    $ref = if ($BaseRef) { $BaseRef } else { "HEAD" }
    $baseSha = (git -C $repoRoot rev-parse $ref 2>$null)
    if ($LASTEXITCODE -ne 0 -or -not $baseSha) {
        Write-Host "Could not resolve base ref '$ref' in '$repoRoot'." -ForegroundColor Red; exit 1
    }
    $baseSha = $baseSha.Trim()

    $curBranch = (git -C $repoRoot rev-parse --abbrev-ref HEAD 2>$null)
    if ($curBranch) { $curBranch = $curBranch.Trim() } else { $curBranch = "(detached)" }

    $dirty = (git -C $repoRoot status --porcelain 2>$null)
    if ($dirty) {
        Write-Host "  [warn] base worktree '$repoRoot' has uncommitted changes - they will NOT be visible in new worktrees." -ForegroundColor Yellow
    }

    return [PSCustomObject]@{
        RepoRoot = $repoRoot; RepoName = $repoName; Container = $container
        CommonDir = $commonDir; BaseSha = $baseSha; BaseRef = $ref; BaseBranch = $curBranch
    }
}

# Parse `git worktree list --porcelain` into {Path, Sha, Branch, Locked} objects.
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

# Count commits on $Branch that are not reachable from $BaseSha (i.e. real, unmerged work).
function Get-BranchAheadCount {
    param([string]$RepoRoot, [string]$Branch, [string]$BaseSha)
    $c = (git -C $RepoRoot rev-list --count "$Branch" "^$BaseSha" 2>$null)
    if ($LASTEXITCODE -ne 0 -or -not $c) { return 0 }
    return [int]($c.Trim())
}

# True if the worktree at $Path has uncommitted (tracked or untracked) changes.
function Test-WorktreeDirty {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return $false }
    $d = (git -C $Path status --porcelain 2>$null)
    return [bool]$d
}

# Per PARALLEL session decide Create / Recreate / Error; SEQUENTIAL -> Shared.
# FRESH-ALWAYS: a spawn-managed leftover from a previous run is Recreate (torn down and
# rebuilt), never reattached - unless it holds uncommitted or unmerged work and -Force is
# absent, which is an Error. Anything not spawn-managed is an Error (never touched).
# Returns a list of error strings; a non-empty list means the caller must abort BEFORE
# creating anything or spawning any tab (fail-fast).
function Resolve-SessionWorktreePlan {
    param($Sessions, $RepoInfo)
    $inv = Get-WorktreeInventory -RepoRoot $RepoInfo.RepoRoot
    $errors = @()
    foreach ($s in $Sessions) {
        if ($s.TagType -ne 'PARALLEL') {
            $s.Worktree = $script:WorktreePath; $s.WtAction = 'Shared'; $s.WtBranch = ''
            continue
        }
        $expBranch = "sessions/" + $s.Id
        $expPath = Join-Path $RepoInfo.Container $s.Id
        $regAtPath = $inv | Where-Object { Test-SamePath $_.Path $expPath } | Select-Object -First 1
        $branchWt = $inv | Where-Object { $_.Branch -eq $expBranch } | Select-Object -First 1
        $bl = (git -C $RepoInfo.RepoRoot branch --list $expBranch 2>$null)
        $branchExists = [bool]$bl
        $markerPath = Join-Path $expPath $MarkerName

        $s.Worktree = $expPath
        $s.WtBranch = $expBranch

        # Foreign obstructions we must never disturb.
        if ($regAtPath -and $regAtPath.Branch -ne $expBranch) {
            $s.WtAction = 'Error'
            $errors += "$($s.Id): worktree path '$expPath' is registered to branch '$($regAtPath.Branch)', not '$expBranch' - remove it manually."
            continue
        }
        if ((Test-Path -LiteralPath $expPath) -and (-not $regAtPath) -and (-not (Test-Path -LiteralPath $markerPath))) {
            $s.WtAction = 'Error'
            $errors += "$($s.Id): '$expPath' exists, is not a registered worktree, and has no $MarkerName marker - remove it manually."
            continue
        }
        if ($branchWt -and (-not (Test-SamePath $branchWt.Path $expPath)) -and (-not (Test-SamePath (Split-Path -Parent $branchWt.Path) $RepoInfo.Container))) {
            $s.WtAction = 'Error'
            $errors += "$($s.Id): branch '$expBranch' is checked out at '$($branchWt.Path)', outside the spawn container - resolve it manually."
            continue
        }

        $leftoverExists = [bool]$regAtPath -or (Test-Path -LiteralPath $expPath) -or $branchExists -or [bool]$branchWt
        if (-not $leftoverExists) {
            $s.WtAction = 'Create'
            continue
        }

        # Spawn-managed leftover -> discard and recreate fresh, but protect real work.
        $ahead = if ($branchExists) { Get-BranchAheadCount -RepoRoot $RepoInfo.RepoRoot -Branch $expBranch -BaseSha $RepoInfo.BaseSha } else { 0 }
        $dirty = Test-WorktreeDirty -Path $expPath
        if ((-not $script:Force) -and ($dirty -or $ahead -gt 0)) {
            $why = if ($dirty -and $ahead -gt 0) { "$ahead commit(s) not merged into $($RepoInfo.BaseRef) and uncommitted changes" }
                   elseif ($ahead -gt 0) { "$ahead commit(s) not merged into $($RepoInfo.BaseRef)" }
                   else { "uncommitted changes" }
            $s.WtAction = 'Error'
            $errors += "$($s.Id): leftover worktree/branch '$expBranch' has $why. Merge it, run cleanup-plan-worktrees.ps1, or pass -Force to discard and start fresh."
            continue
        }
        $s.WtAction = 'Recreate'
    }
    return $errors
}

# Execute one Create/Attach decision: add the worktree, write the marker JSON, ensure
# the marker filename is git-ignored (shared .git\info\exclude), print a deps reminder.
function New-SessionWorktree {
    param($Session, $RepoInfo, [string]$PlanFile)
    $path = $Session.Worktree
    $branch = $Session.WtBranch
    if ($Session.WtAction -eq 'Recreate') {
        # Tear the stale spawn-managed worktree + branch down, then fall through to a fresh create.
        $reg = (Get-WorktreeInventory -RepoRoot $RepoInfo.RepoRoot | Where-Object { Test-SamePath $_.Path $path } | Select-Object -First 1)
        if ($reg) {
            git -C $RepoInfo.RepoRoot worktree remove --force $path | Out-Null
        } elseif (Test-Path -LiteralPath $path) {
            Remove-Item -LiteralPath $path -Recurse -Force -ErrorAction SilentlyContinue
        }
        $bwt = (Get-WorktreeInventory -RepoRoot $RepoInfo.RepoRoot | Where-Object { $_.Branch -eq $branch } | Select-Object -First 1)
        if ($bwt) { git -C $RepoInfo.RepoRoot worktree remove --force $bwt.Path | Out-Null }
        git -C $RepoInfo.RepoRoot worktree prune | Out-Null
        if (git -C $RepoInfo.RepoRoot branch --list $branch 2>$null) { git -C $RepoInfo.RepoRoot branch -D $branch | Out-Null }
    }
    if ($Session.WtAction -eq 'Create' -or $Session.WtAction -eq 'Recreate') {
        git -C $RepoInfo.RepoRoot worktree add -b $branch $path $RepoInfo.BaseSha | Out-Null
        if ($LASTEXITCODE -ne 0) { Write-Host "  [error] failed to create worktree for $($Session.Id)" -ForegroundColor Red; return $false }
    } else {
        return $true   # Shared: nothing to create
    }

    $marker = [PSCustomObject]@{
        sessionId  = $Session.Id
        planFile   = $PlanFile
        branch     = $branch
        baseSha    = $RepoInfo.BaseSha
        baseBranch = $RepoInfo.BaseBranch
        createdUtc = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
        tool       = "spawn-plan-sessions.ps1"
    }
    $markerPath = Join-Path $path $MarkerName
    ($marker | ConvertTo-Json) | Set-Content -LiteralPath $markerPath -Encoding Ascii

    # Ignore the marker in every worktree via the shared, non-versioned .git\info\exclude.
    $excludeFile = Join-Path $RepoInfo.CommonDir "info\exclude"
    $already = $false
    if (Test-Path -LiteralPath $excludeFile) {
        foreach ($el in (Get-Content -LiteralPath $excludeFile)) {
            if ($el.Trim() -eq $MarkerName) { $already = $true; break }
        }
    }
    if (-not $already) { Add-Content -LiteralPath $excludeFile -Value $MarkerName -Encoding Ascii }

    Write-Host "  [deps] $($Session.Id): run your project's install step in $path if needed" -ForegroundColor DarkGray
    return $true
}

# ---------------------------------------------------------------------------
# Pre-register Claude Code folder trust for spawn-managed worktrees.
#
# WHY: interactive claude shows a first-run "Do you trust the files in this folder?"
# dialog for a folder it has never seen. --dangerously-skip-permissions does NOT suppress
# it, and the bracketed-paste prompt spawn-session-tab.ps1 injects lands on that dialog and
# is swallowed - the session boots but never submits. Parent-dir trust does not cascade and
# a worktree does not inherit the main repo's trust, so each fresh per-session worktree hits
# this. There is no supported CLI flag/env for interactive sessions (only `claude -p` skips
# the check), so we pre-seed the per-project trust the CLI keeps in
# $env:USERPROFILE\.claude.json under "projects" (forward-slash path keys).
#
# SAFETY: that file also holds OAuth/account state - never print its contents; messages
# carry only counts and path keys. PS 5.1 ConvertFrom-Json CANNOT parse this file (it holds
# empty-string keys), so the read-modify-write uses System.Web JavaScriptSerializer, whose
# round-trip is byte-stable on the real file. We validate-then-swap: verify the serializer is
# round-trip stable on THIS file (so a lossy re-serialize of an unrelated entry can't slip past
# the key-level checks), mutate in memory, serialize, assert nothing was lost, write a temp file
# (UTF-8 no BOM - the file holds raw non-ASCII), re-parse the temp, and only then File.Replace()
# atomically with a rolling backup. Any failure leaves the original untouched and only warns
# (spawn continues; worst case is the pre-fix behavior - a trust dialog).
#
# CONCURRENCY: this is an unlocked read-modify-write of a file the live CLI also owns. File.Replace
# swaps in our whole snapshot, so a concurrent CLI write landing between our read and our swap would
# otherwise be reverted (a lost update - e.g. a token refresh or another folder's just-granted
# trust). We guard it: capture the file text at read and, immediately before each Replace attempt,
# re-read and abort if it changed on disk (skip rather than clobber - worst case is the old dialog,
# never someone else's lost write). The residual TOCTOU window is sub-millisecond; there is no
# cross-process lock available for this file.
# ---------------------------------------------------------------------------

# The static keys the CLI itself writes for a trusted project (mirrors a real trusted entry
# on this machine, minus the runtime-stats keys it appends after a session). Guaranteed
# equivalent to a CLI-accepted trust, without guessing a minimal subset. Built by
# deserializing a template so the value types (Object[]/Dictionary/bool/int) exactly match
# the graph the rest of the file parses to - hand-built PowerShell literals (@(), etc.) make
# JavaScriptSerializer throw a PSParameterizedProperty circular-reference error on Serialize.
function New-TrustProjectEntry {
    param($Ser)
    $tmpl = '{"allowedTools":[],"mcpContextUris":[],"mcpServers":{},"enabledMcpjsonServers":[],"disabledMcpjsonServers":[],"hasTrustDialogAccepted":true,"projectOnboardingSeenCount":0,"hasClaudeMdExternalIncludesApproved":false,"hasClaudeMdExternalIncludesWarningShown":false}'
    return $Ser.DeserializeObject($tmpl)
}

# Re-parse a serialized config and assert the rewrite lost nothing we care about. Throws
# (into the caller's catch) with key NAMES only - never values.
function Assert-TrustConfig {
    param($Ser, [string]$Json, [string[]]$OrigTopKeys, [string[]]$OrigProjKeys, [string[]]$NeededKeys)
    $chk = $Ser.DeserializeObject($Json)   # throws if the JSON is invalid
    foreach ($k in $OrigTopKeys) { if (-not $chk.ContainsKey($k)) { throw "top-level key '$k' lost in rewrite" } }
    if (@($chk.Keys).Count -ne @($OrigTopKeys).Count) { throw "top-level key count changed in rewrite" }
    $projs = $chk['projects']
    foreach ($k in $OrigProjKeys) { if (-not $projs.ContainsKey($k)) { throw "project entry '$k' lost in rewrite" } }
    # -cnotcontains (case-SENSITIVE) to match the ordinal Dictionary.ContainsKey the mutation uses;
    # a case-insensitive delta here would miscount when a needed key differs only in case from an
    # existing one and spuriously throw, aborting the whole registration.
    $addN = @($NeededKeys | Where-Object { $OrigProjKeys -cnotcontains $_ }).Count
    if (@($projs.Keys).Count -ne (@($OrigProjKeys).Count + $addN)) { throw "unexpected project count after rewrite" }
    foreach ($k in $NeededKeys) {
        if (-not ($projs.ContainsKey($k) -and ($projs[$k]['hasTrustDialogAccepted'] -eq $true))) {
            throw "trust entry for '$k' missing after rewrite"
        }
    }
}

# Idempotently mark each per-session worktree path trusted in ~/.claude.json. Returns $true on
# success/no-op, $false on any failure. NEVER throws to the caller - spawning always continues.
function Register-SpawnWorktreeTrust {
    param($Sessions, $RepoInfo)

    $targets = @($Sessions | Where-Object { $_.WtAction -ne 'Shared' } | ForEach-Object { $_.Worktree })
    if (@($targets).Count -eq 0) { return $true }

    # CLI key format: forward slashes, no trailing slash. Scope guard: only ever register paths
    # under this run's spawn-managed container - never blanket-trust an arbitrary folder.
    $containerKey = ($RepoInfo.Container -replace '\\', '/').TrimEnd('/')
    $keys = @()
    foreach ($t in $targets) {
        $k = ($t -replace '\\', '/').TrimEnd('/')
        if ($k.StartsWith($containerKey + '/', [System.StringComparison]::OrdinalIgnoreCase)) { $keys += $k }
        else { Write-Host "  [trust][warn] $k is outside $containerKey - not registering." -ForegroundColor Yellow }
    }
    if (@($keys).Count -eq 0) { return $true }

    $cfgPath = Join-Path $env:USERPROFILE '.claude.json'
    if (-not (Test-Path -LiteralPath $cfgPath)) {
        Write-Host "  [trust][warn] $cfgPath not found - skipping trust pre-registration." -ForegroundColor Yellow
        return $false
    }

    $tmpPath = $cfgPath + '.spawn-trust.tmp'
    $bakPath = $cfgPath + '.spawn-trust.bak'
    try {
        Add-Type -AssemblyName System.Web.Extensions
        $ser = New-Object System.Web.Script.Serialization.JavaScriptSerializer
        $ser.MaxJsonLength = [int]::MaxValue
        $ser.RecursionLimit = 1000

        $origText = [System.IO.File]::ReadAllText($cfgPath)   # snapshot for the concurrent-write guard
        $cfg = $ser.DeserializeObject($origText)
        if (-not $cfg.ContainsKey('projects')) {
            $cfg['projects'] = New-Object 'System.Collections.Generic.Dictionary[string,object]'
        }
        $projects = $cfg['projects']

        # Idempotency: only touch paths not already trusted; zero -> no write at all.
        $needed = @()
        foreach ($k in $keys) {
            $trusted = $false
            if ($projects.ContainsKey($k)) {
                $e = $projects[$k]
                # Use .ContainsKey (single overload on the generic dict). NOT .Contains: a
                # Dictionary[string,object] exposes two Contains overloads and calling it on the
                # object-typed value fails PS overload resolution, even when cast to IDictionary
                # ("Cannot find an overload for Contains and the argument count 1").
                if (($e -is [System.Collections.Generic.IDictionary[string,object]]) -and $e.ContainsKey('hasTrustDialogAccepted') -and ($e['hasTrustDialogAccepted'] -eq $true)) {
                    $trusted = $true
                }
            }
            if (-not $trusted) { $needed += $k }
        }
        if (@($needed).Count -eq 0) {
            Write-Host "  [trust] all $(@($keys).Count) worktree path(s) already trusted in ~/.claude.json" -ForegroundColor DarkGray
            return $true
        }

        # Snapshot AFTER ensuring 'projects' exists, BEFORE adding the needed keys.
        $origTopKeys  = @($cfg.Keys)
        $origProjKeys = @($projects.Keys)

        # Fidelity guard: the serializer must reproduce this file's content on a bare round-trip.
        # If it does, our only delta below is the added keys (a deterministic append), so an
        # unrelated entry cannot be silently altered - something the key-level Assert cannot see.
        $baseline = $ser.Serialize($cfg)
        if ($baseline -ne $ser.Serialize($ser.DeserializeObject($baseline))) {
            throw "JavaScriptSerializer is not round-trip stable on this .claude.json - refusing to rewrite"
        }

        foreach ($k in $needed) {
            # Set the flag in place only when the existing value is a real dictionary; otherwise
            # (absent, or a malformed non-dictionary entry for this scoped worktree path) write a
            # fresh entry. Indexing into a non-dictionary would throw and abort all registration.
            if ($projects.ContainsKey($k) -and ($projects[$k] -is [System.Collections.Generic.IDictionary[string,object]])) {
                $projects[$k]['hasTrustDialogAccepted'] = $true
            } else {
                $projects[$k] = New-TrustProjectEntry -Ser $ser
            }
        }

        $json = $ser.Serialize($cfg)
        Assert-TrustConfig -Ser $ser -Json $json -OrigTopKeys $origTopKeys -OrigProjKeys $origProjKeys -NeededKeys $needed
        [System.IO.File]::WriteAllText($tmpPath, $json, (New-Object System.Text.UTF8Encoding($false)))
        Assert-TrustConfig -Ser $ser -Json ([System.IO.File]::ReadAllText($tmpPath)) -OrigTopKeys $origTopKeys -OrigProjKeys $origProjKeys -NeededKeys $needed

        # Atomic swap with a rolling backup. Re-read and bail if the file changed on disk since our
        # snapshot (a concurrent CLI write we must not clobber), and retry a few times for transient
        # sharing violations from a session that has the file briefly open.
        $replaced = $false
        for ($i = 0; $i -lt 3; $i++) {
            if ([System.IO.File]::ReadAllText($cfgPath) -ne $origText) {
                throw "config changed on disk since read (concurrent write) - skipping to avoid clobbering it"
            }
            try { [System.IO.File]::Replace($tmpPath, $cfgPath, $bakPath, $true); $replaced = $true; break }
            catch { if ($i -eq 2) { throw }; Start-Sleep -Milliseconds 150 }
        }

        Write-Host "  [trust] pre-registered $(@($needed).Count) worktree path(s) in ~/.claude.json (backup: .claude.json.spawn-trust.bak)" -ForegroundColor DarkGray
        return $true
    } catch {
        if (Test-Path -LiteralPath $tmpPath) { Remove-Item -LiteralPath $tmpPath -Force -ErrorAction SilentlyContinue }
        Write-Host "  [trust][warn] could not pre-register worktree trust ($($_.Exception.Message)) - fresh-worktree tabs may show a trust dialog that swallows the injected prompt." -ForegroundColor Yellow
        return $false
    }
}

# ---------------------------------------------------------------------------
# Parse the plan file's "## Session Breakdown" section
# ---------------------------------------------------------------------------

$lines = Get-Content -LiteralPath $PlanFile -Encoding UTF8

$startIdx = -1
for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match '^##\s+Session Breakdown\b') { $startIdx = $i; break }
}
if ($startIdx -lt 0) {
    Write-Host "No '## Session Breakdown' section found in: $PlanFile" -ForegroundColor Red
    Write-Host "Run /split-plan-into-sessions on the plan first." -ForegroundColor DarkGray
    exit 1
}
$endIdx = $lines.Count
for ($i = $startIdx + 1; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match '^##\s+' -and $lines[$i] -notmatch '^###') { $endIdx = $i; break }
}
$section = $lines[$startIdx..($endIdx - 1)]

$sessions = @()
$curId   = $null
$curName = ""
$curBody = @()

function Add-Session {
    param($id, $name, $body)
    if (-not $id) { return }

    # Cold-start prompt = the blockquote run after the "**Cold-start prompt**" marker.
    $promptLines = @()
    $inBlock = $false
    $seenMarker = $false
    foreach ($ln in $body) {
        if (-not $seenMarker) {
            if ($ln -match '^\s*\*\*Cold-start prompt') { $seenMarker = $true }
            continue
        }
        if ($ln -match '^\s*>') { $inBlock = $true; $promptLines += ($ln -replace '^\s*>\s?', '') }
        elseif ($inBlock) { break }
    }
    $prompt = (($promptLines -join ' ') -replace '\s+', ' ').Trim()
    if (-not $prompt) {
        Write-Host "  [skip] $id - no cold-start prompt blockquote found." -ForegroundColor Yellow
        return
    }

    # Parallel-safety: parse the "**Parallelization:**" line. Auto-submit only when
    # the session is provably unblocked ("blocked by none").
    $parLine = ($body | Where-Object { $_ -match '^\s*\*\*Parallelization' } | Select-Object -First 1)
    $blocked = $true
    $blockers = "(no Parallelization line - held for safety)"
    if ($parLine) {
        # Capture "blocked by <...>" up to the next field label ("shared write" / "mode")
        # or EOL. ASCII-only (the skill separates fields with a middle-dot bullet, which we
        # strip below as trailing non-alphanumeric to keep this source pure ASCII).
        if ($parLine -match 'blocked by\s+(?<b>.+?)(?:\s+shared write|\s+mode\b|$)') {
            $b = (($Matches['b'] -replace '[^0-9A-Za-z,\- ]+$', '').Trim()).TrimEnd('.')
            if ($b -match '^\s*none\s*$' -or $b -eq '') { $blocked = $false; $blockers = "" }
            else { $blocked = $true; $blockers = $b }
        } else {
            # Parallelization line exists but no "blocked by" clause -> be conservative.
            $blocked = $true; $blockers = "(Parallelization line has no 'blocked by' clause)"
        }
    }

    # Tag: PARALLEL if "parallel-safe with" names >=1 session; else SEQUENTIAL (incl. no line).
    $tagType = "SEQUENTIAL"
    if ($parLine -and $parLine -match 'parallel-safe with\s+(?<p>.+?)(?:\s+blocked by|\s+shared write|\s+mode\b|$)') {
        $pf = (($Matches['p'] -replace '[^0-9A-Za-z,\- ]+$', '').Trim()).TrimEnd('.')
        if ($pf -and $pf -notmatch '^\s*none\s*$') { $tagType = "PARALLEL" }
    }

    # Model: from the "**Recommended model:**" line, first Opus/Sonnet/Fable named. Any Opus ->
    # opus (Opus 4.8), any Sonnet -> sonnet (Sonnet 5), any Fable -> fable (Fable 5);
    # missing/other -> opus (default). The runner adds the [1m] suffix to guarantee 1M context.
    $model = "opus"
    $modelLine = ($body | Where-Object { $_ -match '^\s*\*\*Recommended model' } | Select-Object -First 1)
    if ($modelLine -and $modelLine -match '(?i)(opus|sonnet|fable)') {
        if ($Matches[1] -match '(?i)sonnet') { $model = "sonnet" }
        elseif ($Matches[1] -match '(?i)fable') { $model = "fable" }
        else { $model = "opus" }
    }

    # Blocker session ids: tokens from the "blocked by" clause that name a *-session-N id.
    # These drive the self-gating tab runner (-DependsOn) and the manifest's blockedBy[].
    # Extract each id as a SUBSTRING (not an end-anchored whole-token match) so backtick-wrapped
    # ids (`plan-session-2`, the default markdown the skill emits) and trailing-annotated tokens
    # ("plan-session-2 (after merge)") still resolve instead of being silently dropped - which
    # would misclassify a GATED session as AUTO/HELD and lose the validation role.
    $blockerIds = @()
    if ($blockers) {
        $blockerIds = @($blockers -split '\s*,\s*' | ForEach-Object {
            if ($_ -match '([A-Za-z0-9._-]*-session-\d+)') { $Matches[1] }
        } | Where-Object { $_ })
    }

    $script:sessions += [PSCustomObject]@{
        Id = $id; Name = $name; Prompt = $prompt; Blocked = $blocked; Blockers = $blockers
        TagType = $tagType; Model = $model; BlockerIds = $blockerIds
        Worktree = $script:WorktreePath; WtAction = 'Shared'; WtBranch = ''
    }
}

foreach ($ln in $section) {
    if ($ln -match '^###\s+(?:Session\s+)?`?(?<id>[\w.-]+-session-\d+)`?(?:\s+(?<name>.*\S))?\s*$') {
        Add-Session -id $curId -name $curName -body $curBody
        $curId   = $Matches['id']
        $curName = if ($Matches['name']) { ($Matches['name'] -replace '^[\s\p{Pd}]+', '').Trim() } else { "" }
        $curBody = @()
    } elseif ($curId) {
        $curBody += $ln
    }
}
Add-Session -id $curId -name $curName -body $curBody

if ($sessions.Count -eq 0) {
    Write-Host "No sessions with cold-start prompts were parsed from the Session Breakdown." -ForegroundColor Red
    exit 1
}

# ---------------------------------------------------------------------------
# Orchestration state directory (slug-keyed) + stale-state gate (-Reset / -Resume).
# Lives OUTSIDE every repo so nothing is committable and reports survive worktree pruning.
# A stale .done must never silently release gated tabs, so a bare re-run over existing
# state aborts; -Reset archives it (never deletes - reports are history); -Resume validates
# the plan identity and skips sessions already .done.
# ---------------------------------------------------------------------------

$slug = ($sessions[0].Id -replace '-session-\d+$', '')
$stateDir = Join-Path $env:USERPROFILE (".claude\orchestration\{0}" -f $slug)
$manifestPath = Join-Path $stateDir "manifest.json"
$resumeDoneIds = @()

if ($Reset -and $Resume) {
    Write-Host "Pass only one of -Reset / -Resume, not both." -ForegroundColor Red; exit 1
}

$existingManifest = Test-Path -LiteralPath $manifestPath
$existingSentinels = @()
if (Test-Path -LiteralPath $stateDir) {
    $existingSentinels = @(Get-ChildItem -LiteralPath $stateDir -Filter '*.done' -ErrorAction SilentlyContinue) +
                         @(Get-ChildItem -LiteralPath $stateDir -Filter '*.failed' -ErrorAction SilentlyContinue) +
                         @(Get-ChildItem -LiteralPath $stateDir -Filter '*.aborted' -ErrorAction SilentlyContinue)
}
$hasState = $existingManifest -or (@($existingSentinels).Count -gt 0)

if ($hasState -and -not $Reset -and -not $Resume -and -not $DryRun) {
    Write-Host ""
    Write-Host "Orchestration state already exists for slug '$slug':" -ForegroundColor Red
    Write-Host "  $stateDir" -ForegroundColor Red
    if ($existingManifest) { Write-Host "    - manifest.json" -ForegroundColor DarkYellow }
    foreach ($sf in $existingSentinels) { Write-Host "    - $($sf.Name)" -ForegroundColor DarkYellow }
    Write-Host "Re-run with -Reset (archive it and start fresh) or -Resume (skip .done sessions)." -ForegroundColor Yellow
    exit 1
}

if ($Reset -and $hasState -and -not $DryRun) {
    # Milliseconds keep the stamp unique across back-to-back resets; a counter suffix is the
    # belt-and-suspenders fallback so an existing archive dir is never overwritten.
    $stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssfffZ")
    $archiveRoot = Join-Path $stateDir "archive"
    $archiveDir = Join-Path $archiveRoot $stamp
    $n = 2
    while (Test-Path -LiteralPath $archiveDir) { $archiveDir = Join-Path $archiveRoot ("{0}-{1}" -f $stamp, $n); $n++ }
    New-Item -ItemType Directory -Path $archiveDir -Force | Out-Null
    foreach ($item in (Get-ChildItem -LiteralPath $stateDir -Force | Where-Object { $_.Name -ne 'archive' })) {
        Move-Item -LiteralPath $item.FullName -Destination $archiveDir -Force
    }
    Write-Host "[Reset] Archived prior state to $archiveDir" -ForegroundColor Cyan
}

if ($Resume) {
    if (-not $existingManifest) {
        Write-Host "-Resume: no manifest at $manifestPath - nothing to resume." -ForegroundColor Red; exit 1
    }
    $prevManifest = $null
    try { $prevManifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json }
    catch { Write-Host "-Resume: manifest.json is unreadable ($($_.Exception.Message))." -ForegroundColor Red; exit 1 }
    if ($prevManifest.planFile -ne $PlanFile) {
        Write-Host "-Resume: the existing manifest was written for a different plan file:" -ForegroundColor Red
        Write-Host "    manifest: $($prevManifest.planFile)" -ForegroundColor DarkYellow
        Write-Host "    current : $PlanFile" -ForegroundColor DarkYellow
        Write-Host "Same slug, different plan - refusing to resume (state collision)." -ForegroundColor Red
        exit 1
    }
    $curSha = (Get-FileHash -LiteralPath $PlanFile -Algorithm SHA256).Hash
    if ($prevManifest.planFileSha256 -and ($prevManifest.planFileSha256 -ne $curSha)) {
        Write-Host "-Resume: [warn] the plan file has changed since the manifest was written (SHA drift)." -ForegroundColor Yellow
    }
    $resumeDoneIds = @($sessions | Where-Object { Test-Path -LiteralPath (Join-Path $stateDir ("{0}.done" -f $_.Id)) } | ForEach-Object { $_.Id })
}

# ---------------------------------------------------------------------------
# Resolve per-session worktrees (opt-in). Fail-fast: any Error aborts here, before
# any worktree is created or any tab is spawned. Under -Resume, sessions already .done
# are excluded from worktree planning: they get no tab and their (possibly unmerged)
# branch must be left intact - never fed to the fresh-always teardown logic.
# ---------------------------------------------------------------------------

$worktreeSessions = if ($Resume) { @($sessions | Where-Object { $resumeDoneIds -notcontains $_.Id }) } else { $sessions }

$repoInfo = $null
if ($PerSessionWorktrees) {
    $repoInfo = Get-RepoInfo -Path $WorktreePath -BaseRef $BaseRef
    $planErrors = Resolve-SessionWorktreePlan -Sessions $worktreeSessions -RepoInfo $repoInfo
    if (@($planErrors).Count -gt 0) {
        Write-Host ""
        Write-Host "Worktree plan has conflicts - aborting before creating anything:" -ForegroundColor Red
        foreach ($e in $planErrors) { Write-Host "  - $e" -ForegroundColor Red }
        exit 1
    }
}

# ---------------------------------------------------------------------------
# Permission mode (decision 5): ask unless preset via -Permissions. -Yes does NOT
# bypass this question (only the flag does). -DryRun skips it (preview shows both).
#   1 / skip -> --dangerously-skip-permissions (fully unattended)
#   2 / auto -> --permission-mode auto (shift+tab "auto mode": edits auto-accepted,
#               other actions still prompt and surface as input-needed toasts)
# ---------------------------------------------------------------------------

$permMode = $Permissions
$permAsk = $false
if (-not $permMode) {
    if ($DryRun) {
        $permAsk = $true
    } else {
        Write-Host ""
        Write-Host "Spawn tabs with which permission mode?" -ForegroundColor Cyan
        Write-Host "  [1] --dangerously-skip-permissions  (fully unattended)" -ForegroundColor DarkGray
        Write-Host "  [2] auto mode (--permission-mode auto: edits auto-accepted, other actions prompt)" -ForegroundColor DarkGray
        $ans = Read-Host "Send 1 or 2 [1]"
        if ($ans -match '^\s*2\s*$') { $permMode = 'auto' } else { $permMode = 'skip' }
    }
}
if ($permMode -eq 'auto') {
    Write-Host ""
    Write-Host "  Permission mode: auto - tabs launch with --permission-mode auto (not skip-permissions);" -ForegroundColor Yellow
    Write-Host "  file edits auto-accept, other actions prompt and surface as input-needed toasts." -ForegroundColor DarkYellow
}

# ---------------------------------------------------------------------------
# Show the plan (who auto-submits vs. who is held; per-session worktree)
# ---------------------------------------------------------------------------

# AUTO  = unblocked, auto-submits on boot.
# GATED = has parseable prerequisite session ids -> its tab waits (lazy boot) and self-submits.
# HELD  = blocked but no parseable prerequisite id -> legacy manual Enter.
function Get-SessionLabel {
    param($Session)
    if (@($Session.BlockerIds).Count -gt 0) { return 'GATED' }
    elseif (-not $Session.Blocked) { return 'AUTO' }
    else { return 'HELD' }
}

$branch = (git -C $WorktreePath rev-parse --abbrev-ref HEAD 2>$null)
if (-not $branch) { $branch = "(not a git worktree)" }
$autoCount  = @($sessions | Where-Object { (Get-SessionLabel $_) -eq 'AUTO' }).Count
$gatedCount = @($sessions | Where-Object { (Get-SessionLabel $_) -eq 'GATED' }).Count
$heldCount  = @($sessions | Where-Object { (Get-SessionLabel $_) -eq 'HELD' }).Count
$wtCount = @($sessions | Where-Object { $_.WtAction -ne 'Shared' }).Count
$permDisplay = if ($permAsk) { "(asked at spawn: 1=skip | 2=auto)" } else { $permMode }

Write-Host ""
Write-Host "=== Spawn Plan Sessions ===" -ForegroundColor Cyan
Write-Host "  Plan     : $PlanFile" -ForegroundColor DarkGray
Write-Host "  Worktree : $WorktreePath" -ForegroundColor DarkGray
Write-Host "  Branch   : $branch" -ForegroundColor DarkGray
Write-Host "  State    : $stateDir" -ForegroundColor DarkGray
Write-Host "  Perms    : $permDisplay" -ForegroundColor DarkGray
if ($PerSessionWorktrees) {
    Write-Host "  Isolated : $wtCount PARALLEL session(s) get own worktree under $($repoInfo.Container)" -ForegroundColor DarkGray
    Write-Host "  Base ref : $($repoInfo.BaseRef) ($($repoInfo.BaseSha.Substring(0, [Math]::Min(12, $repoInfo.BaseSha.Length))))" -ForegroundColor DarkGray
}
Write-Host "  Sessions : $($sessions.Count)  ($autoCount auto, $gatedCount gated, $heldCount held)  |  effort=$Effort" -ForegroundColor DarkGray
Write-Host ""
foreach ($s in $sessions) {
    $label = Get-SessionLabel $s
    $meta = "[{0} SESSION]  {1}[1m]" -f $s.TagType, $s.Model
    switch ($label) {
        'GATED' {
            Write-Host ("  GATED {0}  {1}" -f $s.Id, $meta) -ForegroundColor Cyan
            Write-Host ("        self-submits when done: {0}" -f (@($s.BlockerIds) -join ', ')) -ForegroundColor DarkCyan
        }
        'HELD' {
            Write-Host ("  HELD  {0}  {1}" -f $s.Id, $meta) -ForegroundColor Yellow
            Write-Host ("        press Enter yourself after: {0}" -f $s.Blockers) -ForegroundColor DarkYellow
        }
        default {
            Write-Host ("  AUTO  {0}  {1}" -f $s.Id, $meta) -ForegroundColor Green
        }
    }
    if ($s.WtAction -eq 'Shared') {
        Write-Host ("        worktree: shared -> {0}" -f $s.Worktree) -ForegroundColor DarkGray
    } else {
        Write-Host ("        worktree: {0} -> {1} [{2}]" -f $s.WtBranch, $s.Worktree, $s.WtAction.ToLower()) -ForegroundColor DarkCyan
    }
}
Write-Host ""

# Assemble the full multi-line message per session and persist it under the orchestration
# state dir (<stateDir>\prompts\<id>.txt - the tab runner bracketed-paste-injects it).
# Line 1 = the [PARALLEL/SEQUENTIAL] tag; then, for an isolated-worktree session, a worktree
# directive, a fragment-log directive (write your Implementation Log entry to a sibling
# <session-id>.implog.md instead of the plan file, so concurrent parallel sessions can never
# conflict on the shared plan file), and, if it is also blocked, a merge-prerequisites
# directive; then, for a session with real prerequisite sessions, a launcher-gated directive
# (plus a fold-in-fragments directive if any blocker wrote one); then the SESSION WRAP-UP and
# ORACLE directives; then the cold-start prompt. Baking the wrap-up/oracle here guarantees the
# completion protocol even for plans carved by an older skill version. Prompt files are only
# written on a real run (never under -DryRun).
$spawnDir = Join-Path $stateDir "prompts"
if (-not $DryRun -and -not (Test-Path -LiteralPath $spawnDir)) { New-Item -ItemType Directory -Path $spawnDir -Force | Out-Null }
$planDir = Split-Path -Parent $PlanFile
$completeScriptPath = Join-Path $PSScriptRoot "complete-session.ps1"
foreach ($s in $sessions) {
    $pf = Join-Path $spawnDir ("{0}.txt" -f $s.Id)
    $msgLines = @("[$($s.TagType) SESSION]")
    if ($s.WtAction -ne 'Shared') {
        $baseShort = if ($repoInfo) { $repoInfo.BaseSha.Substring(0, [Math]::Min(12, $repoInfo.BaseSha.Length)) } else { "" }
        $msgLines += ("You are working in an isolated git worktree at $($s.Worktree) on branch $($s.WtBranch), created from $baseShort. Commit on this branch only - do not touch the main worktree.")
        $fragSelf = Join-Path $planDir ("{0}.implog.md" -f $s.Id)
        $msgLines += ("To avoid a merge conflict with sibling parallel sessions on the shared plan file, do NOT append your Implementation Log entry directly into the plan file. Instead write it (the same heading and content you would otherwise append) to $fragSelf and commit that file on this branch. Whoever merges this branch is responsible for folding it into the plan file afterward.")
        if ($s.Blocked -and $s.Blockers -match '-session-\d') {
            $msgLines += ("Before starting, merge or rebase the prerequisite session branches (or main once they have merged) into this branch so their commits are visible here.")
        }
    }
    if (@($s.BlockerIds).Count -gt 0) {
        $msgLines += ("This tab was gated by the launcher until its prerequisites signalled done, so by the time you read this they are satisfied: {0}. On starting, quickly confirm their .done sentinels / Implementation Log entries, then proceed - do NOT wait or poll (all gating is done by infrastructure, never by you)." -f (@($s.BlockerIds) -join ', '))
        $fragBlockers = @($sessions | Where-Object { $s.BlockerIds -contains $_.Id -and $_.WtAction -ne 'Shared' })
        if ($fragBlockers.Count -gt 0) {
            $fragList = ($fragBlockers | ForEach-Object { Join-Path $planDir ("{0}.implog.md" -f $_.Id) }) -join ', '
            $msgLines += ("After merging their branch(es), check for sibling Implementation Log fragment file(s) ($fragList) - if present, fold each one's content into the plan file's Implementation Log section (in session-number order), delete the fragment file(s), then commit the consolidation.")
        }
    }

    # SESSION WRAP-UP (mandatory, in order) - baked so every session runs the completion protocol.
    $reportPath = Join-Path (Join-Path $stateDir "reports") ("{0}-report.md" -f $s.Id)
    $completeCmd = 'powershell -NoProfile -ExecutionPolicy Bypass -File "' + $completeScriptPath + '" -SessionId ' + $s.Id + ' -Status done -CommitSha <sha> -Summary "<one line, no secrets>"'
    $exportHint = '/export session-logs/logs/' + $s.Id + '-final.txt'
    $msgLines += ("SESSION WRAP-UP (mandatory, in order): (1) DoD green - positive AND negative tests. (2) Run /code-review on your session diff; fix CONFIRMED findings and flag any SOLID violations in your new code; re-test. (3) Auto-commit per commit-policy (no AI trailers); record the commit SHA in your Implementation Log entry/fragment. (4) Write a report to " + $reportPath + " with sections: Status, Commit, Tests run + results, Review outcome (incl. SOLID flags), Issues encountered, Consultations, Deferred; add a one-line issues note to the Implementation Log. (5) Signal completion: " + $completeCmd + " (use -Status failed instead if the work is unrecoverable). (6) As your very last message, print this exact line for the human to run - you CANNOT invoke slash built-ins yourself: USER ACTION - type  " + $exportHint + "  in this tab to save the human-readable transcript snapshot to session-logs (use -v2, -v3... for earlier interim snapshots). Never put secrets in reports, summaries, or the manifest.")
    $msgLines += ("ORACLE CONSULT: if you are stuck after 2 failed attempts at the same problem, hit an architecture-risk fork, or are about to abandon a DoD item, consult the 'oracle' agent (read-only) before proceeding and record the consultation in your report.")

    $msgLines += $s.Prompt
    if (-not $DryRun) {
        Set-Content -LiteralPath $pf -Value ($msgLines -join "`n") -Encoding UTF8 -NoNewline
    }
    $s | Add-Member -NotePropertyName PromptFile -NotePropertyValue $pf -Force
}

# ---------------------------------------------------------------------------
# Manifest: the static DAG, written once (skipped under -DryRun). role = "validation"
# iff blockedBy equals every OTHER session id (computed, never parsed from prose).
# ---------------------------------------------------------------------------

$allIds = @($sessions | ForEach-Object { $_.Id })
function Test-IsValidation {
    param($Session, $AllIds)
    $others = @($AllIds | Where-Object { $_ -ne $Session.Id })
    $bb = @($Session.BlockerIds)
    if ($others.Count -eq 0) { return $false }
    if ($bb.Count -ne $others.Count) { return $false }
    return (@($others | Where-Object { $bb -notcontains $_ }).Count -eq 0)
}

if (-not $DryRun) {
    $manifestSessions = @()
    foreach ($s in $sessions) {
        $manifestSessions += [PSCustomObject]@{
            id         = $s.Id
            name       = $s.Name
            model      = $s.Model
            tagType    = $s.TagType
            blockedBy  = @($s.BlockerIds)
            autoSubmit = (-not $s.Blocked)
            role       = if (Test-IsValidation -Session $s -AllIds $allIds) { 'validation' } else { 'implementation' }
            worktree   = $s.Worktree
            branch     = $s.WtBranch
            promptFile = $s.PromptFile
        }
    }
    $manifest = [PSCustomObject]@{
        schemaVersion       = 1
        planSlug            = $slug
        planFile            = $PlanFile
        planFileSha256      = (Get-FileHash -LiteralPath $PlanFile -Algorithm SHA256).Hash
        generatedUtc        = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
        effort              = $Effort
        permissions         = $permMode
        perSessionWorktrees = [bool]$PerSessionWorktrees
        stateDir            = $stateDir
        sessions            = $manifestSessions
    }
    if (-not (Test-Path -LiteralPath $stateDir)) { New-Item -ItemType Directory -Path $stateDir -Force | Out-Null }
    ($manifest | ConvertTo-Json -Depth 5) | Set-Content -LiteralPath $manifestPath -Encoding Ascii
}

if ($DryRun) {
    Write-Host "[DryRun] Would open $($sessions.Count) tab(s); auto-submit AUTO, self-gate GATED, hold HELD." -ForegroundColor Yellow
    if ($permAsk) {
        Write-Host "[DryRun] Permission question skipped; a real run asks [1] skip (default) or [2] auto." -ForegroundColor Yellow
    }
    Write-Host "[DryRun] Would-be manifest ($manifestPath):" -ForegroundColor Yellow
    foreach ($s in $sessions) {
        $role = if (Test-IsValidation -Session $s -AllIds $allIds) { 'validation' } else { 'implementation' }
        $bb = if (@($s.BlockerIds).Count -gt 0) { (@($s.BlockerIds) -join ',') } else { 'none' }
        Write-Host ("[DryRun]   {0}  model={1}  role={2}  autoSubmit={3}  blockedBy={4}" -f $s.Id, $s.Model, $role, (-not $s.Blocked), $bb) -ForegroundColor DarkYellow
    }
    if ($PerSessionWorktrees) {
        $createN   = @($sessions | Where-Object { $_.WtAction -eq 'Create' }).Count
        $recreateN = @($sessions | Where-Object { $_.WtAction -eq 'Recreate' }).Count
        $sharedN   = @($sessions | Where-Object { $_.WtAction -eq 'Shared' }).Count
        Write-Host "[DryRun] Worktree plan: $createN fresh, $recreateN recreate (discard stale), $sharedN shared." -ForegroundColor Yellow
        foreach ($s in $sessions | Where-Object { $_.WtAction -ne 'Shared' }) {
            Write-Host ("[DryRun]   {0}: {1} {2} -> {3}" -f $s.WtAction, $s.Id, $s.WtBranch, $s.Worktree) -ForegroundColor DarkYellow
        }
        # Mirror the real run: it registers $worktreeSessions (so -Resume-done sessions are excluded)
        # and skips any path already trusted - hence "unless already trusted", not an unconditional write.
        foreach ($s in $worktreeSessions | Where-Object { $_.WtAction -ne 'Shared' }) {
            Write-Host ("[DryRun]   trust: would register {0} in ~/.claude.json (unless already trusted)" -f ($s.Worktree -replace '\\', '/')) -ForegroundColor DarkYellow
        }
    }
    Write-Host "[DryRun] No state written; no worktrees created; no tabs spawned." -ForegroundColor Yellow
    exit 0
}

# ---------------------------------------------------------------------------
# Confirm
# ---------------------------------------------------------------------------

if (-not $Yes) {
    if ($PerSessionWorktrees -and $wtCount -gt 0) {
        $sharedN = $sessions.Count - $wtCount
        $recreateN = @($sessions | Where-Object { $_.WtAction -eq 'Recreate' }).Count
        $wtMsg = "About to create $wtCount fresh isolated worktree(s)"
        if ($recreateN -gt 0) { $wtMsg += " (discarding $recreateN stale one(s))" }
        $wtMsg += " under $($repoInfo.Container); $sharedN session(s) share $WorktreePath on branch '$branch'."
        Write-Host $wtMsg -ForegroundColor Yellow
    } else {
        Write-Host "About to open $($sessions.Count) tab(s) in the SAME worktree ($WorktreePath) on branch '$branch'." -ForegroundColor Yellow
        if ($autoCount -gt 1) {
            Write-Host "$autoCount sessions will auto-submit and run CONCURRENTLY in that one worktree - shared-file edits may collide." -ForegroundColor Yellow
        }
    }
    $answer = Read-Host "Continue? [y/N]"
    if ($answer -notmatch '^(y|yes)$') { Write-Host "Cancelled." -ForegroundColor DarkGray; exit 0 }
}

# ---------------------------------------------------------------------------
# Create the per-session worktrees (before spawning any tab). Runs even under -NoTabs.
# ---------------------------------------------------------------------------

if ($PerSessionWorktrees) {
    foreach ($s in $sessions | Where-Object { $_.WtAction -eq 'Create' -or $_.WtAction -eq 'Recreate' }) {
        $ok = New-SessionWorktree -Session $s -RepoInfo $repoInfo -PlanFile $PlanFile
        if (-not $ok) {
            Write-Host "Aborting: worktree creation failed for $($s.Id)." -ForegroundColor Red
            exit 1
        }
    }
    # Pre-register folder trust for the fresh worktrees so claude's first-run trust dialog
    # cannot swallow the injected prompts. Runs once, after worktrees exist and immediately
    # before any tab boots; also covers -NoTabs (the printed manual invocations boot claude in
    # these same folders). Never fatal - a failure just risks the pre-fix dialog behavior.
    Register-SpawnWorktreeTrust -Sessions $worktreeSessions -RepoInfo $repoInfo | Out-Null
}

# ---------------------------------------------------------------------------
# Tab runner + per-session wt.exe argument builder (shared by -NoTabs and the spawn loop).
# AUTO  -> -AutoEnter (submit on boot). GATED -> -DependsOn (lazy-boot self-gating tab that
# submits itself once its deps signal .done). HELD -> neither (legacy manual Enter).
# ---------------------------------------------------------------------------

$tabRunner = Join-Path $PSScriptRoot "spawn-session-tab.ps1"
if (-not (Test-Path -LiteralPath $tabRunner)) {
    Write-Host "Tab runner not found next to this script: $tabRunner" -ForegroundColor Red
    exit 1
}
$delayMs = [Math]::Max(1000, $BootDelaySeconds * 1000)

function Get-SessionTabArgs {
    param($Session)
    # Front-load the tab title with the session number + P/S so it survives WT's
    # right-truncation (the shared slug prefix would otherwise make every tab identical).
    $num = if ($Session.Id -match 'session-(\d+)') { $Matches[1] } else { '?' }
    $ps  = if ($Session.TagType -eq 'PARALLEL') { 'P' } else { 'S' }
    $title = "[$num$ps] $($Session.Id)"
    $a = @(
        '-w', '0', 'new-tab', '--title', $title, '--suppressApplicationTitle',
        'powershell', '-NoExit', '-ExecutionPolicy', 'Bypass', '-File', $tabRunner,
        '-Id', $Session.Id, '-Worktree', $Session.Worktree, '-PromptFile', $Session.PromptFile, '-DelayMs', $delayMs,
        '-Model', $Session.Model, '-Effort', $Effort,
        '-StateDir', $stateDir, '-PlanSlug', $slug, '-PermissionMode', $permMode
    )
    $label = Get-SessionLabel $Session
    if ($label -eq 'GATED') { $a += @('-DependsOn', (@($Session.BlockerIds) -join ',')) }
    elseif ($label -eq 'AUTO') { $a += '-AutoEnter' }
    return $a
}

if ($NoTabs) {
    Write-Host ""
    Write-Host "[NoTabs] Prepared $($sessions.Count) session(s); no wt.exe tabs opened." -ForegroundColor Cyan
    Write-Host "  State dir   : $stateDir" -ForegroundColor DarkGray
    Write-Host "  Manifest    : $manifestPath" -ForegroundColor DarkGray
    Write-Host "  Prompt files: $spawnDir\<session-id>.txt" -ForegroundColor DarkGray
    Write-Host "  Manual tab invocations (run each in its own Windows Terminal tab):" -ForegroundColor DarkGray
    foreach ($s in $sessions) {
        if ($Resume -and ($resumeDoneIds -contains $s.Id)) {
            Write-Host ("    SKIP (done)  {0}" -f $s.Id) -ForegroundColor DarkGray
            continue
        }
        $a = Get-SessionTabArgs -Session $s
        Write-Host ("    [{0}] wt.exe {1}" -f (Get-SessionLabel $s), ($a -join ' ')) -ForegroundColor DarkGray
    }
    if ($PerSessionWorktrees) {
        Write-Host "  Merge session branches back manually; clean up with cleanup-plan-worktrees.ps1." -ForegroundColor DarkGray
    }
    exit 0
}

# ---------------------------------------------------------------------------
# Spawn each tab. Each tab runs spawn-session-tab.ps1, which launches interactive
# Claude and injects the prompt into its OWN console (WriteConsoleInput) after a
# boot delay - foreground-independent, so tabs don't fight over focus and can all
# open at once. AUTO sessions inject prompt + Enter; GATED tabs wait (lazy boot) and
# self-submit once their deps signal .done; HELD tabs wait for a manual Enter.
# Under -Resume a session already marked .done is skipped (no tab).
# ---------------------------------------------------------------------------

foreach ($s in $sessions) {
    if ($Resume -and ($resumeDoneIds -contains $s.Id)) {
        Write-Host ("  SKIP (done)  {0}  (already .done - no tab)" -f $s.Id) -ForegroundColor DarkGray
        continue
    }
    $wtArgs = Get-SessionTabArgs -Session $s
    & wt.exe @wtArgs
    Start-Sleep -Milliseconds 1500   # wider stagger so each Claude boots with less contention
}

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

$autoList  = @($sessions | Where-Object { (Get-SessionLabel $_) -eq 'AUTO' })
$gatedList = @($sessions | Where-Object { (Get-SessionLabel $_) -eq 'GATED' })
$heldList  = @($sessions | Where-Object { (Get-SessionLabel $_) -eq 'HELD' })
$statusScript = Join-Path $PSScriptRoot "orchestration-status.ps1"

Write-Host ""
Write-Host "[OK] Spawned tab(s)." -ForegroundColor Green
if ($autoList.Count -gt 0) {
    Write-Host "  Auto-submitted ($($autoList.Count)):" -ForegroundColor Green
    $autoList | ForEach-Object { Write-Host "    $($_.Id)" -ForegroundColor DarkGray }
}
if ($gatedList.Count -gt 0) {
    Write-Host "  Gated - self-submit when their deps signal done, no manual Enter ($($gatedList.Count)):" -ForegroundColor Cyan
    $gatedList | ForEach-Object { Write-Host ("    {0}  <- deps: {1}" -f $_.Id, (@($_.BlockerIds) -join ', ')) -ForegroundColor DarkGray }
}
if ($heldList.Count -gt 0) {
    Write-Host "  Held - prompt is pasted in the box, press Enter yourself once the blocker ships ($($heldList.Count)):" -ForegroundColor Yellow
    $heldList | ForEach-Object { Write-Host "    $($_.Id)  <- after: $($_.Blockers)" -ForegroundColor DarkYellow }
}
if ($PerSessionWorktrees -and $wtCount -gt 0) {
    Write-Host "  Isolated worktrees ($wtCount):" -ForegroundColor Cyan
    $sessions | Where-Object { $_.WtAction -ne 'Shared' } | ForEach-Object {
        Write-Host ("    $($_.Id)  $($_.WtBranch) -> $($_.Worktree) [$($_.WtAction.ToLower())]") -ForegroundColor DarkGray
    }
    Write-Host "  Merge session branches back manually; clean up with cleanup-plan-worktrees.ps1." -ForegroundColor DarkGray
}
Write-Host ""
Write-Host "  State dir : $stateDir" -ForegroundColor DarkGray
Write-Host "  Perms     : $permMode" -ForegroundColor DarkGray
Write-Host ("  Status    : powershell -NoProfile -ExecutionPolicy Bypass -File `"{0}`" -PlanSlug {1}" -f $statusScript, $slug) -ForegroundColor DarkGray
Write-Host "  Re-run    : -Reset archives this state and starts fresh; -Resume skips .done sessions." -ForegroundColor DarkGray
