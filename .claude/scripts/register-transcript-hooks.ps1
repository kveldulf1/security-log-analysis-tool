# register-transcript-hooks.ps1 - Register the transcript-guard hooks in a project's settings.json.
#
# Adds hooks.SessionStart -> capture-session-start.ps1 and hooks.Stop -> check-transcript-stop.ps1
# to <ProjectPath>\.claude\settings.json WITHOUT disturbing anything already there. Used to retrofit
# projects that were seeded before the guard existed (a fresh seed ships the template settings.json
# directly). Idempotent: re-running when both hooks are present writes nothing.
#
# Safety: backs up to settings.json.transcript-hooks.bak, re-parses the serialized result and
# asserts every original top-level key survived and both hook commands are present, and aborts
# WITHOUT writing on any doubt. -DryRun reports the intended change and writes nothing.

param(
    [Parameter(Mandatory = $true)] [string]$ProjectPath,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'

$HOOK_DEFS = @(
    @{ Event = 'SessionStart'; Script = 'capture-session-start.ps1' },
    @{ Event = 'Stop';         Script = 'check-transcript-stop.ps1' }
)

function New-HookEntry {
    param([string]$ScriptName)
    return [pscustomobject]@{
        hooks = @(
            [pscustomobject]@{
                type    = 'command'
                command = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File .claude/scripts/$ScriptName"
                timeout = 10
            }
        )
    }
}

function Set-Prop {
    param($Obj, [string]$Name, $Value)
    if ($Obj.PSObject.Properties[$Name]) { $Obj.PSObject.Properties[$Name].Value = $Value }
    else { $Obj | Add-Member -NotePropertyName $Name -NotePropertyValue $Value }
}

function Test-EventHasScript {
    param($Cfg, [string]$Event, [string]$ScriptName)
    if (-not $Cfg.PSObject.Properties['hooks']) { return $false }
    if (-not $Cfg.hooks.PSObject.Properties[$Event]) { return $false }
    foreach ($grp in @($Cfg.hooks.$Event)) {
        if ($grp -and $grp.PSObject.Properties['hooks']) {
            foreach ($h in @($grp.hooks)) {
                if ($h.command -and ($h.command -match [regex]::Escape($ScriptName))) { return $true }
            }
        }
    }
    return $false
}

function Write-Utf8NoBom {
    param([string]$Path, [string]$Text)
    $enc = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Text, $enc)
}

$claudeDir = Join-Path $ProjectPath '.claude'
$settingsPath = Join-Path $claudeDir 'settings.json'

# --- Absent: write a fresh settings.json with just the two hooks. -------------------------------
if (-not (Test-Path -LiteralPath $settingsPath)) {
    $fresh = [pscustomobject]@{
        hooks = [pscustomobject]@{
            SessionStart = @( (New-HookEntry 'capture-session-start.ps1') )
            Stop         = @( (New-HookEntry 'check-transcript-stop.ps1') )
        }
    }
    $json = $fresh | ConvertTo-Json -Depth 12
    if ($DryRun) { Write-Host "[dry-run] would create $settingsPath with SessionStart+Stop hooks"; exit 0 }
    if (-not (Test-Path -LiteralPath $claudeDir)) { New-Item -ItemType Directory -Path $claudeDir -Force | Out-Null }
    Write-Utf8NoBom $settingsPath $json
    Write-Host "[ok] created $settingsPath with transcript-guard hooks" -ForegroundColor Green
    exit 0
}

# --- Present: merge non-destructively. ----------------------------------------------------------
$raw = Get-Content -LiteralPath $settingsPath -Raw
try { $cfg = $raw | ConvertFrom-Json } catch { Write-Error "settings.json is not valid JSON: $($_.Exception.Message)"; exit 1 }
$originalKeys = @($cfg.PSObject.Properties.Name)

$changed = $false
foreach ($def in $HOOK_DEFS) {
    if (Test-EventHasScript $cfg $def.Event $def.Script) { continue }
    if (-not $cfg.PSObject.Properties['hooks']) { Set-Prop $cfg 'hooks' ([pscustomobject]@{}) }
    $existing = @()
    if ($cfg.hooks.PSObject.Properties[$def.Event]) { $existing = @($cfg.hooks.$($def.Event)) }
    $merged = @($existing) + @( (New-HookEntry $def.Script) )
    Set-Prop $cfg.hooks $def.Event $merged
    $changed = $true
}

if (-not $changed) { Write-Host "[ok] transcript-guard hooks already registered in $settingsPath (no change)" -ForegroundColor DarkGray; exit 0 }

$json = $cfg | ConvertTo-Json -Depth 12

# Validate before swapping anything in.
$reparsed = $null
try { $reparsed = $json | ConvertFrom-Json } catch { Write-Error "internal: merged JSON did not re-parse; aborting without write."; exit 1 }
foreach ($k in $originalKeys) {
    if (-not $reparsed.PSObject.Properties[$k]) { Write-Error "internal: original key '$k' lost during merge; aborting without write."; exit 1 }
}
if (($json -notmatch 'capture-session-start\.ps1') -or ($json -notmatch 'check-transcript-stop\.ps1')) {
    Write-Error "internal: merged JSON missing a hook command; aborting without write."; exit 1
}

if ($DryRun) {
    Write-Host "[dry-run] would merge transcript-guard hooks into $settingsPath (original keys preserved: $($originalKeys -join ', '))"
    exit 0
}

$backup = $settingsPath + '.transcript-hooks.bak'
Copy-Item -LiteralPath $settingsPath -Destination $backup -Force
Write-Utf8NoBom $settingsPath $json
Write-Host "[ok] merged transcript-guard hooks into $settingsPath (backup: $backup)" -ForegroundColor Green
exit 0
