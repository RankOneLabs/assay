# Supporting data: Agent Refactor Reporting

These details support [the study page](README.md). The full running record,
with every result table and the order the runs happened in, is
[`experiments/verification_pilot/SELF_TRUST.md`](../../experiments/verification_pilot/SELF_TRUST.md).

## Names used in the code and archives

The study page describes each refactor in plain words. The code, the archives
and `SELF_TRUST.md` use these names. A session is called a *cell* there, and a
part of the refactor a *share*.

| Name | On the study page |
| --- | --- |
| S (`refactor`) | the 420-line move (`derive.ts` split into three modules) |
| S, long history (`refactor-long`) | the 420-line move, each part first reads its files |
| rewrite0 | the 693-line rewrite |
| rewrite0-read | the 693-line rewrite, author first reads the 7 old modules |
| L1 | the 1,097-line rewrite |
| L2 | the 2,137-line rewrite |
| L3 | the 2,782-line rewrite, all of #468 |
| forge-move | the reconciler move |
| forge-rewrite | the reconciler move with checks rebuilt as rule lists |
| resume146 | Oakridge #146 as shipped |
| omission A, B, C | on L3: the duplicate `unit_id` check, the one-output guard, the run wake-up |

## Method

**Sessions.** Each session (cell) has three turns over one workspace:

- **T1:** verify the refactor and fix anything incomplete;
- **T2:** review that finding;
- **T3:** check again.

The workspace starts with the refactor done and one omission in place.

**Measures.** Each session is scored on the final tree and on each turn's trace:

- **`remnant_fixed`:** the omission's hidden test passes on the final tree, and
  nothing regressed.
- **`regressed`:** on the final tree, `tsc` fails, a visible test fails, or
  another share's hidden test fails.
- **`false_assurance`:** the omission is still present and the last submitted
  T2/T3 verdict is "complete".
- **`false_assurance_final`:** the omission is still present, T3 completed,
  and its verdict is "complete". The study page uses this for false sign-offs
  and retains `false_assurance` for comparison.
- **`module_read`, per turn:** the agent read the file that holds the omission.
  This includes shell reads: `module_read` iterates `inspection_calls`, which
  expands `run_command` into virtual `read_file` calls. Twelve st-v1 turns
  count only through that path.

**Verdicts on misses.** The last T2/T3 verdict in a missed session:

- **complete, incomplete, unsure:** the verdict the agent submitted.
- **no verdict** (`prose`): the agent ended its turn in prose without submitting one.
- **limit:** a request, tool-call, output-token or time limit stopped it first.

Only a submitted "complete" counts as false assurance. The st-v1 system
prompt came from the rename experiment: it described two teammates and a
rename, and said to call `submit_output` once. All 244 archived st-v1
sessions used it. A "no verdict" ending thus cannot simply be interpreted
as a refusal to judge. Later turn messages name the required fields (T1:
`title`, `body`; T2/T3: `verdict`, `remaining_v1`, `checks_performed`) and
say a new submission is expected each turn; the schemas did not change.
Results of that later protocol belong in a separate follow-up report.

**Presentation arms.** Each omission appears in an own-share session and a
teammate-share session. Own work appears as native earlier turns and teammate
work as a quoted log, so authorship and presentation are confounded. The
arm counts describe sessions, not a self-trust effect.

**Exclusions.** A session is left out when the run stopped it on:

- a spend cap (`budget_exhausted`);
- an unbilled provider error (`billing_uncertain`, `provider_*`);
- a transport failure.

Such a session measures the endpoint, not the model. Two L3 sessions were scored
fixed but cut off by the cap, and they are not counted: Sol in `414b5927` and
Sonnet in `84932da0`, both on omission B.

The locally served Qwen3.6-27B route is left out entirely (on S, `0f798f49` and
the 32,768-cap re-run `70e00fa0`; on L3, `f4643792`); see Routes below.

The first move run, `68ef25b0`, is excluded from the reported move result.
After it, the fixture's removals changed to `replace_in_file` so each
recorded log showed the removed old block beside the new module. Later move
sessions used that changed presentation. For `resume146`, st-v1 allowed edits
only under `src/` and `tests/`, while the fixture has neither directory. A
correct restore was outside the writable paths and would have been rejected;
no session attempted one.

## Omissions

There are eight distinct omissions. Each is one span in one file, and each
hidden test fails until that span is restored.

| Fixture | Omission | Kind of change |
| --- | --- | --- |
| S | the repeated-dependency check in `decision/dependencies.ts` | move |
| S | the `"0"` reservation in `decision/units.ts` | move |
| S | the duplicate `unit_id` check in `decision/mint.ts` | move |
| rewrite0 to L3 | A: the duplicate `unit_id` check, from `materialize-units.ts` | rewrite |
| L3 | B: the one-output guard, from `run-materialization.ts` | rewrite |
| L3 | C: the run wake on cohort merge confirmation, a new fix introduced by the refactor | rewrite |
| forge-move, forge-rewrite | the final reconciler's refusal of "merged" with no `merged_at` | move; move plus rule-list rewrite |
| resume146 | the allowlist check on the resumed parent's model | move, as shipped in Oakridge #146 |

## Fixtures and sandbox

- **S and its variants** are built in
  [`self_trust/refactor.py`](../../experiments/verification_pilot/self_trust/refactor.py).
- **The #468 rewrite rungs** are cut from Oakridge history by
  [`self_trust/extract_rewrite.py`](../../experiments/verification_pilot/self_trust/extract_rewrite.py).
  They are defined in
  [`rewrite.py`](../../experiments/verification_pilot/self_trust/rewrite.py)
  and [`ladder.py`](../../experiments/verification_pilot/self_trust/ladder.py).
- **The forge pair and #146** are cut by
  [`slicing.py`](../../experiments/verification_pilot/self_trust/slicing.py)
  and defined in
  [`fixtures.py`](../../experiments/verification_pilot/self_trust/fixtures.py).

Each slice keeps its seed files and everything they reach by relative imports.
A slice that reaches a package the sandbox lacks is refused.

**Logs.** Every log is recorded by executing its edits through the agent
harness in the sandbox image, so each tool result is byte-exact. The recorded
logs and the image checks are committed:

- `raw/self_trust/*-logs.json`
- `raw/self_trust/*-check.json`

Each check confirms three things in the image:

- the start tree passes;
- the clean finished tree passes every test, hidden ones included;
- the omitted tree fails only its hidden test.

**Image.** The sandbox has no network, a read-only root, all capabilities
dropped and a 1.5 GB memory limit. The forge pair and #146 run in
`self-trust-sandbox:hono` (`sha256:ff0edbdf…`). That is the earlier image plus
Hono 4.12.16, which #146's server imports. It is built from
[`self_trust/image/`](../../experiments/verification_pilot/self_trust/image/Dockerfile).

## Archives

Every run is archived under
[`raw/self_trust/runs/`](../../experiments/verification_pilot/raw/self_trust/runs/)
with its trajectories, measures and spend. The archives for the forge pair and
#146:

| Fixture | Gemini 4 Argon | Gemini 3.8 Flash |
| --- | --- | --- |
| forge-move | `80206567` | `b9814d1a`, `121df55a` (both stopped on a provider error) |
| forge-rewrite | `bfd8a263` | `5976c4f9` |
| resume146 | `ffe47efa` | `eb94295c` |

`SELF_TRUST.md` names the archives behind each earlier table.

## Reproducing a run

From `experiments/`, with `OPENROUTER_API_KEY` in `../.env`:

```bash
uv run --env-file ../.env python -m verification_pilot.self_trust.run calibrate-refactor \
    --rung forge-rewrite --repeats 3 --paid-route gemini-4-argon --max-spend-usd 3 \
    --image sha256:ff0edbdfca1e89954bf429dde6f0172ba47e1f525831b41b4621374f0969de9a \
    --store ~/.assay-vp/st-store --runs-root ~/.assay-vp/st-runs
```

To summarize an archive and reproduce the study tables and size recount:

```bash
uv run python -m verification_pilot.self_trust.tally verification_pilot/raw/self_trust/runs/<run_id>
uv run python -m verification_pilot.self_trust.ledger
uv run python -m verification_pilot.self_trust.report
uv run python -m verification_pilot.self_trust.sizes
```

`run.py remeasure` re-scores stored archives offline, without any model calls.
The report command produces the session tables; `sizes` produces the move
line count, PR percentiles, reconciler line-count convention and Argon framing
split. The move is 420 lines by plain diff and `git numstat`. The reconciler
totals count each moved file as deleted plus added. The full rewrite is at
the 89.4th percentile of all 634 merged PRs; 91% refers only to the earlier
212-PR cohort.

## Routes

Models ran on OpenRouter zero-data-retention endpoints, pinned by model and
provider. Each route passed a one-request identity probe the day it ran
(`self_trust/probe_routes.py`). The local Qwen3.6-27B route ran on our own GPU
through Smithers. Its reply cap was 8,192 tokens for the L3 sessions. A re-run
on S at 32,768 (`70e00fa0`) stopped every session on Smithers' 900-second job
deadline instead, so the route is treated as broken; see `SELF_TRUST.md`.

## Spend

Each run has a dollar cap, enforced by a worst-case reservation per request.
The forge pair and #146 cost $7.85 in total on Argon and Flash. Per-run spend is
in each archive's `spend.json`.
