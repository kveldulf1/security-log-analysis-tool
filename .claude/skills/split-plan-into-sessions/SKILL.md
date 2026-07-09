---
name: split-plan-into-sessions
description: "Break a finalized implementation plan into a sequence of focused chat sessions, each producing one committable PR. Use for large plans (>2,000 LOC, >15 files, or natural module boundaries). Each session is self-contained, startable cold from the plan file, and ends with a green commit."
user-invocable: true
allowed-tools: Read, Grep, Glob, Edit, Bash
model: opus
argument-hint: "[path to plan file]"
---

# Split a Plan into Implementation Sessions

## Purpose

Some plans are big. Executing them in a single chat session is technically possible — context windows are large — but it produces:

- Unreviewable PRs (4,000+ LOC in one commit nobody can review).
- No recovery checkpoints (a bad call in chunk 1 means redoing everything).
- Cognitive coherence drift on very long sessions.
- Risk of mid-implementation context compression, which loses detail.

This skill carves an approved plan into 3–7 **focused implementation sessions plus one mandatory final validation session**, where each session:

- Has a single coherent scope (one module, one layer, one product).
- Ships a reviewable PR / commit at the end.
- Can be started from a fresh chat by reading the plan file + previous commits.
- Has a clear definition of done and a cold-start prompt the user copy-pastes.

Sessions are for **human-scale review checkpoints**: each one is a self-contained chat that ends in a reviewable commit, so a large plan lands as a readable sequence of PRs instead of one unreviewable diff.

---

## When to suggest invoking this skill

Look at the **plan that was just approved** (or the one the user is about to start implementing). Recommend `split-plan-into-sessions` when **any two** of the following are true:

| Signal | Threshold |
|---|---|
| Estimated total LOC of new code | ≥ 2,000 |
| Number of files to be created or modified | ≥ 15 |
| Independent module/layer boundaries visible | ≥ 3 |
| Plan mentions distinct "phases" or "milestones" | ≥ 3 |
| Plan touches multiple products (API + UI, library + CLI, etc.) | yes |
| Plan has a long "Out of Scope" list that hints at staged delivery | yes |
| User explicitly asks: "is this too big for one session?" | yes |

**Do not** recommend this skill for:

- Bug fixes (always one session).
- Single-file changes regardless of size.
- Plans that estimate < 1,000 LOC.
- Plans where every change is in one tightly coupled module — splitting would break atomicity.
- Plans the user wants to do *exploratorily* (sessions assume a stable target).

When recommending, phrase it as: *"This plan estimates ~X LOC across ~Y files with N natural boundaries. Want me to invoke `/split-plan-into-sessions <plan-file>` so each chunk becomes its own session with its own commit? Otherwise we can do it in one go."* Let the user decide.

---

## Invocation contract

When the user invokes `/split-plan-into-sessions <plan-file>`:

1. Read the plan file completely.
2. **Derive a meaningful plan slug** (see *Naming — enforced* below) — kebab-case, describing what the plan builds. **Never** inherit the plan file's auto-generated whimsical slug (`shimmering-flame`, `moonlit-sloth`, `robust-phoenix`). If you cannot infer a good slug, ask the user for one before proceeding.
3. Identify natural session boundaries using the rubric below. Always append one mandatory final validation session after the implementation sessions (rubric 9) — it is not optional and does not count against the session-cap rubric.
4. Append a `## Session Breakdown` section to the plan file (do not create a new file). Name **every** session `<plan-slug>-session-N` — never a bare `Session N`.
5. Append an `## Implementation Log` stub section directly after `Session Breakdown` if one does not already exist.
6. Print a short summary to the user: number of sessions, model recommendation per session, total estimated wall-clock, and the cold-start prompt for `<plan-slug>-session-1`. Then print the ready-to-run spawn command (run from the repo root) — `& ".\.claude\scripts\spawn-plan-sessions.ps1" -PlanFile '<absolute plan path>'` — noting it opens one named Windows Terminal tab per session in the current worktree, each auto-running its cold-start prompt. If the breakdown has **parallel waves**, add `-PerSessionWorktrees`: each parallel session then gets its own git worktree + branch (`sessions/<plan-slug>-session-N`) under `<repoParent>\<repoName>.worktrees\`, so concurrent sessions never share one git index (their end-of-session commits can't sweep up each other's edits); sequential/solo sessions keep the shared worktree. Merge those branches back manually, then remove the merged worktrees with `& ".\.claude\scripts\cleanup-plan-worktrees.ps1"`. The `.ps1` launchers are Windows/PowerShell-only; the plan-carving logic in this skill is cross-platform.

   Mention the orchestration layer the spawn command drives: a manifest is written once under `$env:USERPROFILE\.claude\orchestration\<plan-slug>\`; blocked sessions open as self-gating tabs that poll their dependencies' sentinel files and **auto-submit the moment every blocker signals `.done`** — no one needs to press Enter on a blocked tab. Every session signals its own outcome by calling `complete-session.ps1 -Status done|failed` as the last step of its wrap-up (see the cold-start prompt template below). Progress at any point is `& ".\.claude\scripts\orchestration-status.ps1" -PlanSlug '<plan-slug>'`. The spawner itself asks a one-time numeric permission-mode question — *"Spawn tabs with which permission mode? [1] --dangerously-skip-permissions  [2] auto (--permission-mode auto)"* — before opening tabs, unless the caller already passed `-Permissions skip|auto`.
7. After printing the spawn command, **offer to run it yourself** (Bash is in this skill's `allowed-tools`). Once sessions are spawned, **do not start implementing** — instead remain open as the **product-owner (PO) console** for this plan (see *Product-owner dashboard* below). Your first action on entering PO mode is to tell the user to run `/model opus[1m]` in this chat, since PO work (status checks, failure diagnosis, replanning) wants a cheap, huge-context model and this skill cannot switch its own model programmatically.

If `Session Breakdown` already exists in the plan, do **not** overwrite it. Either:

- Append a new dated entry (`### Re-planned YYYY-MM-DD`) when the plan has materially changed, or
- Refuse the invocation with a one-line explanation.

---

## Product-owner dashboard (after spawning)

Once sessions are spawned, this chat does not end — it becomes the **product-owner (PO) console** for the plan. It acts only when the user speaks to it. It never polls.

**First action:** tell the user to run `/model opus[1m]` right now. Planning and carving ran on whatever model started this chat (often Fable); PO work is status-checking and diagnosis, which wants a cheap huge-context model, and no programmatic mid-session model switch exists for the agent itself — the user has to run the slash command. (Verify at implementation time whether that has changed; if a programmatic switch exists, use it instead and skip asking the user.)

From then on, respond to these triggers:

- **"status?"** (or similar) — run `& ".\.claude\scripts\orchestration-status.ps1" -PlanSlug '<plan-slug>'` and summarize the result against the concurrency matrix: what is DONE, what is GATED and waiting on what, what is READY.
- **A session reports FAILED / DEP-FAILED** — read `<session-id>-report.md` and the relevant `gate\<id>.gate.log` from the state dir, diagnose the cause, and guide the fix directly in that session's tab (or, if the tab is gone, spawn a replacement via the printed `spawn-session-tab.ps1` invocation). Once fixed, have the session re-signal `done` — its dependents self-release automatically.
- **ALL-DONE fires** — read `<plan-slug>-final-report.md` (written by the validation session) and present the executive summary to the user.
- **DAGs of more than 8 sessions** — after roughly half the sessions have signaled done, proactively re-read every report plus the specs of the sessions still to run, and confirm or replan them before the rest proceed (the mid-plan checkpoint from rubric 5).

**Explicitly forbidden in PO mode:** polling loops or long waits of any kind (the sentinel/gate mechanism is what makes waiting unnecessary), and starting implementation work itself — the PO console diagnoses and delegates, it does not write the fix.

---

## Carving rubric — how to choose session boundaries

Apply these in order. First match wins for each boundary.

### 0. Naming — enforced
Every session is identified as `<plan-slug>-session-N`, where `<plan-slug>` is a **meaningful, descriptive kebab-case name for the plan** (e.g. `cli-service-mappings`, `jenkins-service-failure-detection`). This is mandatory, not cosmetic: the planner emits whimsical random slugs (`shimmering-flame`, `moonlit-sloth`) that make plans impossible to tell apart in `~/.claude/plans/`. Derive the slug from what the plan builds; if the plan file's own name is whimsical and the content doesn't make a good slug obvious, **ask the user** for one. Use the `<plan-slug>-session-N` identifier consistently in the Session Breakdown headings, the Implementation Log headings, every cross-reference, and the cold-start prompts. Bare `Session N` is not acceptable output.

### 1. Dependency order, smallest dependee first
Sessions that are *consumed by* other sessions must ship first. Foundation modules (auth, HTTP client, logging, shared models, base classes) go in Session 1 even if they're small. Leaves (per-product wrappers, per-feature commands) go later.

### 2. Single-product scope
A session should touch **one product / one layer / one bounded module**. Don't mix three unrelated resource domains (e.g. "users + billing + reporting") in one session — make them three. Don't mix "library + CLI for the same domain" across sessions — keep them together for atomicity.

### 3. ~500–1,500 LOC per session
Within the layout from rules 1–2, target 500–1,500 LOC of net new code per session. If a single module exceeds 1,500 LOC, split it by **sub-scope**, not by file count:

- Wrong split: "Session 3a: half of orders.py, Session 3b: rest of orders.py"
- Right split: "Session 3a: order creation + retrieval, Session 3b: order fulfillment + returns"

### 4. Always end on a green commit
The final deliverable of every session is *runnable code with a passing smoke test*, not a half-built interface. If the natural cut leaves a session in an unrunnable state, move the cut.

### 5. 7 sessions is a soft default, not a hard cap
Recommend **≤ 7 implementation sessions** by default — beyond that, the plan is usually trying to do too much for one PR sequence, and re-scoping is often the right call. But this is a soft default guarding **human review bandwidth** (one PR to review per session) and **plan staleness** (a long-lived DAG drifts from the live codebase), not a capability limit — orchestration removes the old manual-coordination cost that originally motivated the cap. Allow a larger DAG (e.g. 13 sessions) when natural module boundaries genuinely produce more, but only after **asking the user** and stating the real costs above.

Going beyond 7 raises two additional requirements:
- The **concurrency matrix must still verify pairwise-disjoint write targets** for every session pair — this check is O(n²) (21 pairs at 7 sessions, 78 pairs at 13), so build it as an explicit matrix table, never hold it in memory or eyeball it.
- **Wave width stays ≤ 2–3 concurrently *working* sessions** regardless of total DAG size (a machine-resource ceiling, not a session-count one — see the spawner's lazy-boot gate). A DAG with more than 8 total sessions additionally gets a **mid-plan checkpoint**: once roughly half the sessions have signaled done, the PO console (see below) re-reads all reports plus the remaining session specs and confirms or replans them before the rest proceed.

The validation session (rubric 9) is always additional — it does not count against either the soft 7 default or the >8 checkpoint threshold.

### 6. Session 1 is always the foundation
Auth, HTTP client, logging, error envelope, shared models, package skeleton, config doctor, packaging metadata, and **the redaction / security floor test**. Session 1 establishes the patterns; everything downstream depends on it. Do not skip or shrink Session 1 to be "more efficient."

### 7. Polish is the final session
Tests, docs, README, discovery scripts, integration tests, anything that closes loose ends. Even if it's tiny.

### 8. Mark parallelism explicitly
Once boundaries are set, classify each session by its **write targets** (files, issue-tracker record sets, services). Two sessions are **parallel-safe** only if those targets are **disjoint**. Group parallel-safe sessions into **waves** (Wave 1, Wave 2, …) that respect dependency order; everything else is **solo/sequential**. Record this per session (the `Parallelization` line in the output template) and summarise it as a **concurrency matrix** in the Session Breakdown header. Never call sessions parallel-safe without checking disjoint write targets — the shared plan file's `Implementation Log` is itself a write target (see the fragment-file rule in *Execution mode*).

### 9. The final validation session — always
Every breakdown ends with one mandatory session beyond the implementation sessions: id `<plan-slug>-session-<N+1>`, name "Final validation". Its `Parallelization` line is `blocked by <every other session id> · mode solo/sequential` and it runs in the shared worktree (not an isolated one — it needs to see every branch). Scope: merge/verify every session branch in dependency order (stop and ask the user on non-trivial conflicts), fold any remaining `*.implog.md` fragments into the plan's Implementation Log and delete them, then run the whole-solution end-to-end verification from the plan's Verification section — **both positive and negative cases**. It consolidates every per-session report from the orchestration state dir into `<plan-slug>-final-report.md` next to the plan file (a table of status/commit/tests/review-findings/issues per session, then the integrated E2E results and any open risks), commits per the commit-policy memory, presents the user-facing summary, and signals its own completion via `complete-session.ps1` — since every other session depends on it, **its sentinel is the one that fires the ALL-DONE notification**. This session is always additional: it does not count against the rubric-5 session cap in either direction.

---

## Model selection per session

Recommend a model per session based on the work shape, not the session number. Pay the Opus premium only where it buys judgement.

| Session shape | Recommended model | Reasoning |
|---|---|---|
| Foundation: auth + HTTP + logging + errors + redaction tests | **Opus 4.8** | Decisions here propagate to every downstream session. Worth getting right. |
| New product surface where REST is well-documented (list/get/search endpoints) | **Sonnet 5** | Mechanical wrapping. Patterns are already set. |
| Product with quirks (hidden server state, XSRF/session-token endpoints, undocumented workflows) | **Sonnet 5**, escalate to Opus 4.8 for specific debugging | Most of it is mechanical; reserve Opus for the genuine wedges. |
| Migration of existing code onto new infrastructure | **Sonnet 5** | Pattern application. |
| Polish: tests, docs, discovery scripts | **Sonnet 5** | Mostly mechanical. |
| Anything described in the plan as "tricky", "needs research", or "TBD" | **Opus 4.8** | Judgement-heavy. |
| Final validation session (rubric 9) | **Opus 4.8**; **Fable 5** for architecture-heavy plans | Integration-level judgement across every branch; Fable's huge context suits plans with many cross-cutting sessions. |

Never recommend Haiku for a session — sessions are too big and too consequential. Haiku is appropriate for one-off lookups inside a session. The spawner's model parser accepts **Opus, Sonnet, or Fable** — write the model name in the `**Recommended model:**` line exactly (e.g. "Fable 5") so it parses correctly.

---

## Execution mode — distinct sessions vs. subagent fan-out

Sessions can run three ways. Pick by whether each unit needs a **human approval gate**:

| Unit shape | Recommended mode | Why |
|---|---|---|
| **Approval-gated writes** — each batch needs the user's dry-run OK (issue-tracker mutations, risky bulk edits, anything outward-facing) | **Distinct parallel sessions** (cap 2–3) | A subagent can't obtain per-batch human approval — it stalls or is tempted to bypass. Separate sessions keep independent approval loops, context, and recovery. |
| **Autonomous / read-only** — research, searches, mechanical transforms with no per-step approval | **Subagent fan-out** from one session | Converges to a single consolidated review; shared orchestration context. Isolate any file-writers in separate worktrees. |
| **Gated but you want fewer prompts** | **Hybrid** | Subagents do the read-only prep (scope lists, build dry-run diffs) in parallel → one approval → serial apply. |
| **Hard dependency chain** (B needs A merged) | **Solo / sequential** | Not parallel-safe. |

Three invariants regardless of mode:
- **Disjoint write targets** is the test for "parallel-safe" — non-overlapping files / issue-tracker record sets / services. If two sessions can touch the same object, they are sequential (or one isolates in a worktree).
- **Implementation Log fragment files**: a parallel (isolated-worktree) session never appends directly to the plan file's `## Implementation Log` section — appending under your own heading is not enough, since two sessions' insertions still land in the same file at the same location and git will conflict on merge even with different headings. Instead, write your entry to a sibling fragment file `<plan-slug>-session-N.implog.md` (same directory as the plan file, same heading + content you'd otherwise append) and commit it on your own branch. Whichever session next merges that branch folds the fragment's content into the plan file's Implementation Log (in session-number order) and deletes the fragment file, as a single-threaded step with no concurrency risk.
- **Completion protocol**: every session — implementation or validation — ends its wrap-up with a report file and a `complete-session.ps1` signal (see the cold-start prompt template below). A session that signals `failed` never lets its dependents auto-start: the gate rule requires every blocker to be `.done`, so a `.failed`/`.aborted` sentinel holds all dependents until a human fixes the problem and re-signals `done`.

Put each session's chosen mode in its `Parallelization` line and in every cold-start prompt.

---

## Output format — `## Session Breakdown` section

Append this template (filled in) to the plan file. Use a verbatim copy-paste-ready cold-start prompt in each session entry so the user can drop it into a fresh chat without thinking.

```markdown
## Session Breakdown

Generated by `/split-plan-into-sessions` on YYYY-MM-DD.

The plan above is large enough to benefit from multi-session execution. Each
session below is self-contained, ends with a green commit, and starts cold
from this plan file. Skim the "Definition of done" for each session before
starting it; the cold-start prompt is what you paste into a fresh chat.

**Cross-session contract:** the plan file is the canonical source of truth.
Update the `Implementation Log` after each session with the commit SHA and a
one-line note. Do not hold context across sessions in your head — read the
log + the code.

**Concurrency matrix.** Which sessions may run at the same time (respecting dependencies). See *Execution mode* above for distinct-sessions vs. subagent fan-out.

| Wave / mode | Sessions | Notes |
|---|---|---|
| Wave 1 ∥ | `<plan-slug>-session-A`, `<plan-slug>-session-B` | disjoint write targets — distinct parallel sessions (cap 2–3) |
| Wave 2 ∥ | `<plan-slug>-session-C` | parallel-safe, but after Wave 1 |
| solo | `<plan-slug>-session-D` → `-E` → … | sequential dependency chain |

### <plan-slug>-session-1 — <name, e.g. "Foundation">

**Recommended model:** <Opus 4.8 / Sonnet 5>
**Estimated wall-clock:** <h>
**Scope:** <one or two sentences>
**Parallelization:** parallel-safe with <sessions | none> · blocked by <sessions | none> · shared write targets <files / ticket-sets | none> · mode <distinct parallel session (Wave N) | subagent fan-out | hybrid | solo/sequential>

**Files to add or modify** (relative to repo root):
- `path/to/file1.py`
- `path/to/file2.py`
- `tests/path/to/test.py`
- ...

**Definition of done:**
1. ...
2. ...
3. ... (every item must be objectively verifiable — a runnable command,
   not a feeling)

**Cold-start prompt** (copy-paste into a fresh chat):

> Read the plan at `<absolute path to plan file>` — especially the <plan-slug>-session-1
> entry under "Session Breakdown" and the Implementation Log section. Read
> the current state of `<root path of the package or repo>`. Then proceed
> with <plan-slug>-session-1 — <name>. Use <Opus 4.8 / Sonnet 5>. Verify the Definition of
> Done positive and negative. End the session with this wrap-up, in order: (1) DoD green,
> positive and negative tests; (2) run `/code-review` on the session diff, fix CONFIRMED
> findings, and flag any SOLID violations in the new code; re-test; (3) auto-commit per the
> `commit-policy` memory (no AI trailer, two-part message) once green, recording the resulting
> commit SHA; (4) write a report to `<state-dir>\reports\<plan-slug>-session-1-report.md`
> covering Status, Commit, Tests run + results, Review outcome (incl. SOLID flags), Issues
> encountered, Consultations, Deferred — then append an Implementation Log entry with the SHA
> and a one-line issues note (recording the SHA is a small follow-up doc commit, since a commit
> can't contain its own SHA); (5) signal completion by running
> `powershell -NoProfile -ExecutionPolicy Bypass -File "<state-dir>\..\scripts\complete-session.ps1"
> -SessionId <plan-slug>-session-1 -Status done -CommitSha <sha> -Summary "<one line, no secrets>"`
> (use `-Status failed` if the session cannot finish); (6) as your very last message, print this exact
> line for the human to run — you cannot invoke slash built-ins yourself: `USER ACTION — type /export
> session-logs/<plan-slug>-session-1-final.txt` (interim snapshots: `-v2`, `-v3`, …). If you get stuck
> after 2 failed attempts on the same problem, hit an architecture-risk fork, or are about to abandon a
> DoD item, consult
> the `oracle` agent (read-only) first and record the consult in the report. Parallel-safety:
> <parallel-safe with <sessions> — run as its own fresh session alongside up to N others, and do
> NOT fan out subagents for approval-gated writes | sequential — verify <prereq> first>.
> <If PARALLEL: write your Implementation Log entry to `<plan-slug>-session-N.implog.md` next to the
> plan file instead of appending directly. If blocked by a PARALLEL session: after merging its branch,
> fold its `<blocker-id>.implog.md` fragment into this plan's Implementation Log and delete it.>
> Do not start <plan-slug>-session-2.

---

### <plan-slug>-session-2 — <name>

(repeat the same structure)

---

(... up to 7 implementation sessions ...)

---

### <plan-slug>-session-<N+1> — Final validation

**Recommended model:** <Opus 4.8 / Fable 5>
**Estimated wall-clock:** <h>
**Scope:** Merge/verify every session branch in dependency order; fold remaining
`*.implog.md` fragments into the Implementation Log; run whole-solution E2E
(positive + negative) from the plan's Verification section; consolidate every
session report into `<plan-slug>-final-report.md`; present the summary.
**Parallelization:** blocked by <every other session id> · mode solo/sequential (shared worktree)

**Files to add or modify** (relative to repo root):
- (merges of the other sessions' branches — no new files of its own beyond the report)
- `<plan-slug>-final-report.md` (new, next to the plan file)

**Definition of done:**
1. Every session branch is merged (or already integrated); no `*.implog.md` fragment remains.
2. Whole-solution E2E passes, both positive and negative cases, per the plan's Verification section.
3. `<plan-slug>-final-report.md` exists with a per-session table (status, commit, tests, review
   findings, issues) plus integrated E2E results and open risks.

**Cold-start prompt** (copy-paste into a fresh chat):

> Read the plan at `<absolute path to plan file>` — the full Implementation Log and every
> `*.implog.md` fragment still present. Confirm every other session is committed. Then proceed
> with <plan-slug>-session-<N+1> — Final validation. Use <Opus 4.8 / Fable 5>. Merge/verify each
> session branch in dependency order (stop and ask on non-trivial conflicts), fold any remaining
> fragments into the Implementation Log and delete them, then run the whole-solution E2E
> (positive and negative) from the plan's Verification section. Consolidate every report from the
> orchestration state dir into `<plan-slug>-final-report.md` next to the plan file. Commit per the
> `commit-policy` memory, then present the user-facing summary. Signal completion via
> `complete-session.ps1 -SessionId <plan-slug>-session-<N+1> -Status done -CommitSha <sha>
> -Summary "<one line>"` — this is the sentinel that fires ALL-DONE (`-Status failed`, listing the
> failing areas, if the E2E does not pass). This is the last session in the plan.

---

## Implementation Log

Append one entry per completed session.

### <plan-slug>-session-1 — <name> — (YYYY-MM-DD)

- Commit: `<sha>`
- Status: complete / in-progress / abandoned
- Files shipped: <count>
- Smoke results: <one or two sentences>
- Decisions made during the session that the plan didn't anticipate: ...
- Deferred to later sessions: ...

(later sessions extend this section the same way)
```

---

## Heuristics for filling in the template

### "Estimated wall-clock"
Use ranges, not point estimates. Express in hours. A session of 500–1,500 LOC including tests typically lands between 2 and 5 hours of focused work; bigger sessions trend toward 6–8.

### "Definition of done"
Every item must be **objectively verifiable**:

- ✅ "`<binary> <subcommand>` returns exit code 0 against the real <service>."
- ✅ "Unit test `tests/.../test_X.py::test_Y` passes."
- ✅ "Zero `grep -r <forbidden-string> <package>/` matches."
- ❌ "Code looks clean." (subjective)
- ❌ "Documentation is good." (subjective)

### "Files to add or modify"
List explicit relative paths. Avoid wildcards. The reader of a future session should be able to predict the diff scope.

### "Cold-start prompt"
The prompt **must**:

- Reference the plan file by **absolute path**, not relative.
- Instruct the agent to read the Implementation Log first.
- Instruct the agent to run the **`/code-review` gate** on its own diff, fix CONFIRMED findings, and flag any SOLID violations in the new code, before committing.
- Instruct the agent to **auto-commit per the `commit-policy` memory** once the Definition of Done is green (no approval gate), then record the resulting SHA in the Implementation Log.
- Instruct the agent to **write a report** to the orchestration state dir's `reports\<plan-slug>-session-N-report.md`, covering Status, Commit, Tests run + results, Review outcome (incl. SOLID flags), Issues encountered, Consultations, Deferred.
- Instruct the agent to **call `complete-session.ps1 -Status done|failed`** as its final wrap-up step — the DAG's dependents stay gated until this fires.
- State the **oracle consult triggers**: stuck after 2 failed attempts on the same problem, an architecture-risk fork, or about to abandon a DoD item — consult the read-only `oracle` agent and record it in the report.
- For a **PARALLEL** (isolated-worktree) session: instruct it to write its Implementation Log entry to the sibling fragment file `<plan-slug>-session-N.implog.md` next to the plan file, not append directly (see *Execution mode*).
- For any session **blocked by** a PARALLEL session: instruct it to fold that session's `<blocker-id>.implog.md` fragment into the plan file's Implementation Log and delete it, immediately after merging that branch.
- Use the session's `<plan-slug>-session-N` identifier and the recommended model.
- State its **parallel-safety + recommended mode** (parallel-safe with which sessions / sequential; distinct parallel session vs. subagent fan-out), and — for approval-gated work — that subagents must **not** be fanned out for the writes.
- End with an explicit "do not start `<plan-slug>-session-(N+1)`" guard (the final validation session's prompt instead states it is the last session in the plan).

---

## Worked example

If the user invokes this on a plan that proposes building a CLI + library for a REST API (foundation + 3 resource domains + polish), the output should look like:

```markdown
## Session Breakdown

Generated by `/split-plan-into-sessions`.

### <plan-slug>-session-1 — Foundation
**Recommended model:** Opus 4.8
**Estimated wall-clock:** 3–4 hours
**Scope:** Auth, HTTP client, logging adapter, error envelope, packaging,
config doctor, redaction security floor test.

**Files to add or modify:**
- `<pkg>/__init__.py` + all subpackage `__init__.py`
- `<pkg>/client/{auth,http,logging,errors}.py`
- `<pkg>/cli/{main,config}.py`
- `<pkg>/output/formatters.py`
- `<pkg>/config/defaults.json`
- `<pkg>/docs/exit-codes.md`
- `setup.cfg`, `pyproject.toml`, `requirements.txt`
- `tests/<pkg>/{test_redaction.py,conftest.py}`

**Definition of done:**
1. `pip install -e .` installs `<binary>` on PATH (or `python -m <pkg>.cli.main` works).
2. `<binary> config show` returns JSON with no token leak; token printed only as fingerprint.
3. `<binary> config doctor` returns 200 from the API's identity endpoint against the real instance.
4. `<binary> --verbose --log-file /tmp/x.log config doctor` produces a log file with `***redacted***` markers and **zero matches** for the live token.
5. `API_TOKEN=garbage <binary> config doctor` exits with code 3 and a structured JSON envelope.
6. `grep -R <forbidden-dep> <pkg>/cli <pkg>/api <pkg>/client` returns empty.

**Cold-start prompt:**
> Read `C:\Users\me\plans\<plan-slug>.md` — especially <plan-slug>-session-1 under
> "Session Breakdown" and any existing "Implementation Log" entries.
> Read the current state of `<repo>/<pkg>/`. Then proceed with <plan-slug>-session-1
> — Foundation. Use Opus 4.8. End by auto-committing per commit-policy once green, then
> appending an Implementation Log entry with the SHA. Do not start <plan-slug>-session-2.

(<plan-slug>-session-2 … -session-5 follow the same structure)
```

---

## Anti-patterns

❌ **Splitting mid-module.** Don't put half of `api/orders.py` in one session and the rest in another. Either keep it whole or split by sub-scope.

❌ **Cross-cutting sessions.** Don't have a "tests session" that touches every product after the fact. Tests go with the code they cover, in the session that adds the code.

❌ **Recommending Haiku.** Sessions are too consequential. Haiku is for inline lookups, not session-scale work.

❌ **Promising specific timings.** Always use ranges. Implementations slip; the cold-start prompt should not pretend otherwise.

❌ **Hidden dependencies.** If Session 3 depends on a decision Session 2 didn't fully nail down, surface that *in the Session 3 cold-start prompt* with a "before starting, verify <thing>" instruction.

❌ **Splitting plans that don't need it.** Apply the threshold rubric honestly. A 1,200-LOC plan in two coupled modules is one session, not two.

❌ **Generating a new plan file.** This skill mutates the existing plan file in place. The plan is the cross-session contract.

❌ **Gating each session behind manual commit approval.** Per the user's `commit-policy` memory, a session **auto-commits** once its Definition of Done is green (positive + negative tests) — no approval gate; mid-session or untested work still asks first. Don't paste raw git commands into the cold-start prompt; the session runs its normal commit flow.

❌ **Fanning out subagents on approval-gated writes.** A subagent can't get the user's per-batch approval — gated work (issue-tracker mutations, outward-facing writes) runs as distinct parallel *sessions*, or the hybrid (subagents prep read-only → human approves once → serial apply). Never let a subagent auto-apply gated writes.

❌ **Parallel sessions clobbering the shared `Implementation Log`.** Appending under your own `### <plan-slug>-session-N` heading is not enough — different headings still land in the same file at the same insertion point and conflict on merge. Parallel sessions write to a sibling `<plan-slug>-session-N.implog.md` fragment file instead; the merging session folds it in and deletes it, single-threaded.

❌ **Declaring sessions parallel-safe without checking write targets.** "Parallel-safe" means disjoint files / ticket sets / services. If two sessions can touch the same object, they're sequential (or one isolates in a worktree).

❌ **Skipping the final validation session.** Rubric 9 is mandatory, not optional — every breakdown ends with a session blocked by all others that merges, runs whole-solution E2E, and consolidates the final report. Don't drop it to save a session slot.

❌ **Ending a session without `complete-session.ps1`.** A session that commits and stops without signaling is invisible to the orchestration layer — every gated dependent stays parked forever. The wrap-up's last step is always the signal call.

❌ **Putting secrets in reports, summaries, or the manifest.** Report files, `-Summary` text, and the manifest are all plain files outside any repo (no git history to purge if something leaks in). Never write a token, credential, or secret-shaped string into any of them.

❌ **PO session polling for progress.** The product-owner console reacts to the user asking "status?" or to a session reporting failure — it never runs its own poll loop or sits in a long wait. That is exactly what the sentinel/gate mechanism exists to make unnecessary.

---

## Interaction with existing commands and skills

- **`/loop`**: do not pair this skill with `/loop`. Sessions are explicitly human-paced — each one ends with a commit decision the user makes.

---

## Output expectations after invocation

1. The plan file now has a `## Session Breakdown` section near the end (above any "Out of Scope" or appendix sections), including the mandatory final validation session.
2. The plan file has an `## Implementation Log` section, possibly empty, ready to be appended to.
3. The chat reply to the user contains:
   - A one-line summary: "Carved the plan into N sessions plus a final validation session (slug `<plan-slug>`), total wall-clock estimate H1–H2 hours."
   - A bullet list: each `<plan-slug>-session-N` identifier + name + recommended model, ending with the validation session.
   - The cold-start prompt for `<plan-slug>-session-1`, quoted so the user can copy-paste it into a new chat.
   - The **concurrency matrix**: which sessions can run in parallel (waves) + the recommended execution mode (distinct parallel sessions vs. subagent fan-out).
   - The ready-to-run `spawn-plan-sessions.ps1 -PlanFile '<absolute plan path>'` command (opens one named Windows Terminal tab per session, each auto-running its cold-start prompt in the current worktree). When the breakdown has parallel waves, append `-PerSessionWorktrees` so each parallel session runs in its own isolated git worktree + branch (`sessions/<plan-slug>-session-N`), and mention that `cleanup-plan-worktrees.ps1` removes the merged ones afterwards. Note that the spawner writes a manifest under `$env:USERPROFILE\.claude\orchestration\<plan-slug>\`, asks the permission-mode question (or takes `-Permissions skip|auto`), and that progress is visible any time via `orchestration-status.ps1 -PlanSlug '<plan-slug>'`.
   - An offer to run the spawn command now, and a note that this chat will then stay open as the **product-owner console** — its first move will be asking the user to run `/model opus[1m]`.
   - A reminder: "Start `<plan-slug>-session-1` in a fresh chat to keep context lean" (or let the spawn command start them all).
4. The Session Breakdown carries a **concurrency matrix** and **every session entry has a `Parallelization` line**, with a parallel-safety sentence in each cold-start prompt. The final validation session's sentinel is the one whose completion fires the ALL-DONE desktop toast.

---

## Notes

- This skill does not write any code. It only edits the plan file.
- This skill does not run any tests. Verification happens inside each session.
- This skill assumes the plan is already approved. If the plan is still being iterated on, defer.
- If the user invokes this skill against a non-existent or empty plan file, refuse with a short message pointing them at the plan-writing flow first.
