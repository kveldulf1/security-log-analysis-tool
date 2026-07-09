---
name: export-session
description: "Produce the correct /export filename for the current Claude Code session and hand the user the exact line to type. Names follow the session spawner's scheme: <slug>-master-plan for the orchestrator/planning session, and <N><s|p>-<slug>-session-<N> for spawned workers (e.g. 1s-logwarden-session-1, 2s-logwarden-session-2, 3p-logwarden-session-3). Use whenever the user wants to export/save/snapshot the session transcript to session-logs with a meaningful name."
user-invocable: true
allowed-tools: Bash, Read, Glob
argument-hint: "[session-id | master | plan-slug] [--interim N | --final]"
---

# Export Session

## Purpose

Give the user the right `/export` command to snapshot **this** session's transcript into `session-logs/`
with a meaningful, spawner-consistent filename.

**You cannot run `/export` yourself** — it is a Claude Code REPL built-in with no tool behind it. So the
deliverable of this skill is: figure out the correct filename, then print the exact
`USER ACTION - type  /export session-logs/<name>.txt` line for the human to type.

## Naming convention

Mirrors how `spawn-plan-sessions.ps1` labels sessions:

| Session kind | Filename (in `session-logs/`) | Example |
| --- | --- | --- |
| Orchestrator / planning session (ran `/split-plan-into-sessions`, spawned the workers) | `<slug>-master-plan.txt` | `logwarden-master-plan.txt` |
| Spawned worker session | `<N><s\|p>-<slug>-session-<N>.txt` | `1s-logwarden-session-1.txt`, `3p-logwarden-session-3.txt` |

- `<N>` — the session number (from `-session-N`).
- `s` / `p` — **s**equential or **p**arallel, read from the orchestration manifest's `tagType`
  (the exact tag the spawner assigns from each session's `**Parallelization:**` line). The resolver
  reads it for you; you do not judge it by hand.

Suffixes (optional): wrap-up snapshot with `--final` → `-final`; interim milestone with `--interim N` →
`-vN`. If a target file already exists, the resolver auto-suffixes `-2`, `-3`, … so a prior snapshot is
never overwritten (the orchestrated-session protocol's rule).

## Procedure

1. **Determine identity.** In priority order:
   - An explicit argument from the user (a session id like `logwarden-session-3`, the word `master`
     plus a slug, or a plan slug).
   - **This session's own cold-start prompt** — a spawned worker was booted with its id baked in
     (look in your context for `complete-session.ps1 ... -SessionId <id>` or an
     `/export session-logs/<id>-...` hint). If you see it, that is your `-SessionId`.
   - The worktree marker `.claude-spawn-worktree.json` in the repo root (`sessionId` field).
   - The git branch: a parallel worker runs on `sessions/<session-id>`.
   - If this is clearly the **planning/orchestrator** session (you ran `/split-plan-into-sessions`
     and spawned the workers, and are on the base branch), treat it as master-plan.

2. **Run the resolver** (it reads the manifest for the s/p tag and picks a non-overwriting name):

   ```bash
   powershell -NoProfile -ExecutionPolicy Bypass \
     -File .claude/skills/export-session/resolve-export-name.ps1 \
     -SessionId <slug>-session-N            # worker
   # or, for the planning session:
   powershell -NoProfile -ExecutionPolicy Bypass \
     -File .claude/skills/export-session/resolve-export-name.ps1 \
     -MasterPlan -Slug <slug>
   ```

   Add `-Final` for the wrap-up snapshot or `-Interim N` for an interim one. If the manifest is missing
   and you already know the kind, pass `-Type s` or `-Type p` to set the letter explicitly.

3. **Relay the result.** The resolver prints the `/export session-logs/<name>.txt` line. Present it to
   the user verbatim as the last thing you say:

   > USER ACTION — type  `/export session-logs/<name>.txt`  in this tab to save the transcript snapshot.

   Do **not** try to invoke `/export` through any tool — there isn't one.

## Fallback (ad-hoc session, no orchestration state)

If this session was not spawned by the orchestrator and has no plan slug (a plain one-off chat), there
is no manifest to consult. Ask the user for a short descriptive name, then hand them
`/export session-logs/<their-name>.txt` (kebab-case, no spaces — recall the earlier lesson that
`/export` takes the whole argument literally as the path).

## Files

- `resolve-export-name.ps1` — the deterministic name resolver (identity detection + manifest lookup +
  no-overwrite). Windows PowerShell 5.1 compatible.
- `test-resolve-export-name.ps1` — self-tests (positive + negative). Run:
  `powershell -NoProfile -ExecutionPolicy Bypass -File .claude/skills/export-session/test-resolve-export-name.ps1`.
