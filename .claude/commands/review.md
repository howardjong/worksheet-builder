---
description: Code review with worksheet-builder project context (ADHD rules, data contracts, determinism)
argument-hint: "[file or module path, or 'staged' for git staged changes]"
---

You are performing a code review for the worksheet-builder project.

Target: $ARGUMENTS

Read `CLAUDE.md` for project conventions, then review the code with these project-specific concerns:

**1. Correctness & Bugs**
- Logic errors, off-by-one, missing edge cases
- Pydantic model field mismatches between producer and consumer
- Missing validation or confidence gating

**2. Data Contract Compliance**
- All pipeline stage inputs/outputs use the defined Pydantic models
- No raw dicts or untyped data crossing stage boundaries
- Schema validation present at each boundary

**3. Determinism**
- No `random`, `uuid`, `datetime.now()`, or network calls in the critical path
- Same inputs always produce same outputs
- All non-deterministic operations isolated behind the AI adapter interface

**4. ADHD Design Rules (if rendering/adaptation code)**
- Chunking respects grade-level limits
- Instructions are numbered with bold action verbs
- Decorative elements limited to 1-2 per page
- No anti-patterns (dense text, noisy backgrounds, streak punishment, etc.)

**5. Skill Preservation (if adaptation code)**
- Target words preserved through adaptation
- Response format substitutions are skill-aware
- Grade-level/age-band appropriate

**6. Code Quality**
- Type hints on all public functions
- Reasonable error handling (fail gracefully with clear messages)
- No over-engineering beyond the current checkpoint scope
- Tests exist for new functionality

Produce a structured review:
```
## Code Review: [target]

### Verdict: [APPROVE / REQUEST CHANGES]

**Critical Issues:** [count]
**Important Issues:** [count]
**Minor Issues:** [count]

### Issues
| # | Severity | File:Line | Issue | Suggestion |
|---|----------|-----------|-------|------------|
| 1 | Critical | ... | ... | ... |
```
