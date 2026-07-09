---
name: strip-legacy-cruft
description: >-
  Strip legacy and development-history cruft from a codebase to prepare a clean
  pull request — comments that narrate past development phases or superseded
  solutions, postmortem/issue-tracker cross-references, dead code, and
  backward-compatibility shims left over from earlier iterations — while
  preserving the rationale for workarounds that are still load-bearing. Use this
  skill whenever the user wants to clean code up before a PR, remove
  legacy/obsolete/leftover comments, strip "how it used to work" or dev-history
  narration, delete dead code or unused backward-compat aliases, or make a diff
  read present-tense with no references to old approaches — even if they never
  say the word "legacy". Triggers on phrasings like "clean this up for a PR",
  "remove the old comments", "no mentions of past solutions", "strip the dead
  code", "get this ready to ship", or "make the code read like it was always
  this way".
---

# Strip legacy cruft for a clean PR

## What this is for

When code is built up over many iterations, the comments and structure
accumulate an archaeological record: "Phase 2 added this", "FIX-1234 postmortem:
we used to…", a function kept "for backwards-compat" with a version that never
shipped, a workaround whose comment cross-references an internal ticket. That
record is invaluable *during* development and noise *in a pull request*. A
reviewer reading a clean PR should see code that describes what it does **now** —
not a travelogue of how it got here.

This skill removes that archaeology while protecting the one thing inside it
that still matters: the technical reason a piece of non-obvious code exists.
Delete the history; keep the *why* when the why is still true.

The deliverable is edited code plus a verification report proving the sweep was
behavior-neutral and complete. It is not a formatting or refactoring pass —
don't reflow code, rename things, or restructure logic unless the user asks.

## The core idea: present-tense, rationale-preserving

Two questions decide every edit:

1. **Does this text describe the past?** ("used to", "previously", "in v1",
   "Phase 3 added", "FIX-123 postmortem", "kept for backwards-compat") → it's a
   candidate for removal.
2. **If I delete it, does a maintainer lose a reason they still need?** If a
   comment explains why a workaround exists for a bug that is *still present*,
   the reason must survive — reword it to present tense, drop only the
   historical framing and the internal ID.

Most cruft fails (1) and passes (2): delete it. The dangerous case is cruft that
fails (1) but *also* fails (2) — historical framing wrapped around a live
reason. That's the guardrail case: reword, never delete.

## Workflow

Work through these in order. Each stage has a clear exit before the next.

### 1. Scope and reconnaissance

Confirm the target area (a package, a module, a directory, a changeset) and
treat it as a **hard boundary**: clean exactly what the user named and nothing
wider. A cleanup PR earns its keep by being a tight, reviewable diff — quietly
expanding into adjacent files, sibling modules, test code, or docs the user
didn't mention defeats the purpose, *even when those files carry the same
cruft*. If you spot cruft outside the named scope, note it for the user rather
than sweeping it in.

Then survey what's actually there before proposing anything — grep the target
for the marker vocabulary so you're reasoning about real hits, not guesses:

- **Phase/version narration**: `Session`, `Phase`, `Step N`, `Milestone`, `v1`/`v2`,
  `iteration`, `initially`, `originally`.
- **History framing**: `used to`, `previously`, `no longer`, `formerly`,
  `deprecated`, `legacy`, `obsolete`, `historic`, `kept for`, `for now`.
- **Tracker/postmortem refs in comments**: issue keys (`ABC-1234`,
  `#456`, `GH-789`), `postmortem`, `retro`, `RCA`, dated notes (`(2026-05-19)`),
  internal bug-catalogue IDs.
- **Dead-code smells**: `unused`, `not used`, `kept for symmetry`, large
  commented-out blocks, `TODO/FIXME/XXX/HACK` that describe abandoned paths.
- **Stale references**: retired file names, old project/tool names, "renamed
  from", "replaces X".

Note the size (file count, rough hit count). This tells you whether to sweep
inline (a handful of files) or partition and parallelize (dozens).

### 2. Classify the cruft

Sort every hit into one of these categories. The category determines the action.

| Category | What it looks like | Action |
|---|---|---|
| **Dev-phase narration** | "Phase 2 added the writers", "Scope of Session 3:", "initially we shipped read-only" | Rewrite to present tense describing what the code does now. Delete the phase reference. |
| **Postmortem / tracker refs** | "FIX-123 (postmortem 2026-05-19): the validator used to…" | Strip the ID + date + "used to". **Keep** the present-tense rationale if it explains current behavior; delete the comment if it's pure pointer. |
| **Live-workaround comments** | "See BUG-42: server returns 404 on /foo, so we call /bar" — and the server still does | **Code stays untouched.** Reword the comment: keep the technical reason, drop the internal ID and any "previously-implemented X no longer works" history. |
| **Dead code** | unused functions/methods, unreachable branches, commented-out blocks, backward-compat aliases for already-migrated or never-shipped paths | Delete — *after* confirming zero callers (see guardrail). |
| **Stale references** | "drop-in replacement for old-config.json", "renamed from oldtool" | Remove the historical framing; keep the present fact. |
| **User-facing text** | README/docs/help-strings/data files that narrate history | In scope only if the user opted in. Rewrite to terse present tense. |

When rewriting a comment, explain the present reason as if writing it fresh:
state what the code does and the external fact that motivates it (the server
behavior, the Click quirk, the data shape), with no reference to the journey
that discovered it.

### 3. Decide scope with the user

A few choices genuinely change the deliverable and are the user's to make.
Surface them explicitly rather than guessing — getting these wrong means either
an incomplete sweep or an unwanted behavior change:

- **Comment-only vs behavioral removal.** Stripping comments is safe. Removing a
  backward-compat **alias or command** changes the public surface and may touch
  tests and docs. Ask before removing anything callable.
- **Test files: out by default.** Test comments often carry the same narration,
  but tests are a separate concern from the production code under review. Leave
  them untouched unless the user names them or explicitly opts in — don't widen
  the diff into `tests/` on your own initiative.
- **User-facing docs/data in or out.** README, help text, and data files are
  more sensitive than internal comments.
- **Default for tracker IDs:** drop the internal ID and date, **preserve the
  technical rationale.** Confirm if the team treats IDs as live traceability.

### 4. Guardrail — what NOT to touch

Over-deletion is the failure mode that bites later, so hold these lines:

- **Never delete a load-bearing reason.** If a comment justifies a workaround for
  a bug/limitation that is *still real*, reword it — don't drop it. A maintainer
  who can't see why the workaround exists will "simplify" it and reintroduce the
  failure. When unsure whether a reason is still live, keep it (reworded).
- **A marker word inside a runtime string is not cruft.** `raise Error("token no
  longer valid")` or a help string or a data value that literally contains
  "previously" is functional text. Only edit comments, docstrings, and (when in
  scope) dead code — never strings the program emits.
- **Leave functional identifiers alone.** Test catalogues, fixtures, or rule
  tables that *use* an ID as a key/name are not narration. Confirm a "legacy"
  construct is truly dead before removing it.
- **Stay inside the named scope.** Don't edit files, directories, or layers the
  user didn't ask about — tests, sibling modules, docs — just because they
  contain the same markers. Finding cruft somewhere is not a license to edit it;
  a wider blast radius is a harder review.
- **Don't touch generated or vendored artifacts** (build output, mirrors,
  lockfiles, `dist/`, `node_modules/`). Edit the source of truth only.
- **Confirm zero callers before deleting code.** Grep the whole repo (excluding
  build mirrors) for references. If a caller exists, it's not dead — stop and
  report.

### 5. Execute the sweep

Apply the category actions. For a handful of files, edit inline. For a large
sweep (dozens of files), partition into **disjoint file groups** and process
them in parallel — disjoint sets mean no edit conflicts. Whatever the size, two
rules keep edits safe:

- **Edit comments/docstrings only**, unless the agreed scope includes behavioral
  removal. Don't touch logic, signatures, or emitted strings.
- **Compile/parse each file after editing it.** Multi-line docstring rewrites are
  the most common way to introduce an unbalanced quote or broken indent — catch
  it immediately, per file, not at the end.

### 6. Verification gate — the definition of done

A clean PR is only clean if you can prove the sweep was complete and
behavior-neutral. Run every check that applies to the stack:

1. **Compile/parse** every touched file (e.g. `python -m py_compile`, `tsc
   --noEmit`, a JSON/YAML/TOML parse for data files).
2. **Smoke import / build** the package or entry points so a syntax error in an
   untouched-by-tests path still surfaces.
3. **Zero-marker re-grep.** Re-run the marker grep across the target, excluding
   out-of-scope paths (tests if excluded, build mirrors, functional
   catalogues). Expect zero *hard* markers (phase refs, tracker IDs,
   "used to"). Review any residual *soft* markers (a "no longer" in a runtime
   string) and justify each one you keep.
4. **Dead-code confirmation.** Re-grep for callers of anything you deleted →
   zero.
5. **Behavioral preservation.** Confirm anything you intentionally kept (aliases,
   commands) is still present and wired.
6. **Test suite green.** Run the full relevant suite. Comment-only edits should
   not change a single result; a failure means you touched something you
   shouldn't have.
7. **Diff hygiene.** `git diff --stat` shows only the intended files — no scratch
   files, build artifacts, or out-of-scope paths swept in.

Report the result of each check. "Done" is all checks passing, not "the edits
are made".

### 7. Commit cleanly

When the user approves a commit:

- **Stage only the intended changes.** Prefer staging tracked modifications by
  path (e.g. `git add -u <target>`) so untracked scratch/build files are never
  swept in. Verify the staged set before committing.
- **Match the repo's commit convention** (ticket prefix, message style). Describe
  what was removed by category, and state explicitly that behavior is unchanged
  and the suite is green.
- **Don't push or open the PR without explicit approval** — those are
  outward-facing.

## Anti-patterns

- **Deleting the reason with the history.** "We call /bar because /foo 404s
  (BUG-42)" → deleting the whole line because it names a bug. Keep "/foo 404s on
  this server, so we call /bar".
- **Editing runtime strings.** Changing a log/error/help string because it
  contains "previously". That's a behavior change.
- **Scope creep into refactoring.** Renaming, reflowing, or "improving" code
  while you're in there. A cleanup PR that also refactors is hard to review —
  the opposite of the goal.
- **Scope creep into adjacent files.** Sweeping `tests/`, sibling modules, or
  docs the user didn't name because they happen to contain the same markers.
  Same cruft elsewhere is not a license to edit it — clean what was asked for.
- **Declaring done at "edits made".** Skipping the grep/compile/test gate. The
  gate is what makes the PR trustworthy.
- **Silent over-broad staging.** `git add -A` pulling in build artifacts or
  unrelated files.

## A worked shape (illustrative)

A real sweep of a CLI package looked like: survey found ~95 marker hits across
~30 files in four shapes — phase markers ("Session N"), postmortem refs ("F-001
(postmortem …)"), internal bug IDs on live server-bug workarounds, and one dead
method. Scope decision: keep two backward-compat aliases (comment-only), exclude
tests, include README. The bug-ID workaround comments were the guardrail case —
the 404/405/500 server bugs were still live, so the comments were reworded to
state the server behavior with the IDs dropped, code untouched. The gate:
per-file compile, package-wide zero-marker grep, dead-method caller check, full
suite (stayed green), and a diff-stat confirming only the intended files
changed. Net effect: a smaller, present-tense diff a reviewer can read without
decoding the project's history.
