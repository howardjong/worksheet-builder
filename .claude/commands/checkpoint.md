---
description: Validate current checkpoint completion against acceptance criteria from the plan
argument-hint: "[checkpoint number, e.g. 1.2]"
---

You are validating whether a checkpoint in the worksheet-builder implementation plan has been completed.

Target checkpoint: $ARGUMENTS

Instructions:

1. Read `worksheet-builder-consolidated-plan.md` and find the checkpoint section for "$ARGUMENTS".
2. Extract all acceptance criteria (the `- [ ]` checklist items).
3. For each criterion, investigate the codebase to determine if it is met:
   - Read the relevant source files
   - Run the relevant tests if they exist (`make test` or specific pytest commands)
   - Check that the described behavior actually works
4. Produce a report:

   ```
   ## Checkpoint $ARGUMENTS Validation Report

   ### Status: [PASS / PARTIAL / FAIL]

   | # | Criterion | Status | Evidence |
   |---|-----------|--------|----------|
   | 1 | [criterion text] | PASS/FAIL | [file or test that proves it] |
   | ...
   ```

5. If any criteria fail:
   - List exactly what's missing
   - Suggest the minimal work needed to close each gap
6. If all criteria pass:
   - Confirm the checkpoint is complete
   - State what the next checkpoint is

Do not make changes — this is a read-only validation.
