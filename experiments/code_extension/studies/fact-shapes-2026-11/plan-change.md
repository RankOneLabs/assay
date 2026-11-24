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

### Round 5: implicit holders that need a behavior decision (2026-11-20)

Rounds 1 to 4 showed that a literal copy of the value list is found by one search for the
existing values, at any service size. Round 5 changes what a holder is. The six shapes
and their places stay; what each manipulated holder holds changes:

1. **No literal list, no stage name.** The manipulated holder never writes out a stage
   name. It encodes the set another way that real services use: a position or rank,
   an exclusion or default branch ("anything that is not finished"), numeric codes, or
   display text that differs from the stored names. A search for the existing stage
   names does not reach it.
2. **A behavior decision.** Left unchanged, the holder gives the new stage a behavior
   the task rules out. Updating it correctly means applying a stated rule, not adding a
   value. The task text states each such rule as a product requirement of the triage
   feature, in plain terms that name no file, function or table.
3. **Elsewhere, correct by declaration.** In the versions where a holder is not
   manipulated, it reads a per-stage trait declared next to the type, which the compiler
   requires for every stage. Declaring the new stage's traits makes it correct.
4. **The anchor sentence is reworded** so it cannot be read as a rule for tags, and is
   checked against every other concept in the service.

The control (type-enforced) keeps a compiler-checked map, and now its value for the
new stage also has to follow a stated rule. Scoring, the mutant gate and the one-fact
rule per version are unchanged. The cell table for stage-additive is drafted and
reviewed before anything is built. Then stage-additive is built, qualified, and run
with Luna alone ($3 cap).

### Slice round 5 result (2026-11-20)

Luna, 12 attempts, $0.60. 10 passed with every fact correct; 2 hit the 60-turn limit
without submitting (control first attempt, reference first attempt). Luna updated the
manipulated holder in all 12 attempts, including both that did not submit.

- The four positional holders (`values.indexOf(stage) < 2`) were all rewritten to read
  `stageTraits[stage].open`, the declared trait, instead of being patched to a new
  position.
- The two database attempts added a migration that rebuilds the retention table with a
  30-day limit for stage code 4.
- The control attempts added the heading to the compiler-checked map, or derived the map
  from the traits.
- Placement: 10 attempts appended triaged; 2 (stored state and database, first attempts)
  inserted it second. Both still passed, because the holders they reached had already
  been made to read the traits.

The positional holders were found by search, not by reading: 5 of the 8 positional-holder
attempts ran a `grep` for `values.indexOf`, `indexOf(stage)` or `< 2`, and the other 3
searched for uses of `stageTraits` or the `values` list. Sharing one pattern across four
holders made one hit lead to all four.
The SQL limit was found because Luna reads every migration that mentions stage codes.

Five rounds in, Luna and Sol find every holder in a 124 KB and a 272 KB service, whether
the holder is a literal list, a position, a numeric code or a SQL check, and whether or not
the compiler requires it. The task's sentence that the new stage must work everywhere
sends both models into a full sweep of everything that touches the stage type.
Spend after round 5: $13.46.

### Round 6: nested state that must stay accurate when work moves backward (draft, 2026-11-20)

Rounds 1 to 5 tested facts that depend only on a job's current stage, so every holder was
a per-stage lookup and the task listed every behavior. Round 6 tests what has gone wrong in
a real service: state nested three levels deep, each level storing its own status, where a
change that sends work backward has to keep every level accurate.

**The nest.** The service already has jobs and their attempts (each attempt tied to a
session that owns its running status). Round 6 adds runs, a group of jobs, as the top level:

| Level | Stores | Derived from |
|---|---|---|
| Run | status (running, finished), job counts by stage, finish time | its jobs |
| Job | stage, outcome, finish time | its attempts and moves |
| Attempt | running, passed or failed | itself |

Today every level only moves forward: an attempt finishes, its job may complete, the run
may finish.

**Roll-ups are declared, not hand-written.** The base service keeps each level's derived
state in one declaration built from small reusable pieces, with no update code written per
level. In outline:

```ts
const runRollup = rollup<Job, RunState>({
  total: count(),
  done: count(isDone),
  status: when(all(isDone), "finished", "running"),
  finishedAt: latest(job => job.finishedAt),
});
```

`count`, `all`, `any`, `latest` and `when` live in `src/rollup/`. One engine recomputes a
parent from its children whenever a child changes, and walks up the nest. Adding a field or
a level means adding a declaration, never new update code. This is the extensible style a
real service needs, and the correct solution for round 6 works through it.

**The task (draft).** One rule, not a checklist:

> Add review to jobs. When a job's work is done it waits in a new in-review stage until a
> reviewer approves it, which completes it, or sends it back to active with a reason that
> stays in the job's history. A reviewer can also re-queue a completed job, which puts it
> back in the queue for another attempt, even when its run has finished.
>
> Runs and jobs must always reflect what they contain: their status, counts and times
> match their jobs and attempts after every move, single or in bulk, including for data
> already stored. Add roll-up behavior through the existing roll-up declarations, so a
> later field or level gets it without new update code.
>
> A job id made of letters, digits, underscores or hyphens must be accepted for stage
> changes up to 80 characters long, and longer or otherwise malformed job ids must be
> rejected.

**Six copies.** In every copy, roll-ups go through the declarations and the engine, except
one place that assumes work only moves forward. It is correct for every forward move and
wrong after a send-back or re-queue. No copy shares an expression with another, so one
search hit does not lead to the next.

| Copy | Hidden forward-only assumption | Symptom after a send-back or re-queue |
|---|---|---|
| Control | a compiler-checked table of how each stage counts toward its run; the new stage must be added and must count as not done | will not compile, or in-review jobs count as done |
| Reference | a combinator the run status is built from that holds `true` once reached (a latch), reached through the engine | the run stays finished after a job is sent back |
| Name only | a timing module, outside the roll-up folder, that records a run's finish time only if none is set | the run keeps its first finish time after it finishes again |
| Sibling only | bulk moves update run counts by adding to them instead of calling the engine, written as a speed-up beside the single-move path | bulk send-back leaves run counts too high |
| Outside code | a database trigger that marks a run finished when its last job completes, with no reverse branch | the stored run says finished while the service says running |
| Stored state | a run summary cache that skips finished runs, on the assumption that a finished run never changes | re-queuing a job in an already stored finished run leaves a stale summary |

**Scoring.**
- Hidden tests drive review, send-back, rework and approval, and a re-queue inside a
  finished run. One fact per copy checks the symptom in the table, plus the job-id anchor.
  The mutant gate and the one-fact-per-copy rule are unchanged.
- Two checks are reported, not scored, because a missed fix can fail them in any copy:
  - a whole-nest check that every stored run and job equals a recomputation from its
    children;
  - an extension check that declares one new run field from the existing pieces (for
    example a count of jobs in review) and checks it after a send-back. It tells a fix made
    in the declarations or engine apart from a special case patched at a call site.
- Reading each attempt also records where the fix was made: in the roll-up pieces, in the
  engine, or at a call site.

**Build and run.** Rebuilds stage-additive in place (the task still adds a stage), built by an agent, qualified on
mcclure, then run with Luna alone at a $3 cap (about $0.60). The task text and the table
are reviewed before anything is built.

### Slice round 6 result (2026-11-20)

Luna, $0.46 settled plus one request of unknown cost (at most $0.05). The plan halted after
9 of 12 attempts: the 15-minute wall limit cut off the reference second attempt mid-request,
so its charge was never reported, and the launcher stops on an unknown charge. The other
three second attempts (sibling only, control, stored state) never ran.

All 8 attempts that submitted passed every scored fact and both reported checks (the
whole-nest check and the extension check). All 9, including the one that timed out, fixed
the arm's forward-only assumption:

- Control: derived the stage table from the declared traits.
- Reference (both): removed the latch from the `when` piece, matching the reference fix.
- Name only (both): made the finish time follow the run's current status.
- Sibling only: replaced the bulk adder with one engine refresh of the moved jobs.
- Database: one attempt added a migration that rewrites the trigger to work both ways and
  repairs stored rows; the other did the same from the schema setup code.
- Stored state: deleted a run's stored summary whenever the run's state is stored, in the
  run repository rather than the cache.

Every fix went through the roll-up pieces, the engine or the storage layer. None was a
special case at a call site. One name-only attempt finished in 17 requests.

Six rounds in, no model has missed a holder. Round 6's task states the invariant ("runs
and jobs must always reflect what they contain") and says where to add roll-up behavior,
so the model rereads the roll-up path and checks each place against a rule it was given.
Spend after round 6: $13.92, at most $13.97.

### Replay of a real agent failure: Run build (2026-11-21)

The task is the five review comments the agent got on round 2 of Oakridge PR #82, replayed
on the commit it started from (0f95ef0). The agent's own answer (598956c) showed a build as
running whenever the brief had any session, so an ended build blocked a new one. Oakridge
#99 fixed that. The hidden test has two cases on a brief whose build was started
automatically: while that build is live the view shows it and offers no rerun, and once it
has ended Run build is enabled and starts a new one.

Luna, 6 attempts, $0.23. All 6 incorrect, and all 6 for the same reason: the live case
fails and the ended case passes. None repeated the agent's bug. Every attempt took the
first option the Copilot comment offers ("make build start exclusively manual"): it
removed the dispatch on brief approval and kept or added a Run build button. Three also
show "Build started" after their own click. None shows a build that was already running
when the page opened. All 6 also handled the other four comments, passed the visible and
hidden regression suites, and reported checks that ran.

This does not count as a missed holder. The task offers manual-only as an acceptable fix,
and the hidden live case marks it wrong because it needs a brief that was approved before
the change. Such briefs exist in a running system, but no comment mentions them. As built,
the replay grades the choice between the two options the comment offers, not whether the
model finds every place that holds the build state. To make it a holder test, the task
would have to rule out manual-only, for example by dropping that option from the comment.
Spend after the replay: $14.15, at most $14.20.

The Copilot comment now offers only the second option: "Have this UI display/refresh the
existing automatic build session and only enable rerun after it has settled or completed."
The change is applied by `TASK_EDIT` in `replay_kbbl.py`. The tree, patches and hidden tests
are unchanged. Requalified on mcclure with the same image. Second run: `replay99b.json`,
Luna, 6 attempts, $3 cap.

Second run (2026-11-21, $0.26, 284 requests, no halt): 3 correct, 2 incorrect, and 1 stopped
at the 60-turn limit without submitting. No attempt removed the automatic dispatch, and every
attempt looked up the session's status instead of treating any `current_session_ref` as a
live build. So none repeated the agent's bug. All 5 submissions passed the live case. The 2
incorrect ones failed the ended case for a different reason: they enable rerun only when the
cohort's status is `building` (w5 also accepts `done`). In production, approving a brief moves
its cohort to `building` (`brief-status.ts`). The hidden test sets the brief to approved with
raw SQL, so its cohort stays at the default `waiting`, a state approval never leaves. Those
two fails come from the test's setup, not from a missed place. Spend after the second run:
$14.41, at most $14.47.

The hidden test now moves the cohort to `brief_review` and approves the brief through the
real `PATCH /briefs/:id/status`, so the cohort is `building` as in production. Requalified on
mcclure with the same image (manifest sha256:ad361db4…). The held patches grade as before:
reference and both alternatives pass, the agent's commit still fails the ended case, and
manual-only still fails the live case. The second run's six patches (kept in
`replay99b-patches/`) regraded against the fixed test with no model spend: all six pass both
cases, including w2's unsubmitted workspace. Under the fixed test the second run scores 5
correct of 5 submitted, and no attempt repeated the agent's bug.

### Replay of a real agent failure: build guard (2026-11-22)

Second replay, of PR #82 round 3. A build agent following the cohort-5 build brief
(Oakridge fc87c8e1c9) added POST /briefs/:id/build with a guard that refused the build while
the cohort's `current_session_ref` named any live session. The dispatcher also writes that
field for planner2, as the same brief says. So a planner2 session still up blocked the
operator's Run build after a failed automatic dispatch. The fixture
(`kbbl-build-guard-replay`, built by `replay_kbbl82.py`) starts at 7fce9e87dd and gives the
brief as the agent had it, asking for subgoal 11. The brief spelled the guard as the agent
wrote it; the task replaces that clause with the brief's own intent ("409 if a build is
already running for this cohort"), so following the text is not marked wrong. The hidden
test reaches its state through the planner2 dispatch, cohort 3's transitions, POST /briefs
and the real approval. Two adaptations make the start tree typecheck: a stale
briefs.test.ts call, and app.test.ts left unbuildable by the agent's required `dispatcher`.

Qualified on mcclure with the same image (manifest sha256:303f3542…). The reference (the
fix's stage column) and two other correct fixes pass all five hidden cases; the agent's
commit fails only the two planner2 cases; a guardless variant fails only the live-build case.
Plan: `replay82.json`, Luna, 6 attempts, $3 cap.

Result (2026-11-22, $0.27, 329 requests): 4 submitted, all incorrect; 2 stopped at the
60-turn limit. Every submitted attempt fails exactly the agent's two cases (planner2 still
up blocks Run build; the view's button therefore starts nothing) and passes the other three,
the visible suite and the hidden regression. All six patches, including the two unsubmitted
workspaces (kept in `replay82-patches/`), guard on any live `current_session_ref`, the
agent's bug. Each one edited the dispatcher, the file that writes that field for planner2
and build alike, and added a status lookup that treats the ref as the build's (w4 names it
`isBuildRunning`). No patch mentions planner2. Unlike the first replay, the hidden test was
not the problem here: the agent's failure reproduced 6 of 6 under a task that states the
intent and a brief that states planner2's write.

### Build-guard replay: fact-shape arms (2026-11-23)

The brief states planner2's write once, in subgoal 7 ("cohorts for planner2 and build"). The
dispatcher's write names build in a comment and planner2 nowhere: it branches on the stage's
input type. Each arm adds the fact in one more place and is its own scenario
(`replay_kbbl82.py --arm`); hidden tests and held fixes are built the same way.

| Arm | Change from the replay |
|---|---|
| `near-ask` | subgoal 11 gains a bullet: "The dispatcher writes the cohort's `current_session_ref` for planner2 as well as for build (subgoal 7)." |
| `write-comment` | the dispatcher's cohort branch gains a comment naming planner2 and saying a build dispatch writes the same column |
| `write-named` | that branch tests `stage.name === "planner2"` instead of the input type (same branch for the seeded stages) |

All three qualified on mcclure with the same image; image grading matches the replay's on
every held patch (the fix and both alternatives 5/5; the agent's commit fails only the two
planner2 cases; no-guard only the live-build case). Turn limit stays at 60 so the arms
compare with the replay's run; unsubmitted workspaces are regraded from their patches.

Cohort `replay82-arms.json`: Luna on the three arms, 6 each, $3 cap; Sol on the unchanged
replay, 6 attempts, $4 cap, to see whether the miss is Luna's alone. Combined cap $7.

A further candidate, not built: the brief's decisions section gives the ref's purpose as
letting `/briefs/:id/build` "block on 'this cohort is already building'", which reads as
permission for the agent's guard. An arm without that rationale would separate a misleading
stated reason from where the fact sits.

Result (2026-11-23, $2.78: Luna $0.73, Sol $2.04). No arm moved Luna.

| Plan | Submitted | Correct submitted | Turn-limit | Workspaces correct (regraded) |
|---|---|---|---|---|
| Luna, near-ask | 3 | 0 | 3 | 1 of 6 (w1, unsubmitted) |
| Luna, write-comment | 3 | 0 | 3 | 0 of 6 |
| Luna, write-named | 3 | 0 | 3 | 0 of 6 |
| Sol, unchanged replay | 6 | 0 | 0 | 0 of 6 |

Every submitted Luna attempt failed exactly the agent's two planner2 cases. Of the nine
unsubmitted workspaces (regraded locally from `replay82-arms-patches/luna/`), three fail the
typecheck, five fail the planner2 cases, and near-ask w1 passes all five: it records build
sessions per cohort in the dispatcher and guards on those only.

Four Luna attempts (one per arm, plus a second write-comment) wrote in a comment that
planner2 shares the ref, then guarded on the ref's session still running, which stops a
planner2 session left live. They read planner2's write but assumed its session ends once the
brief is posted. The planner2 prompt does end "summarise the key decisions and stop", while
kbbl's chat sessions are stdin-driven processes that `status()` reports `running` until they
exit. So the binding fact is planner2's session lifetime, not where planner2 writes, and no
arm states it.

Sol (`replay82-arms-patches/sol/`): five of six failed the planner2 cases. w1 cleared the
ref on brief approval (the held alternative-clear fix) but then refused any build while the
cohort was `building` with a ref, so an ended build blocked a rerun. w0, w2 and w3 did the
same without the clear, failing the planner2 and ended cases; w4 and w5 made Luna's guard.
Sol costs about $0.34 per attempt here, 8x Luna.

### Build-guard replay: lifetime arm (2026-11-24)

The arms run showed the attempts that read planner2's write still assumed its session ends
once the brief is posted. The lifetime arm (`kbbl-build-guard-replay-lifetime`) is near-ask
plus one more task bullet: "A planner2 chat session stays `live` after it posts the brief and
summarises; it ends only when the operator ends it." Luna, 6 attempts, same bounds.

Result ($0.26): 2 of 3 submitted correct (w0, w5); w3 submitted the planner2 bug with a
failing typecheck. Regraded locally (`replay82-lifetime-patches/`), 4 of 6 workspaces have the
right behavior (w0, w2, w4, w5; w2 fails the typecheck on an unused import), against 1 of 6 for
near-ask and 0 of 6 for the replay. The correct attempts tag each session ref with the stage
that launched it and block only on a live build. w1 refused while the cohort was `building`
with a running ref, which a live planner2 still trips.

So the binding fact was planner2's session lifetime, which the replay's code implies (chat
sessions are processes that `status()` reports running until they exit) but nothing states.

### Build-guard replay: stage-runs arm (2026-11-24)

`kbbl-build-guard-replay-stage-runs` asks whether a clean session model leaves the trap at
all. The start tree records each dispatch as a `stage_runs` row (stage, input artifact,
session) in place of the `current_session_ref` column planner2 and build share; the brief's
subgoals and decision describe that model, with the same "block on 'this cohort is already
building'" rationale. Lifetime is not stated. Hidden tests are the replay's, byte for byte.
Held: reference (live build run on any of the cohort's briefs) and alternative-brief pass;
negative (any live run on the cohort or brief) and no-guard fail. Qualified on mcclure;
cohort sha256:fd1850b8….

Result ($0.23, two provider halts): 2 of 2 submitted correct (w1, w4); w0 and w5 hit the turn
limit; w2 and w3 were cut off by provider errors (an Azure 520, then an Azure content-policy
block on OpenRouter's Luna route), each accepted at its reservation on resume. Regraded
locally (`replay82-stageruns-patches/`), all four attempts that ran to the end have the right
behavior: w0 passes everything, and w5 passes the hidden tests but fails the typecheck because
it never added the dispatcher to the existing test's app deps. w2 and w3 stopped mid-wiring
(typecheck fails, Run build not yet reachable), so they say nothing about the guard.

Every finished attempt queried `stage_runs` for build runs on the cohort's briefs and asked
the dispatcher whether each was still live: the reference guard. None touched planner2's runs,
so no attempt made the replay's mistake, without being told planner2's session lifetime.

| Arm | Submitted correct | Workspaces with the right behavior |
|---|---|---|
| Replay | 0 of 4 | 0 of 6 |
| Near-ask | 0 of 3 | 1 of 6 |
| Lifetime | 2 of 3 | 4 of 6 |
| Stage-runs | 2 of 2 | 4 of 4 finished (2 lost to provider errors) |

So the trap was the shared column, not the indirection: once the model records which stage
owns each session, the brief's "block on 'this cohort is already building'" no longer leads
anywhere wrong, and the lifetime fact stops mattering.
