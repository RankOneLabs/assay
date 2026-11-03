# Hosted code-shape pilot, 2026-11-03

**Retired launch; excluded from the code-shape comparison.** The first two
completed submissions were rejected for editing outside `src/compiler/`, but
the task said only to stay inside the source tree. The operator stopped the
launch after three attempt identities had been claimed, before the third made
a paid request. All 28 requests, including the probe, settled with known total
cost $0.16010687. No uncertain charge remains. `retired-run/` preserves the
interrupted archive; `attempts.jsonl`, `execution-result.json`, and
`verification.json` record its accounting and integrity. Its missing planned
coordinates are expected. These observations are harness calibration, not
model-accuracy results. The replacement cohort is
`shape-pilot-2026-11-03-scoped`.

The operator authorized this pilot in the study conversation after reviewing
the four-shape, twenty-attempt plan and its $2 per-attempt / $42 total caps.
The runtime is the implementation merged in PR #162, main commit
`7c532c3`. Credentials come from the existing project environment and are
excluded from study evidence.

## Frozen design

- Subject: `oakridge-dbos-stage-pass-through`, one matched feature request.
- Arms: `central`, `cross_module`, `modular`, and `plugin`, five fresh attempts
  each, with the same task instructions and correctness groups.
- Model: `openai/gpt-6.1-sol`, provider `azure/us`, through OpenRouter.
- Dispatch: concurrency one, `subject-rotated-v1`; seed 43 is metadata and
  does not randomize execution.
- Limits: 900 seconds and 60 requests per attempt, at most 8,192 output
  tokens per request. One charged route probe precedes study dispatch.
- Spend: at most $2 per attempt and $42 for the whole launch, including the
  route probe. Provider failures retain their charges. Unknown billing halts
  the run. Failed attempts are retained and are not silently replaced.
- Plan digest:
  `sha256:5e8b9e76c7f8d21b3ed99b4aab5f217d4356ce150cc91b5deec44310f3da1969`.

`config.json`, `plan.json`, and `launch-summary.json` are the frozen launch
inputs. The durable working store is
`.assay/extension-studies/shape-pilot-2026-11-03/` at the repository root;
the generated archive and reporting outputs will be retained after execution.

## Planned analysis

The primary outcome is independently graded correctness, reported as passed
out of five planned attempts per arm. Completion and operational failures are
reported separately. Secondary outcomes are duration, requests, token usage,
cost, verification behavior, and scope of changes. Trace-based failure
judgments must cite their evidence and reviewer identity.

This is descriptive evidence from one task. Repeats are not independent
subjects; no significance tests or broad code-shape ranking are warranted.
Three architectures are authored adaptations, and edit count and navigation
distance differ across arms. A broader study needs additional matched,
qualified tasks; the existing inference profile requires ten common subjects.
