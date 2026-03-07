# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## Project Overview

**Worksheet Builder** is a skill-preserving worksheet adaptation engine for children ages 5-8 with ADHD. It transforms physical paper literacy worksheets into ADHD-optimized, themed, print-ready activities with progressive avatar engagement.

**Repository:** `https://github.com/howardjong/worksheet-builder.git`

**Full implementation plan:** `worksheet-builder-consolidated-plan.md`

**Running context doc:** `.claude/worksheet-project-context.md` — READ THIS FIRST for current state, decisions, and handoff notes.

## Commands

### Setup
```bash
git clone https://github.com/howardjong/worksheet-builder.git
cd worksheet-builder
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### Development
```bash
make lint        # ruff check .
make typecheck   # mypy .
make test        # pytest tests/ -v (unit tests)
make test-golden # pytest tests/test_e2e.py -v (golden E2E, no network)
make test-all    # pytest tests/ -v (all tests)
make format      # ruff format .
make clean       # rm -rf artifacts/ __pycache__ .mypy_cache
```

### CLI Usage
```bash
# Transform a worksheet
python transform.py --input photo.jpg --profile profiles/ian.yaml --theme space --output ./output/

# Mark completion and award tokens
python complete.py --profile profiles/ian.yaml --lesson 5

# Preview before print
python transform.py --input photo.jpg --profile profiles/ian.yaml --theme space --preview
```

## Architecture

### Pipeline (8 stages, deterministic core)
```
Paper → Capture → Normalize → Source Extract → Skill Model → ADHD Adapt → Theme → Render → Validate
```

- **Stages 1-3:** Physical paper → preprocessed image → OCR → SourceWorksheetModel
- **Stage 4:** SourceWorksheetModel → LiteracySkillModel (what skill is taught)
- **Stage 5:** LiteracySkillModel + LearnerProfile → AdaptedActivityModel (ADHD-optimized)
- **Stage 6:** Apply calm theme tokens + avatar companion
- **Stage 7:** Vector-first PDF via ReportLab
- **Stage 8:** Skill-parity + age-band + print + ADHD compliance validation

### Key Design Constraints
- **Deterministic core:** pipeline works without any API calls. AI is optional assist only.
- **Skill-preserving, not page-faithful:** output may differ significantly from source in layout/wording, but must preserve the literacy skill.
- **ADHD-safe:** calm themes, limited decorative elements, chunked content, predictable rewards, no loot boxes/streak punishment/leaderboards.
- **Print-first:** primary output is printed paper worksheets. Digital companion is secondary.

### Data Contracts (Pydantic models)
All pipeline stages communicate through strict schemas:
- `SourceWorksheetModel` — what's on the page (OCR output)
- `LiteracySkillModel` — what skill is being taught
- `AdaptedActivityModel` — ADHD-optimized activity chunks
- `LearnerProfile` — child preferences, accommodations, avatar, progress
- `RewardEventModel` — token awards and unlocks

### Module Layout
```
capture/     — image preprocessing + master storage
extract/     — OCR + heuristics + AI assist adapter
skill/       — literacy skill taxonomy + extraction
adapt/       — ADHD activity adaptation + accommodation rules
theme/       — calm theme engine + curated assets
companion/   — learner profile, avatar, rewards, caregiver controls
render/      — ReportLab PDF + preview
validate/    — skill-parity, print quality, ADHD compliance
```

## Conventions

- **Python 3.11+**, type hints everywhere, Pydantic for all data contracts
- **Linting:** ruff. **Type checking:** mypy (strict). **Testing:** pytest.
- **No AI in critical path** — AI assist is always behind `extract/adapter.py` interface and optional
- **All model outputs must validate against Pydantic schemas** before influencing the pipeline
- **Idempotent:** same inputs → same outputs. Keyed by `hash(image) + profile + theme + pipeline_version`
- **Persist all intermediate artifacts** in `artifacts/` for debugging
- **Master images** stored permanently in `masters/` for reprocessing
- **Profiles** stored as YAML in `profiles/`
- **Curated theme assets** committed to repo; generated assets cached in `asset_cache/` (gitignored)

## Operating Conventions

### Commands and Skills
- **Commands** (`.claude/commands/`) define **what to do** — user invokes them via `/slash-command`
- **Skills** (`.claude/skills/`) define **how to do it well** — auto-loaded when task context matches
- **Before executing any command or implementation task:** identify which skills apply and load them. The skills encode domain rules (ADHD design, data contracts, skill preservation, print quality, avatar rewards, pipeline stages) that must influence the work.

### Parallelization Rules
Use sub-agents for parallel work **when safe:**
- Tasks modify different files/modules
- Tasks don't share mutable state
- Tasks are logically independent (e.g., `capture/` and `skill/taxonomy.py`)

Do NOT parallelize when:
- Tasks modify the same module
- Tasks require sequential reasoning (e.g., schema design before implementation)
- Architecture changes need coordination across modules

### Implementation Protocol
For each checkpoint or non-trivial task:
1. Read the plan and context doc for current state
2. Identify which skills apply (check `.claude/skills/`)
3. Decompose into independent sub-tasks if possible
4. Implement (parallelize independent sub-tasks via sub-agents)
5. Validate after implementation: run tests, check contracts, verify ADHD compliance
6. Update context doc with results

### Continuous Improvement
When repeated patterns emerge during implementation, propose:
- New commands for repeatable workflows
- New skills for domain knowledge that should auto-activate
- Updates to existing skills when rules prove incomplete

## Session Handoff Protocol

When ending a session or handing off to another agent:
1. Run `/handoff` or manually update `.claude/worksheet-project-context.md` with:
   - Current milestone/checkpoint status
   - What was completed this session
   - What's next (with specific files/functions)
   - Any decisions made or open questions
   - Any gotchas discovered
2. Commit the context update if other changes are being committed
