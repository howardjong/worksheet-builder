---
description: Update the running context doc for session handoff to another agent or future session
---

You are preparing a session handoff for the worksheet-builder project.

Read the current context document at `.claude/worksheet-project-context.md` and the implementation plan at `worksheet-builder-consolidated-plan.md`.

Then update `.claude/worksheet-project-context.md` with:

1. **Current State** section:
   - Update the milestone progress table with current checkpoint statuses
   - Update "What Exists Now" with any new files or modules created
   - Update "What's Next" with the specific next checkpoint and concrete next steps

2. **Session Log** — append a new entry at the bottom:
   ```
   ### Session N — [today's date]
   **Participants:** [who worked]
   **What happened:**
   - [bullet list of what was accomplished]
   - [any key decisions made]
   - [any gotchas discovered]
   **What's next:** [specific next checkpoint and first steps]
   ```

3. **Gotchas Discovered** — add any new issues found during this session

4. **Open Questions** — add any new questions, update status of resolved ones

5. **Key Decisions Log** — add any new architectural or design decisions made

Additional context from this session: $ARGUMENTS

After updating, show a brief summary of what changed in the context doc.
