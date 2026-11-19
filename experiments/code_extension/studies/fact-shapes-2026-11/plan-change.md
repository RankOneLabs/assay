# fact-shapes-2026-11: plan change

Filed 2026-11-15, before any run of this study. The cell table must be written
and reviewed before the base service is built.

The tasks change because GPT-6.1 Sol reached the ceiling: it passed **57 of 57**
submitted attempts in the matched-task study (57 submitted of 60 dispatched;
[results](../matched-tasks-2026-11/results.md)) and **11 of 11** in the code
extension library's one-attempt-per-task calibration, including a 2-task recheck
([study plan](../scenario-library/study-plan.md)). Those task sets cannot rank
shapes.

The three changes are:

1. **intent-only** task text: no keys, files or classes are named.
2. **per-fact** scoring: one hidden test group per required fact.
3. **rename-only restructuring**: every restructuring task renames an existing
   stage, evidence kind or route permission.

The pilot's third-fact trigger is fixed in advance: if Sol misses
at most 1 of its 10 non-control manipulated facts in the pilot, a third required
fact is added through a further written plan change before the full run.
The pilot has 12 Sol attempts, 2 per shape; the 2 type_enforced control attempts
are excluded from these 10 manipulated facts.

The reviewed cell table is rendered from the single typed source
`code_extension/fact_shapes/cells.py`. Later base-fixture, generator, scoring and
tally cohorts import that source and never re-declare the table.

## Second change: independent holders (2026-11-18, after the first pilot)

### What the pilot showed

The first pilot ran stage-additive only. Sol passed 12 of 12, Argon 5 of 5 that could be
scored (its sixth was stopped by the plan cap, not by the model), and Luna did not run.
The third-fact trigger above fired: Sol missed 0 of 10 manipulated facts.

The tasks were easy for three reasons, read from Sol's tool calls:

1. **One owner per version.** Each version declared the value list once, and everything
   else, the type included, derived from it. A model that missed the owner broke every
   behavior, so its own first test found it. It was also the only line in the
   repository listing the values.
2. **Every holder sat in the feature folder.** Sol's third command in every attempt was
   `for f in stage/*; do cat "$f"; done`, which read all six holders at once.
3. **The task text named each kind of place**: "the independent validation operation",
   "the adjacent operation", "after all database migrations have been applied".

### What changes

This replaces the third-fact change. It does not add a third fact.

1. **Independent holders.** In every version, `<feature>/types.ts` declares the value
   list and the edit site uses it. The manipulated holder keeps its own independent copy
   of the list, which only its own behavior reads. Missing it leaves the primary
   operation and the model's own tests passing; only that fact's hidden test fails. In
   the versions where a holder is not manipulated, it derives from the type as before.

   | Shape | Independent holder |
   |---|---|
   | Type-enforced (control) | an exhaustive `Record<Stage, …>` map that the compiler rejects until it has the new key |
   | Direct import | the policy the edit site imports (still one import step, on the primary path) |
   | Name only | a descriptively named registry read only by a separate validation entry point |
   | Neighbor only | the adjacent operation's own accepted list |
   | Database | the CHECK constraint in a SQL migration |
   | Stored state | the build-status reader's list of stages that follow the live session; a stage missing from it reports a stored copy |

2. **Scattered holders.** Holders move to where a service keeps them rather than the
   feature folder: migrations under `db/migrations/` among the other features'
   migrations, the registry under `src/validation/`, the adjacent operation beside its
   route, the build-status reader under `src/sessions/`, the label map under
   `src/presentation/`. The type, the edit site and the direct-import policy stay in
   the feature folder. Distances in the cell table are recomputed from the new layout.
3. **Neutral task text.** The task text keeps stating every required behavior, so a miss
   is still a miss of a stated requirement, but as one requirement over the whole
   service rather than one sentence per place: the new value must work everywhere the
   existing values work, stored data included (renames: everything that accepts the
   former value accepts the new one, and new requests reject the former spelling). The
   label-length anchor stays an explicit sentence.

### Gate changes

The mutant gate keeps its form: the reference passes the manipulated fact and the
anchor, and each omission fails only its own fact. An omission now updates the type and
skips only the holder, which is the miss the study looks for. The type-enforced
omission still fails through the typecheck. The rule in `alignment.md` for a single
selected owner (option A) is withdrawn.

### Order of work

1. Change the generator and base for all three features, then regenerate and qualify
   stage-additive only, on mcclure.
2. Run a Sol-only pilot on stage-additive: 12 attempts, 2 per shape, plan cap $5 (one request's
   reservation spare), each round its own cohort label (`slice.json`) and under
   its own authorization. Read every attempt.
3. Repeat 1 and 2 until Sol misses some manipulated facts outside the control and at
   most 1 control fact. About 2 of 10 is the level meant; it is a guide, not a
   threshold. If Sol misses nearly everything, each miss is read for whether the task
   text stated the behavior.
4. Then expand to the other five tasks, rerun the three-model pilot with plan caps that
   leave one request's reservation of headroom, and set the main study's design and
   caps from its measured costs. Argon cost $0.52 an attempt in the first pilot, about
   3.5 times the plan's estimate, so the main study as planned does not fit $80; that
   decision is made then, with measured costs.

Pilot attempts from this or the first pilot are never pooled with the main study.

### Slice round 1 and the change for round 2 (2026-11-19)

Round 1 (independent, scattered holders; Sol only; stage-additive): Sol passed 12 of 12,
$2.94, 14 to 24 requests an attempt. Its tool calls show why. It lists all 87 files,
opens the holder files whose names contain the feature (`registered_stages.ts`,
`stage_labels.ts`, `stage_peer.ts`), reads 135 to 190 KB an attempt, more than the whole
124 KB of application code, and searches for the existing values. The task was also
small: add one value in about two places and widen one rule, so all of the model's
effort went to finding places.

Round 2 changes two things and keeps the service's size:

1. **Feature tasks.** Each task asks for a real feature in which the new or renamed value
   is one part. For stage-additive, a triage step: new imported jobs start in the new
   stage, a triager sets priority and owner and releases the job or rejects it with a
   reason kept in its history, and jobs in the new stage do not count toward dispatch
   capacity. The task text still states, in one plain sentence, that the value must work
   wherever the existing values do, stored data included, so a miss is still a miss of a
   stated requirement. The label-length anchor stays. Hidden tests of the feature's own
   behavior are reported but are not scored facts; they show the attempt did the feature.
2. **Neutral holder names.** Holders sit in shared files that do not name the feature
   (one validation registry, one peer module, one label module and so on, each serving
   all three features), so a file listing no longer points at them.

The service is grown only if Sol still finds every holder after this round.
