---
description: Show current project status — milestones, checkpoints, what's next, and open questions
---

You are providing a project status briefing for the worksheet-builder project.

Read `.claude/worksheet-project-context.md` and the codebase, then produce a concise status report:

1. **Milestone Progress** — show the milestone table with current checkpoint statuses

2. **What's Working** — list pipeline stages that are implemented and passing tests

3. **What's Next** — the specific next checkpoint with its acceptance criteria

4. **Open Questions** — any unresolved questions from the context doc

5. **Recent Gotchas** — any issues discovered that affect upcoming work

6. **Test Health** — run `make test` and report results (pass/fail/skip counts)

Keep the output concise and actionable — this is a briefing, not a deep dive.

$ARGUMENTS
