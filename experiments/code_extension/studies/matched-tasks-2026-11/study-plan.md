# Matched-task study plan, November 2026

**Status:** Confirmed 2026-11-06. `calibration.json` has run. `study-with-sol.json` is
authorized from this file's commit, and every other cohort below still needs its own
authorization.

## Question

Do extension failures tied to code shape recur across feature requests and models? The
failure of interest is missed integration: code that is written but that normal dispatch
never reaches. The design keeps it separate from ordinary wrong behavior.

## What runs

Each cohort has a file in this directory, and each is its own authorization.

| Cohort file | Tasks | Models | Repeats | Attempts | Cap per attempt | Cap per plan | Combined cap |
|---|---|---|---:|---:|---:|---:|---:|
| `calibration.json` | 2 new | Ministral 14B, Qwen3.8 27B | 1 | 16 | $0.75 | $2.00 | $4.00 |
| `study.json` | 2 new | Ministral 14B, Qwen3.8 27B | 5 | 80 | $0.75 | $8.00 | $16.00 |
| `study-with-control.json` | 2 new, plus pass-through | Ministral 14B, Qwen3.8 27B | 5 | 120 | $0.75 | $8.00 new, $4.00 control | $24.00 |
| `third-model.json` | 2 new, plus pass-through | GPT-6.1 Sol | 5 | 60 | $2.00 | $15.00 | $15.00 |
| `study-with-sol.json` | 2 new, plus pass-through for Sol only | Ministral 14B, Qwen3.8 27B, GPT-6.1 Sol | 5 | 140 | $0.75, Sol $2.00 | $8.00, Sol $15.00 | $31.00 |

The new tasks add a `status_report` stage with a typed configuration and a
`collect_artifacts` stage using the existing artifact collection contract. Each runs under
all four shapes: `modular`, `central`, `cross_module` and `plugin`.

Every attempt is a fresh workspace and session, at concurrency one, under these bounds:
900 seconds, 60 requests, 8,192 output tokens per request and 32 KiB of tool output. No
tool-call limit is enforced. Timeouts and output-limit stops are outcomes under these
bounds, and changing either bound means a new cohort. Each plan makes one billed route
probe, inside its cap and not counted as an attempt.

## Calibration

Calibration runs first and measures difficulty, cost and time on the new tasks. Its
attempts are never pooled with the study.

A task may be replaced only if all 8 of its attempts passed, or all 8 failed. A pattern
between shapes is never a reason. A replacement needs its own qualification and a new
study plan.

## Attempt outcomes

Every planned attempt gets exactly one outcome, taken mechanically from retained records.
Apply the first row that matches.

| Outcome | Rule |
|---|---|
| Not dispatched | No attempt was claimed. It stays visible as missing. |
| Provider or harness failure | The stop maps to `harness_or_provider_failure`, or a submitted attempt has no usable grade. |
| Timeout | Stop cause `agent_deadline`, `harness_deadline` or `candidate_test_timeout`. |
| Limit stop | Terminal cause `output_token_limit`, `request_limit`, `conversation_limit` or `turn_limit`. |
| Scope or integrity stop | Stop cause `out_of_scope_edit`, `tampering` or another rejected workspace. |
| No submission | Any other attempt that ended without a submission. |
| Unusable patch | Submitted, but the patch was rejected or preflight failed, so the check groups did not run. |
| Reachability failure | Graded, and the `new_behavior` test titled `reachability:` failed. |
| Semantic failure | Graded, the reachability test passed and a test titled `semantics:` failed. |
| Unattributed feature failure | `new_behavior` failed with neither title failing. Each one is reviewed. |
| Regression only | `new_behavior` passed and a regression group failed. |
| Passed | The independent evaluator returned `correct`. |

The titles are read from the retained `new_behavior` group output. The reachability test
fails only when normal dispatch cannot find the stage, so a registered but wrong compiler
counts as reachable. A timeout is never a reachability failure.

An attempt the evaluator could not grade stays ungraded in the primary tables. A later
offline regrade is reported beside it, never in place of it.

## Measures

All counts are per task, model and shape, five attempts each.

| Measure | Numerator | Denominator |
|---|---|---|
| Yield (primary) | Passed | Dispatched attempts |
| Completion | Normally completed submissions | Dispatched attempts |
| Conditional correctness | Passed | Graded attempts |
| Reachability failures (shape question) | Reachability failure | Dispatched attempts, with the ungraded count beside it |
| Semantic failures | Semantic failure | Dispatched attempts, with the ungraded count beside it |
| Stops before grading (secondary) | Ungraded attempts that used all 60 requests, and timeouts, counted separately | Dispatched attempts |

Also show, for each group: every outcome above, feature, regression and build results,
duration, requests, tool use, measured cost and unknown-cost coverage. Operational failures
stay in every denominator except conditional correctness and are also broken out.

## Decision rule

The rule reads only mechanical outcomes, so review of failures cannot change it.

**Recurs:** for one model, on both new tasks, `plugin` has at least 2 reachability failures
in 5 attempts, and more than each of the other three shapes on that task.

| Result | Next step |
|---|---|
| Recurs | Continue to the seven further tasks. |
| Meets the rule on one task only | Review before committing to further tasks. |
| Meets the rule on neither task | Stop and review. |
| Each model and task pairing is 0 of 20 or 20 of 20 | Stop and review, because the cohort is at floor or ceiling. |

## Limits every report must state

- Repeats measure variation within a task. They are not independent tasks.
- At two or three tasks the results are descriptive, with raw counts and no significance
  tests. Ten tasks is the reporting threshold for paired inference, not a guarantee of
  power.
- Both new tasks share the compiler application and reuse pass-through's shape adaptations.
  `plugin` is one authored design, `stage-plugins.ts` with its JSON configuration, which
  does not exist at the upstream pin. These tasks cannot separate configuration-driven
  enablement in general from this one file being easy to miss.
- Shape is not the only difference between trees. Report file count, source size and
  navigation distance beside the results.
- `subject-rotated-v1` is deterministic, and its seed is metadata. It rotates shapes within
  a task but runs tasks in sequence, and plans run one after another, which separates
  models in time.

Pass-through differs from the new tasks in two ways. It has no agent-test namespace, so an
attempt that adds a test is rejected, and its feature tests are not titled, so it gives
yield but no reachability split. Report it beside the new tasks and never pool it with them.
Results from the November 3 pilot are historical and are not pooled either.

## Review of failures

Each candidate failure needs an attributed judgment bound to its trace digest before
`code_extension.run report` will render. Judgments go in the run's `run.json`, and the
reviewer is named there. Review each reachability failure against the retained patch, the
public requirements, the failed checks and the trace. Use `missed_integration_point` only
where that evidence supports it. Judgments never override a mechanical outcome, and they do
not infer hidden reasoning.

## Billing recovery

Launch authorization pre-approves `--accept-unknown` for unknown charges caused
by the agent deadline, within unchanged caps. Actual unknown costs stay recorded as unknown.

1. When a plan halts, run `code_extension.run status` and list its unknown charges.
2. The journal ties each request to its attempt, and the run manifest gives that attempt's
   stop cause. If every unknown charge belongs to an `agent_deadline` attempt, resume with
   `--accept-unknown`, then launch again for the plans after it.
3. Any other unknown charge, or a bill above its reservation, stops for the user.

No attempt is retried or replaced. A plan with no manifest, such as one whose process was
killed, cannot resume, and running its remaining attempts needs a new authorization.

## Store

Run from `~/studies/assay-code-extension/matched-tasks-2026-11/` on otto, where
the evaluator's Docker runtime lives, and copy the store to the same path on willie after
each plan. Copy the November 3 pilot stores there first, because their only copy is in a
disposable worktree. Observations stay outside this repository.
