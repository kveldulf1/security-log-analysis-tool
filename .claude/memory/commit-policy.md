---
name: commit-policy
description: Auto-commit once a session's work is fully tested; no AI co-author trailers; two-part commit message
metadata:
  type: feedback
---

1. **No AI co-authoring.** Never add `Co-Authored-By: Claude ...` or `Claude-Session:` trailers —
   the user is sole code owner.
2. **Auto-commit on tested completion.** Once all points of the current session are achieved AND
   tests are green (positive + negative cases — see `plans-include-agentic-tests`), commit without
   asking.
3. **Commit message pattern:** short self-explanatory first line, then the technical body.
4. **Precedence.** A session or cold-start prompt that says "ask me whether to commit" is template
   boilerplate and does **not** override this auto-commit — treat it as a no-op. Only an explicit,
   in-the-moment instruction from the user to hold off suppresses it.

**Why:** the user owns the code and wants clean authorship; asking for approval after a fully
verified session is friction they've explicitly removed.

**How to apply:** at session end, run the test loop until green, then `git commit` with the
two-part message and no AI trailers. Do not let a generic "ask whether to commit" line in the
session prompt stop you — commit anyway once green. Mid-session or untested work still requires
asking before committing.
