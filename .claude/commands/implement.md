---
description: Implement a specific checkpoint from the plan with full context
argument-hint: "[checkpoint number, e.g. 1.2]"
---

You are implementing a checkpoint from the worksheet-builder implementation plan.

Target checkpoint: $ARGUMENTS

Before writing any code:

1. **Read the plan:** Open `worksheet-builder-consolidated-plan.md` and find checkpoint "$ARGUMENTS". Read the full checkpoint section including goal, implementation details, files list, and acceptance criteria.

2. **Read the context:** Open `.claude/worksheet-project-context.md` to understand current state, prior decisions, and any gotchas.

3. **Read the project guidance:** The `CLAUDE.md` file has conventions, module layout, and command reference.

4. **Check dependencies:** Read any prerequisite modules that this checkpoint depends on. Don't duplicate existing code.

Then implement:

5. **Create/modify files** as specified in the checkpoint. Follow these conventions:
   - Python 3.11+, type hints everywhere
   - Pydantic v2 for all data contracts
   - Google-style docstrings for public functions
   - Use `click` for any CLI entry points
   - Use `ruff` formatting style
   - Keep functions focused and testable

6. **Write tests** for the new code in `tests/test_<module>.py`. Follow patterns from `/gen-tests` command.

7. **Verify:** Run `make lint && make typecheck && make test` to confirm everything passes.

8. **Update context:** After implementation, update `.claude/worksheet-project-context.md` with:
   - Checkpoint status change
   - Any decisions made during implementation
   - Any gotchas discovered
   - What's next

Do NOT implement beyond the scope of the specified checkpoint. Stay focused.
