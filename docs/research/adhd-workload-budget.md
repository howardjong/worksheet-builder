# ADHD Workload Budget — evidence base for `adapt/workload.py`

Owner policy (2026-07-07): the lesson's learning objectives must be met first,
at the expense of more pages — but bounded by what the evidence says an ADHD
child of this age can sustain in one sitting. This document records the
evidence behind the per-grade numbers in `GRADE_WORKLOAD` and the shape of the
budget model (short segments + movement breaks, capped session).

## What the model encodes

1. **One mini-worksheet = one continuous seatwork segment.** Segment length is
   set at or below the LOW end of the assigned-task attention range for
   typically developing children of that age, to absorb the ADHD discount.
2. **A session = a few segments with movement breaks between them.** Breaks
   measurably restore on-task behavior, so several short segments beat one
   long sitting — but fatigue still accumulates, so the session total is
   capped too.
3. **Objectives drive the count up to the ceiling, never past it.** When
   objective demand exceeds the attention ceiling, the package is capped and
   the overflow flagged (`objectives_overflow`) — the remainder belongs to a
   second sitting, not a longer one.
4. **Observed child data beats the population table.** When the profile's
   `operational_signals.avg_session_duration` is present, the session budget
   never exceeds it. A "small" chunking accommodation drops one segment.

## The numbers

| Grade | Segment (min) | Session (min) | Ceiling (sheets) |
|-------|---------------|---------------|------------------|
| K     | 5             | 12            | 2                |
| 1     | 6             | 18            | 3                |
| 2     | 8             | 24            | 3                |
| 3     | 10            | 30            | 3                |

These are a policy encoding informed by the sources below — deliberately
conservative, not measurements from any single study. Revisit when real
completion data accumulates in profiles (`operational_signals`).

## Evidence

**Peer-reviewed (retrieved via PubMed):**

- Imeraj L, Antrop I, Sonuga-Barke E, et al. *The impact of instructional
  context on classroom on-task behavior: a matched comparison of children with
  ADHD and non-ADHD classmates.* J Sch Psychol. 2013;51(4):487-98.
  [DOI: 10.1016/j.jsp.2013.05.004](https://doi.org/10.1016/j.jsp.2013.05.004)
  — Children with ADHD (ages 6-12, off medication) showed significantly
  shorter on-task spans during academic tasks and individual seatwork than
  matched classmates, despite receiving more teacher supervision (~75% vs 88%
  on-task time). Basis for discounting assigned-task attention norms and for
  preferring short, structured segments.
- School-based active-break trials (e.g., PubMed PMIDs 41246058, 38259740,
  35784522, 33719112) consistently report improved on-task classroom behavior
  immediately following brief physical-activity breaks in primary
  schoolchildren. Basis for the segments-with-movement-breaks session shape
  (the pipeline's brain-break prompts between mini-worksheets).

**Practice guidance:**

- CDC, *ADHD in the Classroom* (cdc.gov/adhd/treatment/classroom.html) —
  shortened assignments and breaking long work into smaller parts are
  first-line documented accommodations; movement breaks help students stay on
  task during longer work.
- CHADD, *Assignment Accommodations* (chadd.org/for-educators/assignment-accomodations/)
  — decreasing assignment length is among the most common effective
  accommodations.

**Developmental attention norms (assigned-task):**

- Widely used developmental guidance puts a single ASSIGNED task at roughly
  "minutes ≈ age" (5 minutes for a 5-year-old), with self-chosen-activity
  spans of ~2-3 minutes per year of age and classroom expectations of
  ~10-18 minutes by kindergarten-grade 1 and ~16-27 minutes by grade 3
  (e.g., brainbalancecenters.com "Normal Attention Span Expectations By Age";
  first-grader in-class observation studies). These anchor the
  typically-developing baseline that the ADHD discount is applied to.

## Known limitations / future work

- The school-psychology literature on task-length manipulation is thinly
  indexed in PubMed; the per-grade minutes would benefit from a proper
  citation pass through ERIC/PsycINFO.
- The best data will be the owner's own: per-child completion logs
  (`operational_signals`) should progressively replace the population table —
  the override hook already exists.
