# Hosted code-shape pilot results

All 20 retained candidates passed the frozen independent checks during offline replay. Nineteen also completed the required submission protocol; one plugin attempt omitted `submit_output`. That recovered patch passed too, but remains a protocol failure.

| Shape | Planned | Normal submissions | Candidates passing replay | Submitted and passing replay |
|---|---:|---:|---:|---:|
| modular | 5 | 5 | 5/5 | 5/5 |
| central | 5 | 5 | 5/5 | 5/5 |
| cross_module | 5 | 5 | 5/5 | 5/5 |
| plugin | 5 | 4 | 5/5 | 4/5 |

This is one matched task, with five repeats per shape and one hosted model (`openai/gpt-6.1-sol`, provider `azure/us`). The result shows a ceiling on the tested correctness checks. It supports no general architecture ranking or significance claim. Three shapes are authored adaptations.

## Runtime and evidence recovery

The original launch finished all 20 worker attempts. Its 19 submitted candidates received unavailable grades because the launch grader expected Docker client `29.6.1`, while the host ran `29.9.0`; the server was `29.1.2`. Those records are preserved in the original archive and generated report. Their zero recorded passes reflect unavailable grading, not evidence that the implementations were incorrect.

The offline replay uses the existing qualification profile: the same pinned image, frozen visible/hidden test groups, Docker client `29.9.0` and server `29.1.2`, 60-second candidate checks and a 300-second evaluator deadline. The failed launch profile used 10 and 120 seconds respectively. No tests or candidates were edited. All 20 replay records include runner settings, candidate identities, group outputs, and links to the original executions. No additional model calls were made.

The original archive also omitted its frozen test-group objects. They were restored byte-for-byte from the durable working store, checked against the retained fixture manifest digests, and retained in `fixture-assets.json`. The corrected launcher now retains these assets before dispatch and includes them in future plan/export closures. The legacy core export verifies original execution integrity; its supplemental fixture inventory separately binds the restored replay dependencies.

A prior launch was retired because the instructions failed to disclose the enforced `src/compiler/` scope. Its evidence and $0.16010687 charge are retained separately and excluded from these counts. The corrected pilot disclosed scope and limits in a configuration-bound message before each attempt.

## Spending and observed effort

The study launch cost **$1.45258630**, including a $0.0006798 route probe. Combined with the retired launch, total API spend was **$1.61269317** against the $42 authorization. All 229 requests settled with known costs; no uncertain charge or automatic replacement attempt remains.

| Shape | Median attempt seconds | Median requests | Attempt API cost, USD |
|---|---:|---:|---:|
| modular | 54.99 | 9 | 0.35883089 |
| central | 58.63 | 9 | 0.35911007 |
| cross_module | 65.45 | 10 | 0.36817803 |
| plugin | 95.87 | 10 | 0.36578751 |

Durations include provider latency and tool execution. Five repeats of one task cannot establish a shape effect on time or cost. Dispatch was deterministic and rotated across repeats, not randomized.

## Measurement interpretation

File footprints include configuration files as well as source files. The plugin implementations edited both the compiler and JSON registration. Cross-module implementations used a new compiler helper plus registration rather than editing the reference compiler file. Paths outside the reference edit set are therefore a proxy, not proof of unnecessary work. Files inspected through shell commands are not counted by the `read_file`-only inspection measure. An unavailable external grade leaves self-assessment agreement unavailable.

Failure judgments in the original index are attributed to Codex automated trace review, not a human reviewer. The plugin protocol omission maps to the existing `wrong_abstraction_or_plan` taxonomy; replay establishes that its retained code passed the tests despite the missing submission call.

## Reproduction and next study

The per-attempt table and replay record digests are in [analysis.json](analysis.json) and [analysis.csv](analysis.csv). Original accounting and traces remain in [the retained run](../../runs/extension-ddad66121cb372922ed7/run.json). Append-only observations are in [offline-replay/regrades](offline-replay/regrades). The [original report](original-report/REPORT.md) deliberately retains the failed first grading observations.

From `experiments/`, regenerate the original report with `python -m code_extension.publish --write`. Replay the committed candidates with:

```sh
python -m code_extension.run regrade \
  --archive code_extension/evidence \
  --image sha256:d0da319d2e141415c1c41ccea44983e8986944e5ae45b53652a9c104c462c4ee \
  --output ../.assay/extension-studies/reproduced-shape-pilot
```

Use the existing pinned runtime image and locked reporting toolchain; this command makes no model requests. A broader study should freeze additional matched tasks with a useful range of difficulty, then select a hosted model matrix and spending caps. The current inference profile requires ten common subjects; these repeats remain one subject. No additional paid study has been started.
