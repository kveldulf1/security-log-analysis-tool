# security-log-analysis-tool — Claude Code Configuration

## Project overview

<!-- TODO: one paragraph describing what security-log-analysis-tool does. -->

## Stack & conventions

- **Python 3.11+**, `src/` layout (`src/<package>/`, tests in `tests/`).
- **CLI** via `argparse` (or `click` if subcommands grow); a single entry point.
- **Typing**: full type hints; prefer `dataclasses` for models.
- **Lint & format**: enforced by a git pre-commit gate (ruff via pre-commit). Auto-fix before committing: `ruff check --fix . && ruff format .`.
- **Packaging**: `pyproject.toml`; installable with `pip install -e .`.
- **Structure**: keep separable concerns in separate, unit-testable modules.
- **No secrets in code or logs**; redact tokens/PII in diagnostic output.

## Testing

- `pytest -q`. Aim for meaningful coverage on core logic (table-driven tests).
- Every bug fix ships with a regression test.

## AI tooling (committed skills)

This repo ships a few personal Claude Code skills to aid development:

- **`/strip-legacy-cruft`** — strip dev-history comments, dead code, and superseded-approach narration to
  make a diff read present-tense before a PR.
- **`/split-plan-into-sessions`** — carve a large plan into focused, per-PR sessions; on Windows it can
  launch one named terminal tab per session (`.claude/scripts/spawn-*.ps1`), optionally each in its own
  isolated git worktree for safe parallel execution, with `cleanup-plan-worktrees.ps1` to tear them down
  afterwards. Launcher is Windows/PowerShell-only; the planning logic is cross-platform. Spawned
  sessions self-gate on completion sentinels (no manual Enter to unblock a dependent) and signal via
  `complete-session.ps1`; check progress with `orchestration-status.ps1`. See `.claude/scripts/README.md`.

## Working conventions

- Auto-commit once a session's work is fully tested and green — no AI co-author trailer, two-part
  message (see memory `commit-policy`). Mid-session or untested work still requires asking first.
- Keep changes small and reviewable; prefer one concern per commit.

## Standing rules

@rules/git-safety.md
@rules/dev-workflow.md
@rules/secrets-hygiene.md

## Memory

Durable working notes, loaded into context at session start (same `@import` mechanism as the rules above):

@memory/commit-policy.md
@memory/plans-include-agentic-tests.md
@memory/orchestrated-session-protocol.md
@memory/project-conventions.md

See `.claude/memory/MEMORY.md` for the human-readable index. When you add a memory, add both its
`MEMORY.md` index line and an `@memory/<file>.md` import here so it loads eagerly.

## Browser automation (playwright-cli)

This project uses browser automation via the Playwright CLI. Install once per machine:

- `npm install -g @playwright/cli`
- `playwright-cli install --skills`
- `playwright-cli install-browser`

The `playwright-test-*` agents and `/explore-app` drive it. `install --skills` regenerates the
`playwright-cli` skill; it is not committed here.
