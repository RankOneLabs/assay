# Supporting data: DRY consistency experiment

These details support [the case study](README.md). The full experiment record
is in
[`experiments/consistency_pilot/dry-experiment.md`](../../experiments/consistency_pilot/dry-experiment.md).

## Method

**Arms.** Each subject has two arms:

- The *clean* arm is the code as written.
- In the *inconsistent* arm, the helper's existing callers inline its logic.

Nothing else differs between the arms. That includes the helper, the target
file and the instruction.

**Calls.** The model gets the instruction and the repository in a single
provider call per cell.

**Verdicts.** Each output gets two verdicts:

- **Structural evaluator v7** labels it from the code:
  - *reused*: it calls the helper;
  - *duplicated*: it calls the helper's building blocks without the helper;
  - *mixed*: it does both;
  - *ambiguous*: neither verdict can be decided.
- **Functional correctness v4** runs hidden test cases in a Docker sandbox.
  Correctness is reported separately and never filters the structural
  verdict.

**Grid and statistics.**

- Each subject × arm cell runs twice.
- Arms are compared per subject with an exact paired sign test at alpha 0.05.
- Ties do not count toward the sign test.
- A subject with an unscored cell drops out of the paired comparison.

**Real-code subjects.** The 11 subjects come from three slices, each copied
unchanged from a pinned commit:

| Family | Slice | Helpers |
| --- | --- | --- |
| `jig-llm` | jig `llm` adapters, 5fa9c01 | `parse_tool_arguments`, `wrap_llm_error`, `merge_completion_kwargs`, `stamp_cost` |
| `jig-feedback` | jig graders and tracers, 5fa9c01 | `strip_markdown_fence`, `validate_scores`, `parse_aware_utc` |
| `scout-platforms` | scout platform adapters, ee8c901 | `derive_source_key`, `source_since`, `parse_platform_ts`, `parse_retry_after` |

**Reproducing a run.**

```bash
cd experiments && uv run --env-file ../.env python -m consistency_pilot.run_dry \
    gpt-6.1-sol ../.assay/dry-codebase-near-gpt-6.1-sol-v1 codebase-near
```

Stored outputs can be rescored offline, without any model calls.

## Synthetic dose results

Reused / duplicated cells out of 24, for 12 subjects × 2 repeats:

| Inline callers | Sol | Sonnet | Gemini | Haiku 4.5 |
| --- | --- | --- | --- | --- |
| 0 of 10 | 24 / 0 | 23 / 0 | 21 / 2 | 15 / 6 |
| 1 of 10 | 24 / 0 | 23 / 0 | 20 / 4 | 10 / 10 |
| 3 of 10 | 22 / 2 | 24 / 0 | 17 / 6 | 14 / 9 |
| 5 of 10 | 20 / 4 | 21 / 0 | 15 / 8 | 11 / 10 |
| 7 of 10 | 24 / 0 | 23 / 0 | 15 / 9 | 10 / 11 |
| 10 of 10 | 2 / 22 | 14 / 9 | 0 / 23 | 2 / 19 |

Other synthetic variants:

- **Placement.** Clustering the inline callers directly above the insertion
  point cost Sol and Sonnet at most 3 of 24 cells. Gemini duplicated in 6 of 8
  subjects once 5 or more callers were inline.
- **Chains.** Five sequential additions did not snowball. Regressions stayed
  at 0–2 subjects per step and did not grow.
- **Context.** Padding the repository to about 30 KB or 90 KB left reuse flat.

## What duplication costs

These are standard tools run on 988 synthetic frontier outputs: 788 reused and
200 duplicated. Each figure is the mean change per output.

| Metric | Reused | Duplicated |
| --- | ---: | ---: |
| SLOC (radon) | 2.4 | 6.3 |
| Cyclomatic complexity (radon) | 1.0 | 2.2 |
| Cognitive complexity (complexipy) | 0 | 1.2 |
| Halstead volume (radon) | 11 | 41 |
| New duplicated lines (jscpd) | 0.05 | 3.4 |

- **Route views carry the cost.** A duplicated route view adds 11.2 SLOC
  against 3.0 for a reused one. Every duplicated route view is a jscpd clone.
- **One-line duplicates cost nothing measurable.**
- **Ruff and mypy findings do not separate the two verdicts.**

## Real code, same-file variant by subject

Reused cells out of 2, as clean / inconsistent:

| Subject | Haiku 4.5 | Gemini | Luna | Sol |
| --- | --- | --- | --- | --- |
| tool-args | 1 / 2 | 2 / 2 | 2 / 2 | 2 / 2 |
| llm-error | 0 / 1 | 2 / 2 | 2 / 2 | 2 / 2 |
| request-kwargs | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| usage-cost | 0 / 0 | 0 / 0 | **2 / 0** | **2 / 0** |
| judge-reply | 2 / 2 | 2 / 2 | 2 / 2 | 2 / 2 |
| judge-scores | 0 / 0 | 1 / 0 | 0 / 0 | ambiguous |
| span-time | 0 / 0 | 2 / 2 | 2 / 2 | 2 / 2 |
| source-key | 0 / 0 | 0 / 0 | 2 / 1 | 2 / 2 |
| source-boundary | 1 / 2 | 0 / 0 | 1 / 2 | 2 / 2 |
| status-time | 2 / 2 | 2 / 2 | 2 / 2 | 2 / 2 |
| retry-delay | 0 / 0 | 2 / 2 | 2 / 2 | 2 / 2 |

## Correctness and cost

| Run | Haiku 4.5 | Gemini 3.1 Pro | GPT-6 Luna | GPT-6.1 Sol |
| --- | --- | --- | --- | --- |
| Imports the helper | 8 of 9 per arm | — | 11 of 11 | 11 of 11 |
| Same-file neighbour | 7 of 10 per arm | 10 of 11 | 11 of 11 | 11 of 11 |
| Cost per 44-cell run | about $2 | $4–5 | $0.12 | $2.28 |

## Limits

- **Power.** With 10–11 subjects × 2 repeats, only large arm effects are
  detectable. Many ties mean "no detected difference", not equivalence.
- **Model comparison.** It was not planned in advance and is exploratory.
- **Coverage.**
  - Gemini did not run on the helper-import variant.
  - Sol did not run on the no-import variant.
- **Floor subjects.**
  - Every model duplicated `request-kwargs` in every cell. This has not been
    investigated.
  - `judge-scores` needs `Score` objects that the task never provides, so
    models write the range checks by hand. The evaluator cannot classify a
    bare range check either way.
- **Evaluator.** v6 rejected idiomatic type hints such as
  `dict[str, Any] | None`. That hit 16 of 44 Haiku cells. All runs were
  rescored with v7.
- **Provider.** At peak load, Azure returned HTTP 200 with an error body for
  large prompts. That stopped two Luna runs under the budget guard; the
  reported Luna runs were rerun off-peak.
- **Scope.**
  - Python only.
  - One function per task, in a single model call.
  - No agent loop or repository search.
