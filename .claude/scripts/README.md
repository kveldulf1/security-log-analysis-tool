# Plan-session spawn scripts

A small PowerShell family for turning a `/split-plan-into-sessions` breakdown into
one live Claude Code session per plan session, each in its own named Windows Terminal
tab -- optionally each in its own isolated git worktree.

## 1. What's here

| Script | Role |
|---|---|
| `spawn-plan-sessions.ps1` | Reads a plan file's `## Session Breakdown`, and for each `### <slug>-session-N` entry opens one named Windows Terminal tab running interactive Claude, injecting that session's cold-start prompt. Writes the orchestration `manifest.json`. The one you run. |
| `spawn-session-tab.ps1` | Per-tab runner. Launches Claude inside a single tab and bracketed-paste-injects the pre-assembled message into that tab's own console; for a gated session it lazy-boots (waits in plain PowerShell, no claude process, until its dependencies signal `.done`). **Not run directly** -- the spawner invokes it once per session. |
| `cleanup-plan-worktrees.ps1` | Removes the per-session git worktrees + branches that `-PerSessionWorktrees` created, once their branches have merged back. Separate lifecycle: runs days later, needs no plan file. |
| `complete-session.ps1` | The mandatory last step of every orchestrated session: writes a `.done`/`.failed`/`.aborted` sentinel, so dependents' gated tabs know when to self-submit. Also called automatically by `spawn-session-tab.ps1` on an unsignaled claude exit (`.aborted`). See "Orchestration" below. |
| `notify-desktop.ps1` | Native Windows-PowerShell-5.1 toast (no BurntToast). Used internally by `complete-session.ps1` and the `notify-input-needed.ps1` hook; callable standalone. |
| `orchestration-status.ps1` | Read-only status table for a plan's orchestration state (or an overview of every known plan). Adds `UUID` + `TRANSCRIPT` columns (from the guard's `gate\<id>.session` capture). Exit 1 if anything is `FAILED`/`ABORTED` **or has a MISSING transcript**, so it is scriptable. |
| `capture-session-start.ps1` | **SessionStart hook** (registered in the project's `settings.json`). Records the real Claude session UUID + transcript path at boot to `gate\<id>.session` (orchestrated) and to `~/.claude\logs\session-registry.log` (always). Prints nothing to stdout; always exits 0. |
| `check-transcript-stop.ps1` | **Stop hook**. Verifies the session's `.jsonl` transcript exists on disk at every turn end; on a miss, logs it, drops a `.transcript-missing` marker, and fires one (debounced) desktop toast telling you to `/export` before closing the tab. Always exits 0. |
| `verify-session-boot.ps1` | Detached one-shot watcher, spawned per tab by `spawn-session-tab.ps1`. Catches what the Stop hook can't: a hook that never fired (`HOOK-SILENT`), or a session that boots but never persists a transcript. Time-bounded, self-exits. |
| `register-transcript-hooks.ps1` | Retrofit tool: non-destructively merges the SessionStart/Stop hooks into an already-seeded project's `settings.json` (a fresh seed ships them in the template). `-ProjectPath <dir> [-DryRun]`. Backs up, validates, and aborts without writing on any doubt. Idempotent. |
| `resume-session.ps1` | Turn an orchestration label back into a live conversation: reads the guard's `gate\<id>.session` capture, confirms the `.jsonl` is on disk, then runs `claude --resume <uuid>` from the recorded cwd. `-Id <label>` with `-PlanSlug <slug>`/`-StateDir <path>` (or a bare `-Id` scan of every plan); `-Uuid <uuid>` resumes a pre-guard session straight from `~/.claude\projects\`; `-DryRun` prints the command without launching. Exit 2 when the transcript was never written (honest "not resumable" verdict pointing at your `/export` snapshots). |

How they fit with the skill: [`/split-plan-into-sessions`](../skills/split-plan-into-sessions/SKILL.md)
**writes** the `## Session Breakdown` (session headings, `**Parallelization:**` lines,
`**Cold-start prompt**` blockquotes) into the plan file; these scripts **consume** that
section. The skill never runs code; the scripts never edit the plan.

Auto-submit is driven per session by its `**Parallelization:**` line:

- `blocked by none` -> the session is safe to start now -> inject prompt **and** press Enter (AUTO).
- `blocked by <X>` -> it must wait for a prerequisite -> inject the prompt only, HELD; you press Enter yourself once `<X>` has shipped.
- no `Parallelization` line -> HELD (never auto-run something we can't prove is unblocked).

## 2. System requirements

- **Windows 10 / 11.**
- **Windows Terminal** (`wt.exe` on `PATH`) -- for actually opening tabs. Not needed under `-DryRun` or `-NoTabs`.
- **Windows PowerShell 5.1+** -- the scripts are 5.1-compatible and pure ASCII (no `&&`, no ternary, no non-ASCII source).
- **git >= 2.5** -- worktree support (`git worktree add/list/remove/prune`).
- **Claude Code CLI** on `PATH` supporting `--name`, `--model` (including the `[1m]` 1M-context suffix), `--effort`, and `--dangerously-skip-permissions`.

## 3. Installing / adjusting paths

The scripts hardcode **no** user paths -- install them anywhere. In this repo they live at
`.claude\scripts\`. Invoke from the repo root with an absolute plan path:

```powershell
& ".\.claude\scripts\spawn-plan-sessions.ps1" -PlanFile 'C:\path\to\plan.md'
```

Path rules:

- **`spawn-session-tab.ps1` must sit next to `spawn-plan-sessions.ps1`** -- the spawner finds it via `$PSScriptRoot`. Keep the two together.
- **Plan files can live anywhere** -- pass the absolute path as `-PlanFile`.
- **Worktrees are derived from the target repo**, not from where the scripts live: `<repoParent>\<repoName>.worktrees\<session-id>` (sibling to the repo dir). Branches are `sessions/<session-id>`.
- **Prompt files** go to `<stateDir>\prompts\<session-id>.txt` (the orchestration state dir -- see "Orchestration" below), not a temp folder, so they survive alongside the reports and sentinels they're paired with.
- **Worktree markers**: each created worktree gets `.claude-spawn-worktree.json` (self-describing: sessionId, planFile, branch, baseSha, baseBranch, createdUtc, tool). The filename is appended once to the repo's shared `.git\info\exclude` so session agents never commit it.

**One behavioral coupling:** the parser expects the exact Session Breakdown format the
skill emits -- `### <slug>-session-N` headings, a `**Parallelization:**` line, and a
`**Cold-start prompt**` blockquote. You can hand-write a compatible plan file without the
skill; just match that shape.

## 4. Parameter reference

### `spawn-plan-sessions.ps1`

| Param | Default | Meaning |
|---|---|---|
| `-PlanFile` (required) | -- | Absolute path to the plan file. |
| `-WorktreePath` | current dir | Repo / worktree the shared (sequential) sessions run in; also the base for `-PerSessionWorktrees`. |
| `-Yes` | off | Skip the confirmation prompt. |
| `-DryRun` | off | Print the plan (and worktree plan) and exit; creates nothing, opens nothing. |
| `-PerSessionWorktrees` | off | Give each **PARALLEL** session its own git worktree + branch; sequential/solo sessions stay in the shared worktree. |
| `-NoTabs` | off | Create worktrees / write prompt files but skip `wt.exe` (also skips the `wt.exe` PATH check). Useful for scripted / agentic testing. |
| `-BaseRef` | `HEAD` | Base commit/ref for new session branches. |
| `-BootDelaySeconds` | `15` | Seconds to wait for Claude's TUI before injecting. Raise on slow machines / under heavy multi-tab load. |
| `-Effort` | `high` | `--effort` value passed to Claude (`low`/`medium`/`high`/`xhigh`/`max`). |
| `-Permissions` | (asks) | `skip` (`--dangerously-skip-permissions`) or `auto` (`--permission-mode auto`). Omit to be asked interactively `[1] skip [2] auto`; a bare flag with no value is invalid -- pass one of the two values. |
| `-Reset` | off | Archive any prior orchestration state for this plan's slug (never deletes -- moved under `archive\<utc>\`) and start fresh. Required before re-running over an existing, non-`-Resume` state dir. |
| `-Resume` | off | Re-run against the existing state dir: sessions already `.done` are skipped (`SKIP (done)`, no tab). Validates the manifest's recorded plan file matches (`exit 1` on a moved/renamed plan) and warns on a changed plan-file hash. |

See "Orchestration" below for the state directory these flags manage, and `orchestration-status.ps1` for checking progress.

### `cleanup-plan-worktrees.ps1`

| Param | Default | Meaning |
|---|---|---|
| `-RepoPath` | current dir | Any path inside the main repo. |
| `-Slug` | (all) | Only clean session ids starting with this slug. |
| `-MergedInto` | current branch | Merge target used to decide "merged". |
| `-DryRun` | off | Classify and print planned actions; remove nothing. |
| `-Yes` | off | Skip the batch confirm for CLEAN+MERGED removals (does **not** bypass the per-item `-Force` confirm). |
| `-Force` | off | Also offer DIRTY / UNMERGED worktrees for removal, each behind an individual confirm. |
| `-KeepBranches` | off | Remove worktrees but leave their branches. |

## 5. Orchestration

Every spawn writes state **outside the repo**, under `$env:USERPROFILE\.claude\orchestration\<plan-slug>\`
(the slug is the plan's session ids with the trailing `-session-N` stripped). Nothing here is
committable and nothing needs a `.gitignore` entry.

```
manifest.json                    static DAG (id, model, blockedBy, role, permissions, ...), written once
prompts\<session-id>.txt         injected cold-start messages
reports\<session-id>-report.md   per-session report (Status, Commit, Tests, Review, Issues, ...)
<session-id>.done|.failed|.aborted   sentinels (JSON: sessionId, status, utc, commitSha, branch, summary, reportFile, writer)
gate\<session-id>.gate.log       lazy-boot gate trace (append-only) for GATED sessions
gate\<session-id>.session        transcript-guard capture: real Claude UUID + transcript path (JSON)
gate\<session-id>.transcript-missing   marker: the .jsonl was not on disk (alarm debounce)
gate\<session-id>.hook-missing   marker: the SessionStart capture never appeared (hook not firing)
_all-done.fired                 atomic claim marker - the ALL-DONE toast fires exactly once
archive\<utc-stamp>\...          state moved aside by -Reset (never deleted)
```

**Tab labels, three kinds:**

- **AUTO** -- `blocked by none`. Boots immediately, prompt injected and submitted.
- **GATED** -- `blocked by <parseable session ids>`. Lazy-boots: the tab waits in plain PowerShell
  (no claude process, a few MB) polling sentinels every ~5 s. All deps `.done` -> releases and
  self-submits, no human Enter. A `.failed`/`.aborted` dep prints a warning and keeps waiting (a
  later re-signaled `.done` auto-recovers). Any keypress force-launches (prompt pasted, not
  submitted -- you took control).
- **HELD** -- blocked by unparseable prose, or no `Parallelization` line. Legacy behavior: prompt
  injected only, you press Enter.

**Permission modes** (`-Permissions skip|auto`, asked interactively when omitted): `skip` launches
each tab with `--dangerously-skip-permissions`; `auto` uses `--permission-mode auto` (edits
auto-accepted, other actions still prompt -- those prompts surface as desktop "Input needed" toasts
via the `notify-input-needed.ps1` Notification hook, see the repo's
[`docs/orchestration-workflow.md`](../../../docs/orchestration-workflow.md)).

**Recovery:**

- A session that finishes must call `complete-session.ps1 -SessionId <id> -Status done|failed -CommitSha <sha> -Summary "..."` -- this is baked into every cold-start prompt as the mandatory last step. Skipping it stalls every dependent.
- Fix a failed session, then re-signal `-Status done`; its dependents' gated tabs pick it up automatically.
- `-Reset` archives (never deletes) prior state for the slug and starts clean; `-Resume` re-runs the same plan, skipping sessions already `.done`.
- Check progress any time with `orchestration-status.ps1 -PlanSlug <slug>` (or with no args for an overview of every known plan).

**Limitations:** a hard tab-kill (closing the window, not `/exit`) leaves no sentinel -- dependents
fail safe by staying gated forever until you either re-run the tab's printed invocation or hand-signal
`complete-session.ps1`. Don't type into a still-`[WAIT]` gated tab except to deliberately force-launch
it -- it has no claude composer yet, so any keypress is treated as the override.

**Transcript-persistence guard.** A PowerShell crash once killed several spawned tabs whose main
conversation transcript (`~/.claude\projects\<slug>\<uuid>.jsonl`) had never been flushed to disk, so
those conversations were unrecoverable. The **root cause** (confirmed and fixed) was that launching the
spawner from a *bridge-child* Claude session (Claude inside a claude.ai web/mobile session) leaks
`CLAUDE_CODE_CHILD_SESSION` / `CLAUDE_CODE_BRIDGE_SESSION_ID` into every spawned tab, so each `claude`
streams to the cloud bridge instead of writing a local `.jsonl`; `spawn-session-tab.ps1` now scrubs
those before launching `claude`. The guard makes any *remaining* failure loud and immediate instead of
a silent post-crash discovery, in four layers (all in the seeded project's `.claude\scripts\` +
`settings.json`, mode-agnostic):

- **Capture** -- the SessionStart hook (`capture-session-start.ps1`) writes the real UUID + transcript
  path to `gate\<id>.session` and appends to `~/.claude\logs\session-registry.log`. This is the
  UUID-to-label map that lets `claude --resume <uuid>` work after the fact.
- **Detect** -- the Stop hook (`check-transcript-stop.ps1`) checks the `.jsonl` exists after every
  turn; the boot watcher (`verify-session-boot.ps1`, spawned by the tab runner) and the tab runner's
  own post-exit check cover the "hook never fired / session ended without a turn" cases. A miss ->
  `.transcript-missing` (or `.hook-missing`) marker + gate-log line + one desktop toast.
- **Snapshot** -- the human-readable copy is the user's `/export session-logs\logs\<id>-vN.txt` (and
  `-final.txt` at wrap-up); the model cannot invoke the `/export` built-in, so every session prints
  the exact command as its last line (baked into the cold-start wrap-up).
- **Recover** -- `resume-session.ps1 -Id <label> -PlanSlug <slug>` resolves the capture and runs
  `claude --resume <uuid>` from the recorded cwd when the transcript is on disk (honest verdict + a
  pointer to your `/export` snapshots when it is not); `-Uuid <uuid>` recovers a pre-guard session.

To retrofit a project seeded before the guard existed:
`register-transcript-hooks.ps1 -ProjectPath <dir>` (idempotent; restart any live session afterward so
it picks up the new hooks). Check status with `orchestration-status.ps1 -PlanSlug <slug>` -- the
`TRANSCRIPT` column shows `yes`/`MISSING`, and a `MISSING` makes the script exit 1.

## 6. Safety model

- **HELD vs AUTO vs GATED.** Only sessions proven unblocked (`blocked by none`) auto-submit immediately. GATED sessions self-submit once every dependency is `.done` (see "Orchestration" above) -- no human Enter needed. Everything else (HELD) is pasted into the box unsubmitted; you press Enter yourself.
- **Isolated worktrees are opt-in.** Without `-PerSessionWorktrees` every tab shares one worktree/branch -- fine for a single AUTO session, risky for several (a session's end-of-session `git add`/`commit` can sweep up a concurrent session's edits). With the switch, each parallel session commits on its own `sessions/<id>` branch.
- **Worktree trust is pre-registered.** A brand-new worktree folder would otherwise trigger claude's first-run "Do you trust the files in this folder?" dialog, which `--dangerously-skip-permissions` does not suppress and which swallows the injected prompt. Before spawning, `-PerSessionWorktrees` idempotently marks each fresh worktree path trusted in `~/.claude.json` (scoped to the `*.worktrees\` container only, rolling backup `.claude.json.spawn-trust.bak`) so AUTO tabs submit unattended. It never fails the spawn -- if the edit cannot be made it just warns and you may see the dialog.
- **Fail-fast, fresh-always worktree planning.** Before creating anything, the spawner resolves every parallel session to Create (no prior worktree/branch) or Recreate (discard and rebuild a spawn-managed leftover from the base ref) -- it never reuses or reattaches a previous run's worktree. A leftover holding uncommitted changes or commits not yet merged into the base ref aborts instead of being silently discarded (override with `-Force`); a directory or branch that isn't spawn-managed always aborts. See the header comment in `spawn-plan-sessions.ps1` for the exact rules.
- **Cleanup never force-removes silently.** The default pass removes only CLEAN + MERGED worktrees (plain `git worktree remove`, `git branch -d`). DIRTY / UNMERGED ones are touched only under `-Force`, and only after a per-item confirmation that `-Yes` does not bypass. LOCKED worktrees are never removed. Only worktrees under a `*.worktrees\` container that carry a valid marker and sit on a `sessions/*` branch are ever candidates -- foreign/unmarked worktrees are ignored.
- **Merge-back is manual.** Neither script merges session branches for you; the spawn summary reminds you to do it, then run cleanup.

## 7. Troubleshooting

- **Prompt didn't submit under load.** Many tabs booting at once can swallow the Enter. Raise `-BootDelaySeconds` (e.g. `-BootDelaySeconds 25`).
- **Garbled tab after killing Claude.** If Claude is killed it may leave mouse-reporting escape modes on; the per-tab runner resets them on exit. If a tab still spews `[<b;x;y>M` on pointer moves, close and reopen it.
- **`wt.exe` not found.** Install Windows Terminal, or use `-DryRun` / `-NoTabs` to run without opening tabs.
- **"branch already checked out" / "directory exists" on spawn.** A previous run's worktree is in the way. Inspect with `git worktree list`, then clear stale ones with `cleanup-plan-worktrees.ps1` (or `git worktree prune` for already-deleted dirs).
- **A dependent tab never self-submits.** Run `orchestration-status.ps1 -PlanSlug <slug>` -- if a dependency shows `FAILED`/`ABORTED` (making this one `DEP-FAILED`), fix it and re-signal `-Status done`. If it shows `GATED` with everything else `DONE`, check `<stateDir>\gate\<id>.gate.log` for the poll trace.
