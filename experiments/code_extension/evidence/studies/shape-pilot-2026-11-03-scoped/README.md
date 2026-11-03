# Hosted four-shape pilot with disclosed scope

**Completed.** See [ANALYSIS.md](ANALYSIS.md): all twenty retained candidates
passed independent offline replay; nineteen also completed submission normally.
The original unavailable grades, replay observations, retired calibration,
harness repairs, and all charges are recorded separately.

This replaces the retired `shape-pilot-2026-11-03` launch. Its first attempts
exposed a mismatch between the task's broad source-tree wording and the
enforced `src/compiler/` scope. The replacement explicitly tells the model
which directory prefixes are writable and that all other files are read-only.
This extra message is bound by the bridge configuration's message-prefix
digest, delivered through the production agent, and checked in the hosted
four-arm regression. The runtime fix is commit `2a7f859adfa5a1d5836cefba2fa13b75c173cf5f`.
The original frozen task, trees, tests, reference patches,
negative controls, model route, and per-attempt limits are unchanged.

## Frozen design and authorization

The operator authorized a twenty-attempt hosted pilot after reviewing the
study plan: five fresh attempts for each of `modular`, `central`,
`cross_module`, and `plugin`, all implementing the same `pass_through` stage
feature. The route is OpenRouter `openai/gpt-6.1-sol`, provider `azure/us`.
Each attempt has a 900-second, 60-request, $2 envelope. The replacement run's
total cap is $41.83, including its charged route probe; together with the
retired launch's $0.16010687, authorized spending stays below $42.

`config.json`, `plan.json`, and `launch-summary.json` freeze the inputs. Plan:
`sha256:05853531da547eee988576ccf763f8ad561be2db3b9221ac27a251c6f9611ee5`.
The working store is
`.assay/extension-studies/shape-pilot-2026-11-03-scoped/` at the repository root.
Dispatch uses concurrency one and the deterministic `subject-rotated-v1`
schedule. Seed 43 is metadata, not randomization. There are no automatic
replacement attempts. Provider failures preserve billed charges, and uncertain
billing halts further dispatch. Credentials are supplied only through the
transport environment.

## Analysis specified before dispatch

Report independently graded correctness and primary success out of five
planned attempts per shape, with completion, operational failures, and
unevaluated attempts shown separately. Secondary measures are time, requests,
tokens, costs, verification behavior, and scope of changes. Any human failure
judgment must identify its retained trace and reviewer. The charged probe is
included in total spending and excluded from the twenty study attempts.

This is one task with repeated attempts. Results are descriptive; no
significance tests or general architecture ranking are warranted. Three shapes
are authored adaptations, and edit count and navigation distance differ.
Additional matched, qualified tasks are needed for a broader study; the
existing inference profile requires ten common subjects. Retired calibration
observations are not pooled into these counts.
