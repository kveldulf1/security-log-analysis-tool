# Development Workflow

The standard loop for any non-trivial change. Follow it end to end; don't skip stages.

## 1. Plan first (plan mode)

Before writing code, produce a plan: the problem, the approach, the files to change, and a
**Verification** section. For large plans, carve them with `/split-plan-into-sessions`. Get the plan
approved before implementing.

**Name the plan file meaningfully.** Plan mode assigns a random slug (e.g.
`so-do-i-need-velvety-milner.md`) — that is not acceptable. A plan file gets a descriptive,
subject-based kebab-case name (e.g. `log-parser-master-plan.md`, `auth-token-refresh-plan.md`). Plan
mode only lets you edit the assigned file, so the moment you exit plan mode, rename it to a meaningful
name and update any references to it. Randomness in plan names is unacceptable.

## 2. Implement with the agentic test loop

Write positive AND negative tests alongside the code. Then run autonomously: run tests -> if any fail,
fix -> run again -> repeat, until all pass. Stop and ask only when something proves impossible or needs
a trade-off decision. Anything not testable agentically (interactive prompts, GUI, terminal spawning)
gets a written manual test procedure, provided proactively. (See memory `plans-include-agentic-tests`.)

## 3. Clean up before the PR

Run `/strip-legacy-cruft` to remove dev-history comments, dead code, and superseded-approach narration
so the diff reads present-tense. Then auto-commit (no AI co-author trailer; two-part message — see
memory `commit-policy`).
