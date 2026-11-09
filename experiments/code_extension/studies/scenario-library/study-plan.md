# Scenario library study: plan (draft)

Status: draft, 2026-11-08. Not confirmed, and no cohort is authorized. The outcome rule was
settled on 2026-11-07, before any library task was qualified. No library attempt has run.

## Question

When the hard part of a task is connecting code across modules, do models write the feature
but leave it unreachable? Does that happen more than on tasks whose edits are all local?

The matched-task study could not answer this. In 140 attempts no model left a stage
unreachable or left it out, but each task's wiring was only about 20 lines of registration.

## What changes from the matched-task study

The matched-task study gave each task several hand-made code shapes. This study does not.
Each library task keeps the one shape the real code has, and shapes are compared between
tasks. Every task is cut from oakridge commit `1495ec34`.

## What runs

Each cohort has a file in this directory, and each is its own authorization.

| Cohort file | Tasks | Models | Repeats | Attempts | Cap per plan | Combined cap |
|---|---:|---|---:|---:|---:|---:|
| `calibration.json` | 11 | Ministral 14B, Qwen3.8 27B, GPT-6.1 Sol | 1 | 33 | $2.00, $3.00, $5.00 | $10.00 |
| `study.json` | 11 | Ministral 14B, Qwen3.8 27B, GPT-6.1 Sol | 5 | 165 | $10.00, $12.00, $18.00 | $40.00 |

The 11 tasks are 9 with a non-local edit and 2 local controls. The three models and their
routes are the ones in the matched-task study, which keeps its results as a reference point.
All three are needed. In that study Sol submitted almost every time, while Ministral used all
60 requests in 7 of 40 attempts and Qwen timed out in 10 of 40.

The cap per attempt stays at $0.75 for Ministral and Qwen and $2.00 for Sol. The bounds also
stay the same: 900 seconds, 60 requests, 8,192 output tokens per request and 32 KiB of tool
output, at concurrency one with no retries. Attempts stopped by these bounds stay visible as
outcomes, so a tighter or looser bound would mean a new cohort. Each plan makes one billed
route probe, inside its cap and not counted as an attempt.

## Expected cost and time

These projections use the matched-task study's measured means. Library tasks need more edits,
so real cost may be higher. Calibration measures this.

| Model | Mean per attempt | Most expensive attempt | Study at that mean (55 attempts) | Study cap | Mean time per attempt | Study time |
|---|---:|---:|---:|---:|---:|---:|
| Ministral | $0.054 | $0.155 | $2.97 | $10.00 | 197 s | 3.0 h |
| Qwen | $0.085 | $0.151 | $4.68 | $12.00 | 618 s | 9.4 h |
| Sol | $0.095 | $0.176 | $5.21 | $18.00 | 88 s | 1.3 h |
| Total | | | $12.86 | $40.00 | | 13.8 h |

Calibration at the same means is $2.57 and 2.8 hours. If every attempt reached its timeout,
before grading, calibration would take 8.25 hours and the study 41.25 hours.

Route prices were checked on 2026-11-08 and match the matched-task study: `mistral/zdr`
$0.20/$0.20, `deepinfra/bf16` $0.15/$1.875 and `azure/us` $2.20/$11.00 per million input and
output tokens. They are checked again just before each launch.

## Calibration

Calibration runs first. Its attempts are never pooled with the study. It answers two
questions.

**Is a task broken?** Every failed calibration attempt is read against its task and hidden
tests. A task is fixed only if a hidden test rejects a correct implementation, or the task
fails for a reason unrelated to the request. A fix needs new qualification, new digests and an
amendment here. No task is replaced or dropped for being too easy or too hard, because a task
that every model wires correctly is a result.

**Does the budget hold?** Calibration runs one repeat of everything the study runs five times,
so its spend times 5 projects the study. The study needs a new decision from the user if any
plan's calibration spend passes 75% of its study cap divided by 5:

| Model | Calibration spend limit | Expected at last study's mean |
|---|---:|---:|
| Ministral | $1.50 | $0.59 |
| Qwen | $1.80 | $0.94 |
| Sol | $2.70 | $1.04 |

## Outcomes

Each dispatched attempt gets exactly one outcome. They are the same as in the matched-task
plan, `../matched-tasks-2026-11/study-plan.md`, with one exception. That plan said
"omitted stage" and keyed it to the stage name. Library tasks add no stage, so each task
now declares its own feature names:

| Outcome | Rule |
|---|---|
| Omitted feature | Graded, and a `new_behavior` test titled `reachability:` failed. The patch also adds no line outside `tests/` that names any of the task's feature names, in any spelling. |
| Reachability failure | Graded, a `reachability:` test failed, and the patch names the feature. |

"Any spelling" ignores case, underscores and hyphens, so `max_silent_ms` also matches
`maxSilentMs`. Every held patch of a task names one of its feature names, including the
patches that fail. A test checks this, so a held patch can never read as omitted.

Other cells keep the old rule, keyed to the stage name. The outcome reader still labels
this outcome `omitted_stage`, so the finished study's tables do not change.

A `reachability:` test checks only that the feature was reached at a place the task requires.
Content checks are titled `semantics:`, so wired code with a content bug is a semantic failure.
This definition is wider than the matched-task plan's in one case. In the review shortcuts task,
filtering the list but not invoke is a reachability failure, because the filter is written but
never reached on that path. The credential check in the restricted evidence task stays a semantic
failure, because it is a security rule rather than wiring.

## Feature names per task

An attempt that names any one of a task's names counts as naming the feature.

| Task | App | Feature names |
|---|---|---|
| Per-worker silence limit | oakridge-dbos | `max_silent_ms` |
| Operator route listing code operations | oakridge-dbos | `/api/operations` |
| Per-worker start budget (control) | oakridge-dbos | `deadline_ms`, `max_start_attempts` |
| Single-item evidence build | observation | `subject_only` |
| Addressing check over a producer-built link view | observation | `addressing` |
| Restricted evidence kind with its own export allowance | observation | `restricted_content` |
| Separate export credential (control) | observation | `OBSERVATION_EXPORT_CREDENTIALS` |
| Agent's native compaction summary as the handoff | kbbl | `NativeCompactionSummaryGenerator` |
| Context-window usage in the inbox | kbbl | `context_used` |
| Review shortcuts only for sessions with the server | kbbl | `OAKRIDGE_GATED_REVIEW_URL`, `selectMcpServers`, `selectGatedReviewAccess` |
| Per-agent default model and effort | kbbl | `default_model` |

Known limits of these names:
- In the shortcuts task, an attempt that checks the grant by hand and never names the
  URL or either policy function reads as omitted. Each such attempt is reviewed.
- `deadline_ms` also matches the existing `DEFAULT_PROVIDER_DEADLINE_MS` line. Every real
  start-budget attempt edits that line anyway.
- The compaction task cannot use `native_compaction`, because the start tree already
  declares it. The generator's class name is given in the request instead.

## Measures

All counts are per task and model, five attempts each. The measures are those of the
matched-task plan: yield, completion, conditional correctness, reachability failures, omitted
features, semantic failures and stops before grading. Reachability failures are the primary
measure here. Each is shown out of dispatched attempts with the ungraded count beside it, since
an attempt that never submits cannot show a reachability failure.

## What hides the edit

Tasks are grouped by what hides the non-local edit. These groups are fixed before any attempt
runs. They are used only to describe results, never in the decision rule.

| Group | Tasks |
|---|---|
| A runtime table or list that the type checker does not check | Operator route, single-item evidence build, addressing check, restricted evidence kind |
| A value or call carried through several layers | Per-worker silence limit, context-window usage, per-agent default model |
| A protocol flag, a strategy order, or a second boundary | Native compaction summary, review shortcuts |
| None: all edits are local (control) | Per-worker start budget, separate export credential |

## Decision rule

The rule reads only mechanical outcomes, so review of failures cannot change it.

**Shows missed integration:** for one model on one task, at least 2 reachability failures in 5
attempts. This is the same threshold as the matched-task study. An omitted feature never counts.

**Recurs:** for one model, at least 3 of the 9 non-local tasks show missed integration, and they
span at least 2 of the 3 apps.

**Control clean:** for that same model, neither control shows missed integration.

**Readable:** a model has at least 3 graded attempts on at least 5 of the 9 non-local tasks.

Apply the first row that matches.

| Result | Next step |
|---|---|
| Any task and model pairing has fewer than 5 dispatched attempts | Incomplete. Do not apply the rule. Review the plan's halt first. |
| Each task and model pairing has 0 or 5 passes of 5 | Stop and review, because the cohort is at floor or ceiling. This holds even if the rule is met. |
| No model is readable | Stop and review. Too few attempts submitted to say anything about wiring. |
| Recurs and control clean, for the same model | Review every counted failure against its patch and hidden tests, then plan a study of what hides the edit. |
| Recurs, but no model that recurs has a clean control | Review. The failures are not specific to non-local edits. |
| Any non-local task shows missed integration | Review those tasks before committing to anything further. |
| No non-local task shows missed integration | Stop and review. Report the combined count with the matched-task study. |

## Limits every report must state

- Repeats measure variation within a task. They are not independent tasks.
- There are 9 non-local tasks, below the ten-task reporting threshold for paired inference, so
  results are descriptive: raw counts and no significance tests. The tenth candidate from the
  survey was not built, because its only unreachable patch is weak.
- There are 2 controls. Only the start budget is closely matched to a non-local task, the silence
  limit, and shares its files. The export credential is in the same app as 3 non-local tasks but
  is not paired with one.
- Tasks are not balanced across apps: oakridge-dbos has 2 non-local tasks, observation 3 and kbbl
  4. Task difficulty, app and shape cannot be separated.
- A reachability failure is read from test titles. A hidden test that is too strict would count
  as one, which is why counted failures are reviewed. All 11 sets of hidden feature tests were
  read against their task text on 2026-11-08. The hidden regression tests, mostly copied from
  oakridge, were not.
- Results depend partly on how a request is worded. On 2026-11-08, before any attempt ran, 6 task
  texts were reworded to describe behavior rather than where to make the edit: native compaction,
  single-item evidence, addressing check, restricted evidence, review shortcuts and default model.
  They still name the functions and routes that the hidden tests call.
- Tasks run in sequence and plans run one after another, which separates tasks and models in time.

## Review of failures

Same as the matched-task plan. Each candidate failure needs an attributed judgment bound to its
trace digest. Judgments never override a mechanical outcome, and they do not infer hidden
reasoning.

## Billing recovery

Same as the matched-task plan, with its later amendment applied from the start. Launch
authorization pre-approves `--accept-unknown`, within unchanged caps, for unknown charges from
`agent_deadline` attempts and from connection drops (`transport_failure`). Any other unknown
charge, or a bill above its reservation, stops for the user. No attempt is retried or replaced.

## Store

Run from `~/studies/assay-code-extension/scenario-library-2026-11/` on otto, where the evaluator's
Docker runtime lives, and copy the store to the same path on willie after each plan. Observations
stay outside this repository.

## Before launch

- Confirm this plan, then authorize `calibration.json` by its frozen digest. The study needs its
  own authorization after calibration.
- Both cohorts froze offline on 2026-11-08 with no blockers, using image
  `sha256:b48e43d170e6c0eb0d7e70364c2e385488c07f93ef8ea38f9942dc573cfba0da`. Calibration froze at
  `sha256:bc68cdf8cc9a1c392ecd0b61e9e8b5ada00cda47ca2362d6d319592ad75ef7cf` and the study at
  `sha256:6ef4c1f602abdb277c5aec447a09cc1a83ebd15f05adbddd2fafcd6625fdb61c`. Those digests were
  taken in a scratch store and are only a check. Freeze again in the real store before authorizing.
- Add the script that tallies results per task and model to the repository. The last study's
  tally scripts assume shapes and are not in the repository.
