# Fact-shapes study: plan (draft)

Status: draft, 2026-11-18. The operator agreed the reading rules on 2026-11-18, with
miss counts as a guide rather than a threshold. The first pilot ran on 2026-11-18; the
tasks are being rebuilt with independent holders (second change in `plan-change.md`).

## Question

When a change needs a value added or renamed in several places, which kinds of place do
models miss? The places differ in what would lead a model to them: a type the compiler
enforces, a direct import, only a descriptive name, only a similar neighboring operation,
a database constraint outside the code, or stored state that must be reused rather than
copied.

The two earlier studies could not answer this. Sol passed 57 of 57 submitted attempts in
the matched-task study and 11 of 11 in the library calibration. Their tasks named the
files and keys to change, and scored a whole task as one pass or fail. This study changes
three things, recorded in `plan-change.md`: the task text describes only behavior, each
required fact is scored on its own, and half the tasks rename an existing value instead
of adding one.

## What runs

One small TypeScript job service (87 files, about 340 KB). Three features each get two
tasks, add a new value or rename an existing one, which makes 6 tasks:

| Feature | Add | Rename |
|---|---|---|
| Job stage | add `triaged` | rename `queued` to `triaged` |
| Evidence kind | add `attestation` | rename `document` to `attestation` |
| Route permission | add `case_inspect` | rename `case_read` to `case_inspect` |

Each task comes in 6 versions of the service. They differ only in where one required fact
lives, the "shape":

| Shape | Where the fact lives | What leads a model there |
|---|---|---|
| Type-enforced (control) | the value's type | the compiler rejects the edit until it is updated |
| Direct import | a policy the edited file imports | one import step from the edit |
| Name only | a separately named registry | its descriptive name; nothing imports it from the edit |
| Neighbor only | a similar operation next to the edited one | analogy with the edited operation; no import path |
| Database | a CHECK constraint in a SQL migration | nothing in the TypeScript code |
| Stored state | existing stored data | adding: reuse it rather than keep a copy; renaming: every reader must follow it |

Every version of a task has the same task text, which states every required behavior in
plain words. Each attempt is scored on two facts: the one its version moves (the
manipulated fact) and a fixed label-length rule that every version shares (the anchor).
The anchor checks that the model read and followed the task at all.

The full table of 36 task versions, with file paths and import and directory distances,
is `cell-table.md`.

## Models and limits

| Model | Route | Per-attempt cap |
|---|---|---:|
| GPT-6.1 Sol | `azure/us` | $2.00 |
| Gemini 4 Argon | `google-vertex/global` | $4.00 |
| GPT-6 Luna (mid-tier) | `azure` | $1.00 |

Limits are those of the matched-task and library studies: 60 requests, 900 seconds,
8,192 output tokens per request, 120 seconds per request and 32 KiB of tool output, at
concurrency one with no retries. An attempt stopped by a limit stays visible as an
outcome.

The per-attempt caps are not expected cost. Each request reserves its worst-case price
against what is left of the attempt's cap, so a lower cap would cut long attempts short
and change their outcomes. Spending is bounded by the plan caps below. A plan that
reaches its cap halts, and the halt is reviewed before anything else runs.

## Order of work

The study runs as a slice first, then expands. Nothing past a step is built or run until
that step is reviewed.

1. **Offline slice.** Generate and qualify only the job-stage add task's 6 versions.
   Qualification checks, in fresh Docker sandboxes, that a correct patch passes and
   that dropping each fact fails only that fact's tests.
2. **Paid slice (the pilot).** Run the pilot below on those 6 versions.
3. **Iterate.** Every failed pilot attempt is read against its task and hidden tests. A
   version is fixed only if a hidden test rejects a correct change, or the attempt failed
   for a reason unrelated to the task. Any fix, and the third-fact change below, goes
   back to step 1.
4. **Expand.** Generate and qualify the other 5 tasks with the generator and shared tests
   unchanged from the approved slice. A change to either goes back to step 1.
5. **Freeze.** Regenerate everything, check it matches the committed files byte for
   byte, pin the cohort files, and set the study's plan caps from the pilot's measured
   means.
6. **Main study,** with its own authorization.

## Pilot

| Model | Versions | Repeats | Attempts | Plan cap | Expected at known means |
|---|---|---:|---:|---:|---:|
| Sol | job-stage add, all 6 shapes | 2 | 12 | $4.00 | $1.56 |
| Argon | job-stage add, all 6 shapes | 1 | 6 | $4.00 | unknown, about $0.90 |
| Luna | job-stage add, all 6 shapes | 1 | 6 | $2.00 | unknown, about $0.30 |
| Total | | | 24 | $10.00 | about $2.80 |

Sol's expected cost uses its library calibration mean of $0.13 per attempt. Argon is
priced near Sol, and Luna lower; the pilot measures both. Each plan also makes one billed
route probe inside its cap.

The pilot answers four questions:

- **Is a version broken?** Read every failed attempt, as in step 3.
- **Is the task too easy?** If Sol misses at most 1 of its 10 manipulated facts outside
  the type-enforced control, a third required fact is added through a written plan
  change before expansion. This rule was fixed on 2026-11-15, before any attempt.
- **Do models finish?** Count attempts stopped by a limit, per model.
- **What does an attempt cost?** The pilot's measured means set the main study's split
  of its $65 cap.

Pilot attempts are never pooled with the main study.

## Main study

6 tasks × 6 shapes × 3 models × 5 repeats = 540 attempts, 180 per model. Each model has
15 attempts per shape and task type (3 features × 5 repeats).

| Model | Attempts | Expected at known means | Plan cap (provisional) |
|---|---:|---:|---:|
| Sol | 180 | $23 | $26 |
| Argon | 180 | about $25; about $50 at Argon's Dec 1 price | $28 |
| Luna | 180 | about $8 | $11 |
| Total | 540 | about $56 | $65 |

The pilot, the Luna library rerun ($5) and the main study together stay within $80. If
the pilot's means do not fit the main study inside $65, the fallback is 3 repeats
(324 attempts) rather than a higher cap. Argon prices are checked again just before
launch.

## Outcomes

Each dispatched attempt gets exactly one outcome:

| Outcome | Rule |
|---|---|
| Scored | Graded. The manipulated fact and the anchor are each held or missed, read from hidden test groups titled `fact:<fact id>:`. |
| Unscored | Graded, but a fact's tests did not run, for example because the patch failed to apply or type-check. The reason is recorded. |
| Stopped | Ended by a limit before submitting: requests, output tokens, wall time or request timeout. |

## Exclusions

A model is left out of the planned comparisons, but still reported, when more than 20% of
its scored type-enforced attempts miss their fact, or more than 20% of all its scored
attempts miss the anchor. Either means its misses cannot be told apart from not doing
the task.

## Planned comparisons

All counts are misses out of scored attempts, per model, per task type, per feature and
pooled over the 3 features, with Wilson 95% intervals. The intervals describe variation
between repeats on 3 fixed features, not sampling over tasks.

1. Each shape against the type-enforced control.
2. Neighbor only and database against direct import: does losing the import path matter?
3. Rename against add, for name only, neighbor only and database.
4. Among misses, how often the model had opened the file holding the fact: neighbor only
   and database against name only.

Also reported:

- **Import distance:** misses by number of import steps from the edited file, as a check
  against "shapes only differ by import distance".
- **Stored-state copies:** in add tasks on the stored-state version, how many patches
  declare a second copy of existing stored data. The count is a lower bound.
- **Exploratory:** whether misses come with a completion claim, and whether the file
  holding the fact was read.

`uv run python -m code_extension.fact_shapes.tally` prints all of these.

## Reading the results

The study is descriptive. No miss count passes or fails a shape by itself. Two kinds of
rule apply: hard stops about whether the data can be read at all, and a guide for which
shapes to look at first.

**Readable:** a model has at least 10 scored attempts in each shape and task type.

**Hard stops.** Apply the first row that matches:

| Result | Next step |
|---|---|
| Any model and version has fewer than 5 dispatched attempts | Incomplete. Review the plan's halt first. |
| No model is readable, or every readable model is excluded | Stop and review. |
| Every readable model misses nothing outside the control | Stop. Report a ceiling, with the pilot's third-fact result. |

Otherwise the results are read, not scored.

**Guide, not a threshold.** A shape is worth a close look for one model when, pooled
over the 3 features, it has clearly more misses than the type-enforced control in the
same task type. About 4 misses in 15 scored attempts against at most 1 in 15 for the
control is the rough level meant. At 15 attempts the 95% intervals of 4/15 (11% to 52%)
and 1/15 (1% to 30%) still overlap, so no count is a clean line. A shape at 3/15 is not
passed: it is reported with its interval and read the same way.

Every counted miss, in every shape, is read against its patch and hidden tests before
anything is written about it. A pattern is written up as a shape result only when at
least 2 readable models miss on the same shape. A pattern in 1 model is reported as that
model's result.

## Limits every report must state

- One small synthetic service and 3 features. Repeats measure variation within a task,
  not independent tasks, so results are descriptive: counts and intervals, no
  significance tests.
- Each task text lists every behavior for every shape, so a model reads requirements
  that its version does not test. Only the manipulated fact and the anchor are scored.
- Shapes are built by moving one fact's location in the same service. Shape, file
  layout and import distance are not fully separable; `cell-table.md` gives both
  distances for every version.
- The stored-state copy count is a lower bound, read from patch text.
- Tasks and plans run in sequence, which separates models in time.

## Store

Run from `~/studies/assay-code-extension/fact-shapes-2026-11/` on otto, where the
evaluator's Docker runtime lives. Copy the store to the same path on willie after each
plan. Observations stay outside this repository.

## Billing recovery

Same as the library study: launch authorization pre-approves `--accept-unknown`, within
unchanged caps, for unknown charges from `agent_deadline` attempts and from connection
drops (`transport_failure`). Any other unknown charge, or a bill above its reservation,
stops for the operator. No attempt is retried or replaced.
