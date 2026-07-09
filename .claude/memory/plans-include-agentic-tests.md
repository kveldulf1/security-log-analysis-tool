---
name: plans-include-agentic-tests
description: Every implementation plan ships with positive + negative agentic tests and a run→fix→re-run loop; non-agentic items get a full manual test procedure
metadata:
  type: feedback
---

Every implementation plan must include **agentic tests** covering both **positive and negative cases**, plus an execution contract for the implementing agent:

1. If running the tests needs input (sample data, environment choice), ask for it explicitly.
2. Otherwise run autonomously: run tests → if any fail, apply fixes → run again → repeat.
3. Exit only when all tests pass, then report the work as complete.
4. Even inside the loop, stop and ask when something proves impossible or a trade-off decision is required — never silently pick a trade-off.
5. Anything **not testable agentically** (interactive prompts, GUI / terminal-tab spawning, anything needing human visual inspection) is handed over as an explicit **manual test procedure** — copy-pasteable setup + run commands, what to observe, expected result, and cleanup. Provide it proactively at completion, not on request.

**Why:** A plan shouldn't end at "code written" — verification with happy-path and failure-path coverage is part of the deliverable, and the agent should self-heal failures rather than hand back a broken state. For the parts an agent can't drive, a runnable checklist lets the human close the loop.

**How to apply:** Every plan gets a Verification section listing positive and negative cases and stating the run→fix→re-run loop as the completion criterion. For each "not agentically testable" item, write the full manual procedure (commands + expected output), not a one-line note.
