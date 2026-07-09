#requires -Version 5.1
# Self-tests for resolve-export-name.ps1. No external deps; uses a temp orchestration root + project.
# Run: powershell -NoProfile -ExecutionPolicy Bypass -File .\test-resolve-export-name.ps1
# Exit 0 = all pass, 1 = at least one failure.

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$script = Join-Path $here 'resolve-export-name.ps1'

$fails = 0
function Check($label, $expected, $actual) {
    if ($expected -eq $actual) {
        Write-Host ("  PASS  {0}" -f $label) -ForegroundColor Green
    }
    else {
        Write-Host ("  FAIL  {0}`n        expected: {1}`n        actual:   {2}" -f $label, $expected, $actual) -ForegroundColor Red
        $script:fails++
    }
}
function CheckThrows($label, [scriptblock]$block) {
    try { & $block; Write-Host ("  FAIL  {0} (expected an error, got none)" -f $label) -ForegroundColor Red; $script:fails++ }
    catch { Write-Host ("  PASS  {0} (threw: {1})" -f $label, $_.Exception.Message.Split("`n")[0]) -ForegroundColor Green }
}

# --- Fixtures ---------------------------------------------------------------------------------------
$tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("export-name-test-" + [System.Guid]::NewGuid().ToString('N').Substring(0, 8))
$orchRoot = Join-Path $tmp 'orchestration'
$slugDir = Join-Path $orchRoot 'logwarden'
$proj = Join-Path $tmp 'project'
$logs = Join-Path $proj 'session-logs'
New-Item -ItemType Directory -Path $slugDir, $logs -Force | Out-Null

$manifest = [pscustomobject]@{
    planSlug = 'logwarden'
    sessions = @(
        [pscustomobject]@{ id = 'logwarden-session-1'; tagType = 'SEQUENTIAL' },
        [pscustomobject]@{ id = 'logwarden-session-2'; tagType = 'SEQUENTIAL' },
        [pscustomobject]@{ id = 'logwarden-session-3'; tagType = 'PARALLEL' }
    )
}
($manifest | ConvertTo-Json -Depth 5) | Set-Content -LiteralPath (Join-Path $slugDir 'manifest.json') -Encoding Ascii

function Run {
    param([hashtable]$Params)
    $Params['ProjectPath'] = $proj
    $Params['OrchestrationRoot'] = $orchRoot
    $Params['Raw'] = $true
    (& $script @Params) | Select-Object -Last 1
}

Write-Host "resolve-export-name.ps1 tests" -ForegroundColor Cyan

# --- Positive: manifest-driven s/p tag --------------------------------------------------------------
Check 'session-1 -> 1s (SEQUENTIAL)'  '1s-logwarden-session-1' (Run @{ SessionId = 'logwarden-session-1' })
Check 'session-2 -> 2s (SEQUENTIAL)'  '2s-logwarden-session-2' (Run @{ SessionId = 'logwarden-session-2' })
Check 'session-3 -> 3p (PARALLEL)'    '3p-logwarden-session-3' (Run @{ SessionId = 'logwarden-session-3' })

# --- Positive: master plan --------------------------------------------------------------------------
Check 'master plan'                   'logwarden-master-plan'  (Run @{ MasterPlan = $true; Slug = 'logwarden' })

# --- Positive: interim / final suffixes -------------------------------------------------------------
Check 'final suffix'                  '3p-logwarden-session-3-final' (Run @{ SessionId = 'logwarden-session-3'; Final = $true })
Check 'interim v2 suffix'             '2s-logwarden-session-2-v2'    (Run @{ SessionId = 'logwarden-session-2'; Interim = 2 })

# --- Positive: -Type override when no manifest entry ------------------------------------------------
Check 'unknown id + -Type p'          '4p-logwarden-session-4' (Run @{ SessionId = 'logwarden-session-4'; Type = 'p' })

# --- Positive: no-overwrite auto-suffix -------------------------------------------------------------
Set-Content -LiteralPath (Join-Path $logs '1s-logwarden-session-1.txt') -Value 'x' -Encoding Ascii
Check 'no-overwrite -> -2'            '1s-logwarden-session-1-2' (Run @{ SessionId = 'logwarden-session-1' })
Set-Content -LiteralPath (Join-Path $logs '1s-logwarden-session-1-2.txt') -Value 'x' -Encoding Ascii
Check 'no-overwrite -> -3'            '1s-logwarden-session-1-3' (Run @{ SessionId = 'logwarden-session-1' })

# --- Positive: auto-detect via worktree marker ------------------------------------------------------
$markerProj = Join-Path $tmp 'markerproj'
New-Item -ItemType Directory -Path (Join-Path $markerProj 'session-logs') -Force | Out-Null
([pscustomobject]@{ sessionId = 'logwarden-session-3' } | ConvertTo-Json) |
    Set-Content -LiteralPath (Join-Path $markerProj '.claude-spawn-worktree.json') -Encoding Ascii
$got = (& $script -ProjectPath $markerProj -OrchestrationRoot $orchRoot -Raw) | Select-Object -Last 1
Check 'auto-detect from marker'       '3p-logwarden-session-3' $got

# --- Positive: default (non-Raw) prints the /export line --------------------------------------------
$line = (& $script -SessionId 'logwarden-session-3' -ProjectPath $proj -OrchestrationRoot $orchRoot) | Select-Object -First 1
Check 'non-Raw emits /export line'    '/export session-logs/3p-logwarden-session-3.txt' $line

# --- Negative: malformed id -------------------------------------------------------------------------
CheckThrows 'malformed session id' { & $script -SessionId 'not-a-session' -ProjectPath $proj -OrchestrationRoot $orchRoot -Raw }

# --- Negative: master plan without slug -------------------------------------------------------------
CheckThrows 'master plan w/o slug'   { & $script -MasterPlan -ProjectPath $proj -OrchestrationRoot $orchRoot -Raw }

# --- Negative: no id and nothing to detect ----------------------------------------------------------
$emptyProj = Join-Path $tmp 'empty'
New-Item -ItemType Directory -Path $emptyProj -Force | Out-Null
CheckThrows 'no id, no detection'    { & $script -ProjectPath $emptyProj -OrchestrationRoot $orchRoot -Raw }

# --- Negative: -Final and -Interim together ---------------------------------------------------------
CheckThrows 'final + interim clash'  { & $script -SessionId 'logwarden-session-1' -Final -Interim 2 -ProjectPath $proj -OrchestrationRoot $orchRoot -Raw }

# --- Cleanup ----------------------------------------------------------------------------------------
Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue

Write-Host ""
if ($fails -eq 0) { Write-Host "ALL TESTS PASSED" -ForegroundColor Green; exit 0 }
else { Write-Host ("{0} TEST(S) FAILED" -f $fails) -ForegroundColor Red; exit 1 }
