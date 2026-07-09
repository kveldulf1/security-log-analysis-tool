# Git Safety Rules

## Repository integrity
- NEVER reinitialize (`git init`) an existing repo, delete `.git`, or recreate a repo to fix auth. Fix remote/auth by updating URLs/credentials only (`git remote set-url` — never remove/add; verify with `git remote -v`).

## Before any git operation
Check: `git --no-pager branch --list`, `git status --porcelain`, `git stash list`, `git branch --show-current`. Note recovery steps.

## Avoid paging (Windows console)
Use `--no-pager` and limited output (`--oneline`, `-n N`, `--porcelain`). Risky if unbounded: `git branch`, `git log`, `git diff`. If a command hangs or shows PSReadLine/display errors, STOP, retry with `--no-pager`/shorter output, and verify state with a simple status command. After a shell reset, `cd` back to the project dir.

## Destructive actions — confirm first
- NEVER force push or use `-f`/`--force` without explicit confirmation.
- Show the command, wait for confirmation, provide rollback instructions.
- Before checkouts: check for uncommitted changes; `git stash` to preserve work; check for unpushed commits before any branch operation.
- Create a backup branch before risky operations; rename with `git branch -m`; preserve all local branches.

## Error recovery
STOP on anything unexpected → check reflog → IDE backups → local filesystem copies → document attempted steps.

## Protect
`.git/`, `.env`, local branches, uncommitted changes, stashed changes.
