# Matched-task study: results

Run 2026-11-06 to 2026-11-07 from the cohort in `study-with-sol.json`
(`sha256:730ddd24f8b096a9bbb9e39f2c08bbb6dcdf77e3705b6f1521f76524538b20c3`), under
`study-plan.md` as amended. All 140 planned attempts were dispatched. The control cohort was
not run.

## Summary

The code shape made no visible difference. In 140 attempts no model ever left the new stage
unreachable or left it out. Every failure was wrong behavior inside the stage, code that did
not type-check, or an attempt that stopped before it submitted. The decision rule gives **stop and review**.

## Cost

| Model | Attempts | Measured | With unknown charges at their bound | Cap |
|---|---:|---:|---:|---:|
| Ministral 14B | 40 | $2.16 | $2.16 | $8.00 |
| Qwen3.8 27B | 40 | $3.40 | $3.67 | $8.00 |
| GPT-6.1 Sol | 60 | $5.68 | $6.10 | $15.00 |
| Total | 140 | $11.24 | $11.93 | $31.00 |

## Outcomes per model and task

Each row is 20 attempts: 5 repeats of each of 4 shapes. "Stopped" attempts were never graded.

| Model | Task | Passed | Wrong | Stopped at 60 requests | Timed out (900 s) | Infrastructure stop | Mean requests |
|---|---|---:|---:|---:|---:|---:|---:|
| Ministral | status report | 16 | 2 | 2 | 0 | 0 | 43.9 |
| Ministral | collect artifacts | 0 | 14 | 5 | 0 | 1 | 48.0 |
| Qwen | status report | 16 | 0 | 1 | 3 | 0 | 36.0 |
| Qwen | collect artifacts | 4 | 1 | 8 | 7 | 0 | 29.1 |
| Sol | status report | 20 | 0 | 0 | 0 | 0 | 12.2 |
| Sol | collect artifacts | 19 | 0 | 0 | 0 | 1 | 15.8 |
| Sol | pass-through | 18 | 0 | 0 | 0 | 2 | 9.2 |

Sol passed all 57 attempts it submitted. Its 3 ungraded attempts are the connection drops
below.

## Passes by shape (out of 5)

| Model | Task | central | cross_module | modular | plugin |
|---|---|---:|---:|---:|---:|
| Ministral | status report | 3 | 4 | 5 | 4 |
| Ministral | collect artifacts | 0 | 0 | 0 | 0 |
| Qwen | status report | 4 | 3 | 4 | 5 |
| Qwen | collect artifacts | 2 | 1 | 1 | 0 |
| Sol | status report | 5 | 5 | 5 | 5 |
| Sol | collect artifacts | 4 | 5 | 5 | 5 |
| Sol | pass-through | 5 | 4 | 4 | 5 |

## Feature failures

| Kind | Ministral | Qwen | Sol |
|---|---:|---:|---:|
| Stage written but unreachable | 0 | 0 | 0 |
| Stage never written | 0 | 0 | 0 |
| Reachable, wrong behavior | 13 | 1 | 0 |
| Did not type-check, so no tests ran | 3 | 0 | 0 |
| Not attributed | 0 | 0 | 0 |

The 3 that did not type-check are Ministral's first repeat on collect artifacts `central`
and on status report `central` and `plugin`. They are Ministral's only wrong answers on
status report. No regression test failed in any attempt. The failing hidden tests on
collect artifacts:

| Failing test | Ministral | Qwen |
|---|---:|---:|
| Does not reject unknown configuration fields | 11 | 0 |
| Accepts `id_path: "/"`, which names no field | 7 | 1 |
| Collection, executor configuration, output release and attention all wrong (5 tests together) | 2 | 0 |

## Decision rule

1. Incomplete: no. Every shape has 5 dispatched attempts on each new task.
2. Floor or ceiling: no. Ministral on collect artifacts (0 of 20) and Sol on status report
   (20 of 20) are at the edges, but not every model and task pairing is.
3. Recurs: no. `plugin` has 0 unreachable-stage failures for every model on both tasks.
4. One task only: no.
5. Neither task: **stop and review**.

## Unknown charges

- Qwen: 9 timeouts left a charge unknown. Each was accepted at its bound under the
  pre-approval for timeouts. The extra $0.27 over the measured cost is these.
- Sol: 3 requests lost their connection, 2 before connecting and 1 mid-response. The bounds
  were $0.106, $0.146 and $0.164, $0.42 in total. The user approved the first two one at a
  time and the third under a standing approval for connection drops within the $15 cap.

## Limits

- Repeats measure variation within a task. They are not independent tasks.
- Three tasks, so these results are descriptive: raw counts, no significance tests.
- All three tasks add a stage to the same compiler. They share the shape adaptations,
  including the single authored `plugin` design, so they cannot separate configuration-driven
  enablement in general from that one file.
- The shapes change only about 20 lines of registration in a tree of 62 to 64 files and
  about 349 KB. File count, size and reference patch size per shape are in each fixture's
  README.
- Tasks ran in sequence and plans ran one after another, so models are separated in time.
- Qwen's route was slower in the study than in calibration: the 90th-percentile time per
  request rose from 48.5 s to 68.8 s with the median about unchanged, and on status report
  the mean time per request roughly doubled. Cost per attempt did not rise. This may explain
  some of its 10 timeouts. The route listing showed full uptime throughout.

## Data

- Store: `~/studies/assay-code-extension/matched-tasks-2026-11` on otto, copied to willie.
- Plans: Ministral `sha256:6262cc6aa376e90d5761056c1d0bd423491c3b8fbe4b5ef98c65cdce95fc969e`,
  Qwen `sha256:fca2634bc9c898442456a4fa821ef53a102bfac6792c755ecb5e339304d11610`, Sol
  `sha256:180cf567c0c8f24c686ee9b723aea362a01cd15c35131511df968a00aa6b6742`.
- Rows come from `uv run python -m code_extension.reachability --store <store> --plan <plan>`.
  The tables were tallied with scripts in
  `~/studies/assay-code-extension/matched-tasks-2026-11-tools/` (`results_table.py`,
  `failed_tests.py`), which are not yet in the repo.
