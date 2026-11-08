# Scenario library study: plan (draft)

Status: draft, 2026-11-07. Only the outcome rule below is settled. It was settled before
any library task was qualified. Models, attempt counts, budgets and the decision rule are
not decided yet.

## What changes from the matched-task study

The matched-task study gave each task several hand-made code shapes. This study does not.
Each library task keeps the one shape the real code has, and shapes are compared between
tasks. Every task is cut from oakridge commit `1495ec34`.

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
