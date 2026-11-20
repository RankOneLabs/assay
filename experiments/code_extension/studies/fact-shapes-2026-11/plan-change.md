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

### Slice round 2 and round 3 (2026-11-19)

Round 2 (triage feature, neutral holder names; Sol only): $4.03. Sol found 9 of 10
manipulated facts outside the control and both controls, and passed all five feature
checks in every attempt. Two fixture bugs showed up:

- The task said triaged jobs must not count toward the job limit, but imported jobs
  start in triaged and visible import tests assert import capacity, so any faithful
  implementation failed those tests. The clause is dropped; the task now says only
  that triaged jobs are never picked for a build.
- The one miss was the stored-state fact, which tested build status for a triaged job
  with a running build, a state the task forbids. The stage stored-state holder moves
  to the export reader: a triaged job reaches it through import, a priority or owner
  change and export, all of which the task allows. The feature's own path never
  exports.

Sol still reads nearly all of `src/` early in each attempt, shared holder files
included, so round 2 is read as effectively 10 of 10 for Sol.

Round 3 runs the mid-tier model (Luna) alone on the corrected slice, 12 attempts with a
$3 cap, to see whether a weaker model misses holders before the service is changed
again.

### Slice round 3 result (2026-11-19)

Round 3 (Luna alone, corrected slice): $0.30 for 12 attempts, 18 to 43 requests each.
Eleven attempts submitted. Ten passed every scored fact, the anchor and all five feature
checks, controls included. Every visible test passed.

- **Database, second attempt: fact failed, holder found.** Luna read the CHECK and wrote
  a correct table-rebuild migration, but named it `zzz_stage_triage.sql`. The loader
  only applies files whose names start with a digit, so the migration never ran and
  the retention write for `triaged` failed its foreign key. Renamed to
  `002_stage_triage.sql`, the same patch passes the hidden test. The loader's pattern
  was in a file Luna searched for during the attempt.
- **Neighbor only, first attempt: no submission.** Luna updated the peer module's own
  list and then stopped without calling submit. Its unsubmitted workspace passes all 12
  hidden tests and all 490 visible tests.

So Luna, like Sol, found every independent holder. Its one fact failure came from
applying a found holder wrongly, not from missing it. Like Sol, it opened about 25
files of `src/` in each attempt before editing.

### Round 4: a larger service (2026-11-19)

Both models open nearly all of `src/` (about 120 KB) before editing, so at this size no
placement of holders can hide one. Round 4 doubles the application code to about 250 KB,
one step rather than a large jump, by adding real features that sit beside the existing
ones. It adds no padding and no holders:

- New code derives any stage, evidence-kind or permission list from the type, and never
  writes out a value that a rename task renames. The holder audit shows the holder set
  is unchanged.
- Holders, task texts, hidden tests and the anchor stay as they are. Distances in the
  cell table are recomputed for the new layout.
- New features get visible tests of their own, in the style of the existing ones.

Stage-additive is regenerated and requalified alone. Luna then runs the slice again (12
attempts, $3 cap, about $0.50 expected). If Luna still finds every holder, the next step
is another size step. If it misses some, Sol runs the same slice.

### Slice round 4 result (2026-11-20)

Round 4 (Luna alone, the 272 KB service): $0.47 for 12 attempts, 21 to 60 requests each.
Seven attempts passed everything. Luna updated the manipulated holder in all 12,
including the five that did not pass.

All five non-passes have one cause, a defect round 4 introduced. The new tags feature
makes tags lowercase slugs of letters, digits and hyphens up to 40 characters. The
anchor sentence ("Labels containing letters, digits, underscores or hyphens must be
accepted up to a length of 80 characters …") reads as a rule for tags, and Luna applied
it there:

- Stored state, first attempt: changed tags to 80 characters and left the real label
  check alone, so the anchor fact failed.
- Control, second attempt: did the anchor correctly and also changed tags, breaking six
  visible tag tests.
- Control first attempt (15-minute wall limit), database second attempt and stored state
  second attempt (60-turn limit): spent 38 to 48 of their roughly 100 commands on tag
  tables and tag tests.

Size did not make holders harder to find. Luna's first move is a search for the existing
values (`grep -RIn '"queued"\|"active"\|"complete"' src …`), and every independent holder
is a literal copy of the value list, so that one search finds every holder at any size.
Two passing attempts opened a single file; the rest opened 31 to 39.
