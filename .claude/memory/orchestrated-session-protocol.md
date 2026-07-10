---
name: orchestrated-session-protocol
description: Every orchestrated session ends by reporting, signaling completion via complete-session.ps1, and respecting the gate/oracle/SOLID/secrets rules that keep the DAG safe
metadata:
  type: feedback
---

1. **Report before signaling.** Before you signal completion, write `<stateDir>\reports\<session-id>-report.md`
   covering: Status, Commit, Tests run + results (positive and negative), Review outcome (including
   any SOLID violations flagged), Issues encountered, Consultations, Deferred work. Add a one-line
   issues note to the plan's Implementation Log (or your session's `.implog.md` fragment if you are
   a parallel session).
2. **Signal via `complete-session.ps1`, always.** Every session - success or failure - ends by
   calling `complete-session.ps1 -SessionId <id> -Status done|failed -CommitSha <sha> -Summary "<one line>"`.
   This is not optional cleanup: dependent sessions' gated tabs poll for this sentinel and will
   never self-submit without it. A session that finishes without signaling stalls the whole DAG.
3. **A `.failed`/`.aborted` dependency never auto-starts its dependents.** The gate rule is strict:
   every declared dependency must be `.done`, or the dependent holds. If you are recovering a
   failed session, fix it and re-signal `-Status done` - do not try to work around a stuck
   dependent by hand-editing its gate state.
4. **Oracle gates are mandatory, not optional.** Consult the read-only `oracle` agent when: stuck
   after 2 failed attempts at the same problem, facing an architecture-risk fork, or about to
   abandon a Definition-of-Done item. Record every consult in your report. Tie-break: the oracle
   wins on architecture/correctness questions; you (the session) win on local mechanics.
5. **Produced code respects SOLID.** The pre-commit `/code-review` gate is where this is enforced -
   flag SOLID violations it surfaces in your report, fix the CONFIRMED ones before committing.
6. **No secrets, ever, in reports, summaries, or the manifest.** Sentinels and reports carry only
   ids, paths, and commit SHAs. `complete-session.ps1` refuses secret-shaped `-Summary`/`-CommitSha`
   input (exit 6) - if you hit that, the text you tried to write had a real secret-shaped substring
   in it; remove it, don't work around the guard.
7. **Transcript snapshots are user-typed, and you must prompt for them.** The verbatim transcript is
   exported with Claude Code's native `/export` - a REPL built-in the model CANNOT invoke (there is
   no tool for it). So the export is the human's action, and your job is to hand them the exact
   command: as your very last message, print `USER ACTION - type  /export session-logs/logs/<session-id>-final.txt`.
   Convention: interim snapshots are `<session-id>-vN.txt` (v1, v2, ...) taken at milestones; the
   wrap-up snapshot is `<session-id>-final.txt`; never overwrite an existing name (suffix `-2`). This
   is the belt-and-braces human-readable copy on top of the on-disk `.jsonl`; the transcript-guard
   hooks separately verify that `.jsonl` was written and alarm if it was not (see the scripts README).

**Why:** the orchestration DAG has no supervisor polling for progress - sessions coordinate purely
through sentinel files and reports. Skipping the signal, working around a failed gate, or leaking a
secret into a file that survives outside the repo (the state dir is never gitignored, never cleaned
up) turns a local mistake into a stuck pipeline or a leaked credential. And a transcript that is
never exported (or worse, never even written to disk) is a conversation lost for good - the reason
the guard and the `/export` habit exist at all.

**How to apply:** treat steps 1-2 as the literal last two actions of every orchestrated session, in
that order, and step 7 (print the `/export` USER ACTION line) as the very last thing you emit. Apply
3-6 throughout the session, not just at the end.
