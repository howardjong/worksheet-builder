# Muse: expressive-reference fresh end-to-end trial

Branch: `howardjong/worksheet-builder`, `codex/on-demand-composed-worksheets`.
Use the exact commit and tree supplied by Codex, in an isolated worktree.
Keep main untouched. The owner's latest request authorizes **one fresh full
lesson-100 run**, superseding the screen-first ordering in
`approved-reference-consistency.md`. Do not spend on another factorial screen,
model sweep or render-only replay before this run.

## Change and hypothesis

The approved reference library was published at `bbd06aec20663f7678d7c1cff6fed9240be09f00`.
The full renderer now has an opt-in reference selector, rather than leaving these
assets usable only in the experiment runner. Set `WORKSHEET_SCENE_REFERENCE_LIBRARY`
to the committed manifest. It validates owner approval, PNG dimensions and bytes
against hashes, then sends exactly three images in order:

1. The existing original character identity reference, unchanged.
2. Approved expression: happy-open-smile for building; thinking for choices;
   concentrating for other learning procedures.
3. Approved astronaut costume, used for clothing rather than the standing pose.

The generator prompt preserves the original anatomy and drawing style, permits
natural expressions, models only its declared section's action, and keeps the
background sparse. It omits the contradictory large-head/rounded-body theme
instructions and all raw worksheet goals/items. This is a targeted change from
the current procedure prompt, not a promotion of the earlier unsuccessful
structured-prompt arm. The judge still receives **only the original** as its
identity authority. All v5 checks/cutoffs remain unchanged, including identity
>=0.85. Reference approval is not proof of first-pass scene reliability.

Scenes bind the new prompt version and ordered reference hashes into their cache
key. Reports include reference roles/hashes, chosen expression, manifest hash
and judge-reference hash. The exact prompt is saved as `scene_prompt.txt`.
Historical scenes can recompose under their old prompt contract, but cannot
stand in for this trial. All scenes must be generated freshly.

The reference library is character context, not pregenerated lesson artwork.
Scene generation is still on demand. Provider fallback is disabled for this
opt-in reference pack, keeping its image endpoint behavior explicit. Only
individual PNG items go to the model;
large sheets, including the lossless archival WebP sheet, are not model inputs.
This pilot supports the rainbow buddy in the space theme; other combinations
with this library enabled fail rather than silently using incompatible references.

## Offline checks and zero-cost reference preflight

Read AGENTS.md, `.claude/worksheet-project-context.md`, this handoff and
`docs/on-demand-rendering.md`. Verify the supplied commit/tree; install repository
requirements; run `make lint`, `make typecheck`, `make test-all`. Do not merge.

Use a private anonymous grade-2 profile with the **same original character
reference bytes as the previous Muse consistency screen**. Resolve relocated
paths only by copying those exact bytes; compare SHA-256 with the prior artifacts.
Do not replace the judge authority with a generated expression/astronaut item.
If the original cannot be verified, return a blocker before paying for planning.

Before injecting the key or starting planning, validate all three possible
expression supplements and the actual profile's original reference. For example,
run from the checkout with the same profile path as the full run:

```bash
export WORKSHEET_SCENE_REFERENCE_LIBRARY="$PWD/assets/characters/rainbow_learning_buddy/reference_library/v1/manifest.json"
export TRIAL_PROFILE=/private/test-learner.yaml
python - <<'PY'
import hashlib, json, os
from pathlib import Path
from companion.character_identity import resolve_character_identity
from companion.reference_library import approved_supplements
from companion.schema import load_profile
from render.live_scene import judge_reference
from theme.engine import load_theme

profile = load_profile(os.environ['TRIAL_PROFILE'])
theme = load_theme('space')
identity = resolve_character_identity(profile, 'space', character_spec=theme.character_spec)
assert identity.base_character == 'rainbow_roblox'
authority = judge_reference(identity)
assert authority, 'Original identity reference is missing'
manifest = Path(os.environ['WORKSHEET_SCENE_REFERENCE_LIBRARY'])
report = {'original_sha256': hashlib.sha256(authority).hexdigest(),
          'manifest_sha256': hashlib.sha256(manifest.read_bytes()).hexdigest(), 'packs': {}}
for expression in ('happy-open-smile', 'thinking', 'concentrating'):
    face, outfit = approved_supplements(manifest, expression)
    report['packs'][expression] = [hashlib.sha256(raw).hexdigest()
                                  for raw in (authority, face, outfit)]
print(json.dumps(report, indent=2))
PY
```

Save that output privately. Match `original_sha256` to the earlier screen before
proceeding. If any hash/approval/path check fails, fix only the path to the verified
bytes or report the blocker. Do not invent a content approval for this preflight.
The full run below must create and judge a **fresh** content package.

## Budget and vault

Reuse the existing key via your vault's opaque runtime surrogate as
`OPENROUTER_API_KEY`. No key in chat, arguments, files or logs; shell tracing off.
No secret retrieval or new paid calls are required from Howard.

Reconcile the same cumulative **$5 session cap** before this run. The earlier
~$2.01 spent/~$2.99 remaining report included an ambiguous unmeasured screen and
$0.50 reservation. Do not treat a stale remainder as verified or start a new $5
allowance. Retain unknown charges as reservations and keep an external cap.
Set `WORKSHEET_RUN_MAX_USD` to **min($1.50, reconciled remaining)** for this process,
`WORKSHEET_RUN_MAX_CALLS=40`, `WORKSHEET_RUN_DEADLINE_S=300`, and
`WORKSHEET_CALL_CEILINGS_JSON` to verified conservative per-HTTP-attempt USD
ceilings for all configured model IDs. Include the **three generation references**,
original-plus-candidate gate images, input tokens/pixels and maximum output/reasoning
allowances in those ceilings. Transport retry attempts share these limits.
Do not understate ceilings or weaken privacy routing to make the run fit.

Verify current model/endpoint availability and pricing using existing provider
preflight procedures. If the remaining allocation cannot cover the bounded run
at honest ceilings, stop before spending and report the shortfall. In-flight
calls can be billed after a cooperative deadline; reconcile the account afterward.
No automatic whole-run retry, gate bypass or threshold reduction is authorized.

## One fresh full pipeline

Use lesson 100, which Howard already approved and which exists in the fixture.
Use a new empty private output directory with no artwork cache/reuse. Keep the
same anonymous learner/profile authority used in preflight. Configuration:

```bash
export WORKSHEET_OPENROUTER_TEXT_MODELS=openai/gpt-6.1-sol
export WORKSHEET_OPENROUTER_VISION_MODELS=openai/gpt-6.1-sol
export WORKSHEET_OPENROUTER_PLANNER_MODELS=openai/gpt-6.1-sol
export WORKSHEET_OPENROUTER_JUDGE_MODELS=openai/gpt-6.1-sol
export WORKSHEET_OPENROUTER_REVIEW_MODELS=openai/gpt-6.1-sol
export WORKSHEET_OPENROUTER_EXTRACTION_MODELS=openai/gpt-6.1-sol
export WORKSHEET_OPENROUTER_REASONING_EFFORT=medium
export WORKSHEET_SCENE_GATE_BACKEND=decisions
export WORKSHEET_OPENROUTER_SCENE_DECISIONS_MODEL=openai/gpt-6-luna-decisions
export WORKSHEET_OPENROUTER_IMAGE_MODELS=openai/gpt-image-2.5-sunburst
export WORKSHEET_IMAGE_PROVIDERS=openrouter
export WORKSHEET_IMAGE_CONCURRENCY=3
export WORKSHEET_SCENE_MAX_CANDIDATES=1
export WORKSHEET_IMAGE_MAX_ATTEMPTS=1
export WORKSHEET_ALLOW_PDF_FALLBACK=0
export WORKSHEET_PLANNER_V2=1
export WORKSHEET_LLM_ADAPT=1
export WORKSHEET_OBJECTIVE_COVERAGE=1
export WORKSHEET_MAX_WORKSHEETS=auto
export WORKSHEET_USE_RAG=0
export WORKSHEET_RUN_MAX_CALLS=40
export WORKSHEET_RUN_DEADLINE_S=300
export WORKSHEET_OPENROUTER_SCENE_TIMEOUT=90
export WORKSHEET_OPENROUTER_PLANNER_TIMEOUT=90
export WORKSHEET_OPENROUTER_JUDGE_TIMEOUT=60
export WORKSHEET_OPENROUTER_REVIEW_TIMEOUT=45
unset WORKSHEET_SKIP_ASSET_GEN WORKSHEET_SHIP_UNAPPROVED WORKSHEET_PLANNER_SLOT_CONTRACT
# Already set: library manifest, TRIAL_PROFILE, vault surrogate, verified USD allocation/ceilings.
python transform.py --lesson 100 --profile "$TRIAL_PROFILE" --theme space \
  --render-mode hybrid_shell --output /private/expressive-reference-full-lesson-100
```

Measure the real Python process returncode (use pipefail if logging through tee).
Start the wall timer before the transform command and stop after the merged,
validated PDF exists, or after failure. This includes fresh planning and content
judging, artwork, scene gates, layout, validators and merge. Lesson mode has no
photo extraction, so do not call this phone-photo end-to-end latency.

One candidate per scene and one image model deliberately prevent art regeneration
and vendor fallback from masking first-pass yield. Independent scenes may overlap
at concurrency three; transport retry and the designed planner coverage retry
can still occur. Record both separately. A successful PDF after a planner retry
is completion, but not strict full-pipeline first-pass success.

## Evidence and stop conditions

Preserve privately: fresh source/skill/adapted package, planner attempts and
coverage failures, judge verdict and hash-bound approval, frozen package,
`approval_contract.json`, all content/print validators, every scene prompt,
reference role/hash report, candidate PNG/gate, layout report, stage timing,
inference log, limits, account reconciliation, merged PDF and page previews.
No generated trial art, profile or photos committed to GitHub.

Report:

- Exact commit/tree and actual served model/provider IDs (a dated Luna alias is
  acceptable; v5 is the application rubric, not a different model).
- Completion or failure, Python exit status, worksheets/pages, actual wall and
  stage latency, calls, cost, retries and fallbacks. **No PDF means failure.**
- First-candidate passes/total scenes and identity/action/outfit scores, with
  original/hash agreement and one-time art placement checked per scene.
- Strict first-pass success only if all content/scene/PDF checks pass without
  planner retry, transport recovery, regeneration or degradation. Report human
  likeness acceptance separately; an automatic pass is not owner acceptance.
- Display every fresh scene and useful PDF previews: likeness, natural expression,
  task-specific varied actions, exact practice text, numbering/logs, sufficient
  writing space and unclipped layout. Give honest effective PPI/page count.

After failure, preserve the candidates and return their exact blocking evidence.
Do not spend on additional images or lower the quality bar. After success, return
images/PDF for owner review; do not merge or claim a >=95% pass rate from one run.

A new authorized phone photo and physical AirPrint remain separate pending
acceptance tests. If Howard supplies a photo, use the reviewed extraction workflow
in `on-demand-live-validation.md` only within explicitly allocated remaining
budget; do not substitute a synthetic input or spend on a second full run under
this one-run authorization. AirPrint requires the actual phone and printer.
