# spawn-session-tab.ps1 - Per-tab runner for spawn-plan-sessions.ps1
#
# Runs inside ONE Windows Terminal tab. Launches an interactive Claude session in the
# given worktree - named (--name), on the recommended 1M-context model (--model) at the
# chosen effort (--effort) - then delivers the pre-assembled message (tag line +
# optional blocking directive + cold-start prompt) by injecting it into this tab's OWN
# console input buffer as a BRACKETED PASTE (WriteConsoleInput) from a background thread
# once Claude's TUI is up. Bracketed paste preserves the newlines (multi-line message,
# each part on its own line) and does NOT submit; a separate Enter submits afterwards.
# Foreground-independent: no window focus, clipboard, or SendKeys, so many tabs can
# spawn without interfering.
#   -AutoEnter present -> submit the first turn (~1.2 s after the paste).
#   -AutoEnter absent  -> leave it in the box; you press Enter yourself (HELD session).
#
# LAZY-BOOT SELF-GATING (-DependsOn + -StateDir): a gated session does NOT launch claude up
# front. Instead this tab waits in plain PowerShell (a few MB, zero tokens, no claude process)
# polling the orchestration state dir every 5 s. When every dependency has a .done sentinel it
# RELEASES: boots claude and self-submits (no human Enter). A dependency that goes .failed /
# .aborted prints a warning and keeps waiting (a later re-signalled .done auto-recovers). Pressing
# any key during the wait is a FORCE-LAUNCH override: claude boots and the prompt is pasted but NOT
# submitted (you took control). Every transition is logged to <StateDir>\gate\<id>.gate.log.
#
# On any claude exit (/exit, Ctrl+C, crash) the tab writes an .aborted sentinel via
# complete-session.ps1 (-SkipIfFinished, so a real .done/.failed is never overwritten) so
# dependents don't hang on a session that vanished. A hard tab-kill leaves no sentinel -> the DAG
# fails safe (dependents stay gated).
#
# Not meant to be run directly - spawn-plan-sessions.ps1 invokes it per session.

param(
    [Parameter(Mandatory = $true)] [string]$Id,
    [Parameter(Mandatory = $true)] [string]$Worktree,
    [Parameter(Mandatory = $true)] [string]$PromptFile,
    [switch]$AutoEnter,
    [int]$DelayMs = 15000,
    [string]$Model = "",
    [string]$Effort = "",
    [string]$StateDir = "",
    [string]$DependsOn = "",
    [string]$PlanSlug = "",
    [ValidateSet('skip', 'auto')] [string]$PermissionMode = 'skip'
)

Add-Type @"
using System;
using System.Runtime.InteropServices;
using System.Threading;
public static class ConInject {
  [StructLayout(LayoutKind.Explicit)]
  struct INPUT_RECORD { [FieldOffset(0)] public ushort EventType; [FieldOffset(4)] public KEY_EVENT_RECORD Key; }
  [StructLayout(LayoutKind.Sequential)]
  struct KEY_EVENT_RECORD { public int bKeyDown; public ushort wRepeatCount; public ushort wVirtualKeyCode; public ushort wVirtualScanCode; public char UnicodeChar; public uint dwControlKeyState; }
  [DllImport("kernel32.dll", SetLastError=true, CharSet=CharSet.Unicode)]
  static extern IntPtr CreateFileW(string n, uint acc, uint share, IntPtr sec, uint disp, uint flags, IntPtr tmpl);
  [DllImport("kernel32.dll", SetLastError=true)]
  static extern bool WriteConsoleInput(IntPtr h, INPUT_RECORD[] b, uint len, out uint written);
  const string PASTE_BEGIN = "[200~";
  const string PASTE_END   = "[201~";
  static INPUT_RECORD Rec(char c, bool down) {
    var r = new INPUT_RECORD(); r.EventType = 1;
    r.Key.bKeyDown = down ? 1 : 0; r.Key.wRepeatCount = 1; r.Key.UnicodeChar = c;
    return r;
  }
  static IntPtr OpenConIn() {
    return CreateFileW("CONIN$", 0x80000000 | 0x40000000, 1 | 2, IntPtr.Zero, 3, 0, IntPtr.Zero);
  }
  static void SendChar(IntPtr h, char c) {
    var recs = new INPUT_RECORD[] { Rec(c, true), Rec(c, false) };
    uint w; WriteConsoleInput(h, recs, 2, out w);
  }
  static void SendStr(IntPtr h, string s) { foreach (char c in s) SendChar(h, c); }
  // Deliver text as a bracketed paste: newlines are preserved, nothing submits.
  static void SendPaste(string text) {
    IntPtr h = OpenConIn(); if (h == (IntPtr)(-1)) return;
    SendStr(h, PASTE_BEGIN);
    foreach (char c in text) { char e = (c == (char)10) ? (char)13 : c; SendChar(h, e); }
    SendStr(h, PASTE_END);
  }
  static void SendRaw(string text) {
    IntPtr h = OpenConIn(); if (h == (IntPtr)(-1)) return;
    SendStr(h, text);
  }
  // One ordered thread: wait for boot, bracketed-paste the message, then (AUTO only)
  // submit with a few spaced Enter retries. Ordering guarantees the paste precedes the
  // Enter; the retries cover a paste that Claude commits late under heavy multi-tab load.
  // A bare Enter on an empty box is a no-op in Claude, so extra attempts are harmless.
  public static void Deliver(int ms, string text, bool autoEnter) {
    var t = new Thread(delegate() {
      Thread.Sleep(ms);
      SendPaste(text);
      if (autoEnter) {
        for (int i = 0; i < 3; i++) { Thread.Sleep(2500); SendRaw("\r"); }
      }
    });
    t.IsBackground = true; t.Start();
  }
}
"@

Set-Location -LiteralPath $Worktree
$msg = Get-Content -Raw -LiteralPath $PromptFile

# Append-only gate trace: one timestamped line per state transition.
function Write-GateLog {
    param([string]$Message)
    if (-not $StateDir) { return }
    try {
        $gateDir = Join-Path $StateDir "gate"
        if (-not (Test-Path -LiteralPath $gateDir)) { New-Item -ItemType Directory -Path $gateDir -Force | Out-Null }
        $stamp = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
        Add-Content -LiteralPath (Join-Path $gateDir ("{0}.gate.log" -f $Id)) -Value ("{0} {1}" -f $stamp, $Message) -Encoding Ascii
    } catch {}
}

# True if a key was pressed (drain it). Guarded so a redirected/absent console never throws.
function Test-ForceKey {
    try { if ([Console]::KeyAvailable) { [Console]::ReadKey($true) | Out-Null; return $true } } catch {}
    return $false
}

# Lazy-boot gate: block until every dependency has a .done sentinel (normal RELEASE, returns
# $true), or the user force-launches with any key (returns $false -> paste unsubmitted). A
# .failed/.aborted dependency prints a warning once and keeps waiting; a later .done recovers.
function Invoke-GateWait {
    param([string]$StateDir, [string[]]$Deps)
    $host.ui.RawUI.WindowTitle = "[WAIT] $Id"
    Write-Host ""
    Write-Host "[WAIT] $Id - lazy-boot gate: claude is NOT running yet." -ForegroundColor Cyan
    Write-Host "  Waiting for these dependencies to signal done: $($Deps -join ', ')" -ForegroundColor DarkCyan
    Write-Host "  Press any key to force-launch now (prompt pasted, NOT submitted)." -ForegroundColor DarkGray
    Write-GateLog ("WAIT deps=" + ($Deps -join ','))
    $warned = @{}
    while ($true) {
        if (Test-ForceKey) {
            Write-Host "[FORCE] $Id - key pressed; launching now, prompt will not auto-submit." -ForegroundColor Yellow
            Write-GateLog "FORCE-LAUNCH key-pressed"
            return $false
        }
        $allDone = $true
        foreach ($d in $Deps) {
            $doneF = Join-Path $StateDir ("$d.done")
            $failF = Join-Path $StateDir ("$d.failed")
            $abrtF = Join-Path $StateDir ("$d.aborted")
            if (-not (Test-Path -LiteralPath $doneF)) { $allDone = $false }
            if ((Test-Path -LiteralPath $failF) -or (Test-Path -LiteralPath $abrtF)) {
                if (-not $warned.ContainsKey($d)) {
                    $warned[$d] = $true
                    Write-Host "  [warn] dependency '$d' signalled failed/aborted - fix and re-signal done, or press any key to launch anyway." -ForegroundColor Red
                    Write-GateLog "DEP-FAILED $d"
                }
            } elseif ($warned.ContainsKey($d)) {
                # Recovered: the failing dep was re-signalled (opposite sentinel deleted).
                $warned.Remove($d)
                Write-Host "  [ok] dependency '$d' recovered." -ForegroundColor Green
                Write-GateLog "DEP-RECOVERED $d"
            }
        }
        if ($allDone) {
            Write-Host "[RELEASE] $Id - all dependencies done; booting claude and self-submitting." -ForegroundColor Green
            Write-GateLog "RELEASE all-deps-done"
            return $true
        }
        Start-Sleep -Seconds 5
    }
}

# Decide auto-submit. A gated session (has deps + a state dir) waits at the gate first;
# a normal RELEASE self-submits, a FORCE-LAUNCH pastes without submitting. A non-gated
# session keeps the original -AutoEnter behavior.
$depList = @($DependsOn -split '\s*,\s*' | Where-Object { $_ })
$isGated = ($depList.Count -gt 0) -and $StateDir
$autoEnterFinal = [bool]$AutoEnter
if ($isGated) {
    $released = Invoke-GateWait -StateDir $StateDir -Deps $depList
    $autoEnterFinal = $released
    $host.ui.RawUI.WindowTitle = "[RUN] $Id"
} else {
    $host.ui.RawUI.WindowTitle = $Id
}

# Export the orchestration env for claude -> hooks -> the PowerShell tool (child processes
# inherit). complete-session.ps1 still takes an explicit -SessionId, so env loss is never fatal.
$env:CLAUDE_SESSION_LABEL = $Id
if ($StateDir) { $env:CLAUDE_ORCH_STATE_DIR = $StateDir }
if ($PlanSlug) { $env:CLAUDE_ORCH_PLAN_SLUG = $PlanSlug }

# Transcript-persistence guard (A): clear any capture/alarm state left by a prior run of THIS id
# (a -Resume or manual respawn; a -Reset already archives the whole state dir), then pre-flight
# that the transcript-guard hooks are actually registered in this worktree's settings.json - if
# not, the SessionStart capture will never fire and the watcher below will alarm HOOK-SILENT.
if ($StateDir) {
    $gateDir = Join-Path $StateDir "gate"
    foreach ($ext in @('.session', '.transcript-missing', '.hook-missing')) {
        $stale = Join-Path $gateDir ($Id + $ext)
        if (Test-Path -LiteralPath $stale) { Remove-Item -LiteralPath $stale -Force -ErrorAction SilentlyContinue }
    }
    Write-GateLog "SPAWN capture-state cleared"
    $projSettings = Join-Path $Worktree ".claude\settings.json"
    $hooksOk = (Test-Path -LiteralPath $projSettings) -and ((Get-Content -LiteralPath $projSettings -Raw -ErrorAction SilentlyContinue) -match 'capture-session-start\.ps1')
    if (-not $hooksOk) {
        Write-Host "[warn] transcript-guard hooks not registered in $projSettings - run: register-transcript-hooks.ps1 -ProjectPath `"$Worktree`"" -ForegroundColor Yellow
        Write-GateLog "HOOKS-UNREGISTERED warning shown"
    }
}

# Paste the whole message (tag + directives + prompt) once Claude has booted past its startup
# input-flush. Submit ~1.2 s later (auto-submit path only) so a busy boot cannot swallow the
# Enter. Force-launched / HELD sessions get the message in the box, unsubmitted.
[ConInject]::Deliver($DelayMs, $msg, [bool]$autoEnterFinal)

# Launch Claude already configured: named, recommended 1M-context model, chosen effort.
# Base model ('opus'/'sonnet'/'fable') gets the [1m] suffix here to guarantee 1M context.
# Permission mode: 'skip' -> --dangerously-skip-permissions (fully unattended); 'auto' ->
# --permission-mode auto (the shift+tab "auto mode": edits auto-accepted, other actions still
# prompt and surface as input-needed toasts).
$claudeArgs = @('--name', $Id)
if ($Model)  { $claudeArgs += @('--model', ($Model + '[1m]')) }
if ($Effort) { $claudeArgs += @('--effort', $Effort) }
if     ($PermissionMode -eq 'skip') { $claudeArgs += '--dangerously-skip-permissions' }
elseif ($PermissionMode -eq 'auto') { $claudeArgs += @('--permission-mode', 'auto') }

# Transcript-persistence guard (B): launch the detached one-shot watcher just before claude boots,
# so its clock starts when the session actually starts (correct even for lazy-boot gated tabs). It
# waits for the SessionStart capture, then confirms the transcript exists on disk, alarming if not.
if ($StateDir) {
    $watch = Join-Path $PSScriptRoot "verify-session-boot.ps1"
    if (Test-Path -LiteralPath $watch) {
        $timeoutSec = 90 + [int]($DelayMs / 1000)
        $q = { param($s) '"' + ([string]$s -replace '"', "'") + '"' }
        $wargs = '-NoProfile -ExecutionPolicy Bypass -File {0} -Id {1} -StateDir {2} -TimeoutSec {3}' -f `
            (& $q $watch), (& $q $Id), (& $q $StateDir), $timeoutSec
        Start-Process -FilePath 'powershell.exe' -WindowStyle Hidden -ArgumentList $wargs | Out-Null
        Write-GateLog "WATCHER spawned"
    }
}

# Transcript-persistence guard (bridge-env scrub): the root cause of spawned tabs not persisting a
# resumable transcript. If the spawner was launched from a Claude Code session that is itself a bridge
# child (Claude running inside a claude.ai web/mobile session exports CLAUDE_CODE_CHILD_SESSION=1,
# CLAUDE_CODE_BRIDGE_SESSION_ID and CLAUDE_CODE_SESSION_ID), those are INHERITED by this tab and make
# the spawned `claude` boot as a bridge child that streams to the cloud instead of writing a local
# ~/.claude\projects\<slug>\<uuid>.jsonl - so `claude --resume <uuid>` can never reopen it. Removing
# them here makes every spawned tab an independent, locally-persisted, resumable session. It is a
# no-op when they are absent (a spawner run from a plain terminal has none), so it never changes
# normal use. CLAUDE_ORCH_* / CLAUDE_SESSION_LABEL are deliberately kept: the SessionStart capture
# needs them and Claude ignores them.
$bridgeVars = @('CLAUDE_CODE_SESSION_ID', 'CLAUDE_CODE_CHILD_SESSION', 'CLAUDE_CODE_BRIDGE_SESSION_ID')
$scrubbed = @()
foreach ($bv in $bridgeVars) {
    if (Test-Path -LiteralPath ("Env:" + $bv)) { Remove-Item -LiteralPath ("Env:" + $bv) -Force -ErrorAction SilentlyContinue; $scrubbed += $bv }
}
# Defensive: catch any future CLAUDE_CODE_BRIDGE_* the CLI might add.
Get-ChildItem Env: | Where-Object { $_.Name -like 'CLAUDE_CODE_BRIDGE_*' } | ForEach-Object {
    Remove-Item -LiteralPath ("Env:" + $_.Name) -Force -ErrorAction SilentlyContinue; $scrubbed += $_.Name
}
if ($scrubbed.Count -gt 0) { Write-GateLog ("BRIDGE-ENV scrubbed " + (($scrubbed | Select-Object -Unique) -join ',')) }

claude @claudeArgs

# Abort sentinel: if claude returned without this session signalling completion, mark it
# .aborted so gated dependents don't hang. -SkipIfFinished makes this a no-op when a real
# .done/.failed already exists. Covers /exit, Ctrl+C, and crashes (the -NoExit shell regains
# control here); a hard tab-kill leaves no sentinel and the DAG fails safe.
if ($StateDir) {
    $completeScript = Join-Path $PSScriptRoot "complete-session.ps1"
    $sentinelExists = @('done', 'failed', 'aborted') | Where-Object { Test-Path -LiteralPath (Join-Path $StateDir ("{0}.{1}" -f $Id, $_)) }
    if ((Test-Path -LiteralPath $completeScript) -and -not $sentinelExists) {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $completeScript -SessionId $Id -Status aborted -SkipIfFinished -StateDir $StateDir -Summary "claude exited without signaling completion"
    }
}

# Transcript-persistence guard (C): on exit, print an explicit verdict from the UUID captured at
# boot, plus a resume hint. A missing transcript means the conversation is unrecoverable - say so
# loudly (and alarm once) so it is never discovered only after a later crash.
if ($StateDir) {
    $gateDir = Join-Path $StateDir "gate"
    $sessFile = Join-Path $gateDir ($Id + ".session")
    if (Test-Path -LiteralPath $sessFile) {
        try {
            $sess = Get-Content -LiteralPath $sessFile -Raw | ConvertFrom-Json
            if ($sess.transcriptPath -and (Test-Path -LiteralPath $sess.transcriptPath)) {
                $bytes = (Get-Item -LiteralPath $sess.transcriptPath).Length
                Write-Host ("[transcript] OK  {0}  ({1} bytes)" -f $sess.transcriptPath, $bytes) -ForegroundColor Green
                Write-Host ("[transcript] resume with:  claude --resume {0}" -f $sess.sessionId) -ForegroundColor DarkGray
                Write-GateLog ("TRANSCRIPT-OK exit uuid=" + $sess.sessionId)
            } else {
                Write-Host ("[transcript] MISSING - {0} was never written to disk (claude --resume will not work for this session)." -f $sess.transcriptPath) -ForegroundColor Red
                Write-Host "             If you ran /export to session-logs\, that snapshot IS your transcript; if not, this conversation is lost." -ForegroundColor Red
                Write-GateLog ("TRANSCRIPT-MISSING exit uuid=" + $sess.sessionId)
                $marker = Join-Path $gateDir ($Id + ".transcript-missing")
                if (-not (Test-Path -LiteralPath $marker)) {
                    Set-Content -LiteralPath $marker -Value ("exit uuid=" + $sess.sessionId) -Encoding Ascii -ErrorAction SilentlyContinue
                    $notify = Join-Path $PSScriptRoot "notify-desktop.ps1"
                    if (Test-Path -LiteralPath $notify) {
                        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $notify -Kind failed -Title ("Transcript MISSING: " + $Id) -Body ("Not on disk: " + $sess.transcriptPath) | Out-Null
                    }
                }
            }
        } catch {
            Write-Host "[transcript] capture file unreadable: $sessFile" -ForegroundColor Yellow
        }
    } else {
        Write-Host "[transcript] no capture recorded - the SessionStart hook did not fire (see gate log)." -ForegroundColor Yellow
        Write-GateLog "TRANSCRIPT-UNKNOWN no .session at exit"
    }
}

# Guard: if Claude exited abnormally (e.g. was killed) it may not have disabled the
# mouse-reporting mode it turned on, which leaves the leftover prompt spewing mouse
# escape sequences ([<b;x;y>M) on every pointer move. -NoExit returns control here on
# any exit, so reset the mouse modes and show the cursor. Harmless after a clean exit.
$esc = [char]27
[Console]::Write("$esc[?1000l$esc[?1002l$esc[?1003l$esc[?1006l$esc[?1015l$esc[?25h")
