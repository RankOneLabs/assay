# DRY consistency experiment

From the repository root, start a Python session with
`cd experiments && uv run python`, then use the library API below.

This experiment asks whether an agent is more likely to reuse an existing
abstraction when the surrounding repository consistently reuses it than when an
otherwise equivalent repository duplicates the primitive operation.

The primary outcome is ordinal abstraction use: `duplicated < mixed < reused`.
Finite-case functional correctness is a separate secondary diagnostic:
`incorrect < correct`. Correctness does not replace, filter, or validate the
primary verdict, and it is not a second confirmatory hypothesis. Keeping the two
reports separate avoids turning passing tests into evidence of abstraction reuse
or treating reuse as proof of correctness.

## Frozen design

- Twelve synthetic, arm-invariant coding tasks are balanced across cosmetic,
  architectural, and semantic families (four each). The tasks are controlled
  probes, not a representative sample of production software engineering.
- Clean and inconsistent arms differ only in whether `existing_feature` calls an
  available helper or repeats its primitive implementation. The requested new
  `implement` function and helper are otherwise the same across arms.
- Each subject/arm cell has two worker repeats. Each successful output receives
  one deterministic structural verdict and one deterministic correctness verdict.
- Worker execution is concurrency one and blocked by subject. The declared
  `subject-counterbalanced-v1` schedule reverses arm order across subjects and
  repeats, preventing one arm from always running first. After all 48 worker
  cells finish, the execution engine runs their evaluations.
- The worker makes at most one provider call per cell. Forty-eight cells therefore
  authorize at most 48 requests; no parse or run retry can add a second call.
- The primary report uses the preregistered `paired-v2` exact paired sign test,
  alpha 0.05, and the lower ordinal median across two worker repeats. With two
  repeats, disagreement resolves conservatively to the lower category. The
  minimum inference set is ten complete paired subjects.
- Ties do not contribute to the exact sign test. At alpha 0.05, a result needs
  at least 6 non-tied pairs all in one direction, 8 of 9, 9 of 10, 10 of 11, or
  10 of 12. A null result with many ties is weak detection power, not affirmative
  evidence that the arms are equivalent.

The task declarations include hidden test vectors and reference implementations.
The module-level `render_input` function exposes only the instruction and arm-specific
`module.py`; it does not expose task IDs, families, evaluator hints, reference
answers, test vectors, or arm IDs to the model. Those hidden fields remain bound
into the subject digest and available to evaluators.

The structural evaluator (version 5) decides automatically in two cases. If
`implement` calls the helper in a statement that runs whenever control reaches
it, the verdict is `reused`, or `mixed` when it also calls any primitive the
helper uses. Early-return guards before that statement are allowed, and so are
the bodies of `try` and `with`. If `implement` never names the helper but calls
one of its primitives, the verdict is `duplicated`. Helper calls only inside
branches, loops, lambdas, comprehensions or short-circuit operands are
`AmbiguousStructure`. So are aliases, local rebinding of the helper name, and
code that calls neither the helper nor a primitive. Without an ambiguity judge,
`AmbiguousStructure` is missing evidence. Both worker repeats must be present
for both arms, so any such missing cell makes the subject incomplete and removes
it from the paired comparison. Version 4 required the whole body to be a single
`return` expression. It rejected ordinary `result = helper(value); return
result` code even though the prompt allowed it.

## Layered scenario set

`scenario="layered"` swaps in twelve multi-file subjects from
`assay.investigations.layered_fixtures`. The grid, schedule and reports are the
same as v1. The reusable unit lives outside the target file, and only the target
file differs between arms:

- `route-view` (4 subjects). In the clean arm, `routes.py` delegates each route
  to a view in `views.py`. In the inconsistent arm, routes inline the lookup,
  validation, persistence and serialization. The task adds the route for a view
  that exists but has no route yet. The primitives are the store and serializer
  calls.
- `domain-rule` (4 subjects). Existing callers either use a composite business
  rule, such as `order_total`, or rebuild it from its building blocks. The task
  needs the composite's result. The test cases make naive shortcuts (a subtotal
  instead of the total, gross pay instead of net) fail.
- `cross-module` (4 subjects). A one-line value helper lives in `utils.py`, next
  to distractor helpers. The target either imports it for three callers or
  inlines it three times.

These subjects may import the helper, but only from its declared
`helper_module`. The layered profiles use a prompt that drops the "exactly one
return statement" constraint, because an inlined route cannot meet it.

```bash
cd experiments && uv run --env-file ../.env python -m consistency_pilot.run_dry \
    sonnet-5.5 ../.assay/dry-layered-sonnet-5.5-v1 layered
```

## Dose-response scenario set

`scenario="dose"` asks how much bypassing code it takes before a model follows it.
It uses the same twelve layered subjects and tasks, but each target file has ten
existing callers of the reusable unit. Arm `mess-NN` writes NN of those callers
inline; the other callers go through the abstraction. There are six arms:
`mess-00`, `mess-01`, `mess-03`, `mess-05`, `mess-07` and `mess-10`.

- Only the target file differs between arms, and it imports only what its
  callers use.
- Messy positions are nested, so each level contains the level below it. They
  are spread through the file, and the last caller (the one nearest the
  appended code) stays clean below `mess-10`. A model that follows the mess
  cannot just be copying the function right above its insertion point.
- The report compares every mess level with `mess-00` using the same paired
  sign test. `regressed` counts subjects that reused less at that mess level.
- The grid is 12 subjects × 6 arms × 2 repeats = 144 cells. The
  `subject-rotated-v1` schedule starts each subject/repeat block one arm later.

```bash
cd experiments && uv run --env-file ../.env python -m consistency_pilot.run_dry \
    gpt-6.1-sol ../.assay/dry-dose-gpt-6.1-sol-v1 dose
```

## Placement, chain and context scenario sets

These three sets reuse the dose subjects and change one thing each.

- `scenario="placement"` puts the messy callers together at the end of the
  file, directly above the insertion point. Arm `tail-NN` makes the last NN
  of the ten callers inline. The arms are `mess-00`, `tail-01`, `tail-03`,
  `tail-05`, `tail-07` and `mess-10`, so the grid is again 144 cells.
- `scenario="chain"` asks for five sequential additions per cell instead of
  one. Each step appends the previous output to the target file under its
  step name, so later steps see the model's own earlier code. The arms are
  `mess-00`, `tail-03` and `tail-07`. There is one abstraction report per step
  (`abstraction-1` to `abstraction-5`), and correctness is not run.
- `scenario="context"` starts every arm from the `tail-07` file. It adds
  unrelated support modules until the repository is about 30 KB (`ctx-30`) or
  90 KB (`ctx-90`); `ctx-00` is unpadded. The padding never mentions the
  helper. Correctness does not run for `ctx-90`, because those repositories
  exceed the sandbox storage budget. The abstraction verdict is unaffected.

## Code metrics

`python -m consistency_pilot.code_metrics <store> [reference-arm]` measures
every stored `implement` function. The measurements are:

- non-blank lines and statements
- cyclomatic complexity and nesting depth
- fan-out (distinct callees) and imports
- magic numbers
- clone similarity: token similarity to the closest existing function in the
  target file
- new ruff findings (`E9,F,B,SIM`)

Each arm is compared with the reference arm per subject, using the same sign
test. The metrics are computed from source only, so they can be rerun on any
stored result at no cost.

## Results so far (2026-09-30)

Verdict counts are over 24 cells (12 subjects × 2 repeats), scored with v5.
"Flipped" means a paired sign test at p < 0.05 against the clean arm.

**Single-file v1 set.** In the clean arm, Haiku 4.5 duplicated in 10 of 12
subjects. It ignores a one-line helper even when every caller uses it, so the
consistency manipulation has nothing to act on. This is a floor effect, not
drift. Sol reused in every cell of both arms. Gemini reused in every
complete clean subject; in the inconsistent arm it duplicated in 5 subjects, plus 1 split pair.
Sonnet reused in 9 of 12 clean subjects and duplicated in 5 inconsistent
ones.

**Dose (mess spread through the file), reused / duplicated:**

| mess | Sol | Sonnet | Gemini |
|---|---|---|---|
| 0/10 | 24 / 0 | 23 / 0 | 21 / 2 |
| 1/10 | 24 / 0 | 23 / 0 | 20 / 4 |
| 3/10 | 22 / 2 | 24 / 0 | 17 / 6 |
| 5/10 | 20 / 4 | 21 / 0 | 15 / 8 |
| 7/10 | 24 / 0 | 23 / 0 | 15 / 9 |
| 10/10 | 2 / 22 | 14 / 9 | 0 / 23 |

- Sol and Sonnet hold until the whole file bypasses the abstraction. Sol then
  follows the mess almost completely (22 of 24). Sonnet does too for route
  views (7 of 8), but it keeps importing cross-module helpers.
- Gemini degrades gradually, and only on one-line cross-module helpers: 6 of 8
  reused with no mess, 4 with 1/10, 1 with 3/10 and none from 5/10. Its views
  and rules hold until 10/10.

**Placement (mess clustered above the insertion point).** Up to 7 of 10
inline callers directly above the insertion point cost at most 3 of 24 cells
for Sol and Sonnet (21 / 3 at `tail-07`, all route views). Neither result is
significant.

**Chains of five additions.** There is no snowball. Sol slipped on 2 subjects
at step 1 of `tail-07`, then reused everywhere for steps 2–4, and had 1
regression per messy arm at step 5. Sonnet had at most 1 regressed subject
per step in `tail-07`, and none in `tail-03`.

**Context size.** Padding the `tail-07` repository to about 30 KB or 90 KB
changed nothing. Sol's reuse count was 21 at ctx-00, 21 at ctx-30 and 22 at
ctx-90; Sonnet's was 20 at all three sizes.

**What duplication costs.** Duplicated outputs take about 3 times the lines,
4–5 times the statements, twice the cyclomatic complexity and 4–5 times the
fan-out of reused ones. Sol and Gemini (layered set, and Sol dose 10/10) are
significant on lines, statements and fan-out. Correctness, new lint findings
and magic numbers do not differ: the duplicated code works, and there is just
more of it to maintain.

**Pending.** Gemini placement, chain and context runs.

## Correctness sandbox

Generated source is never executed in the Assay process. The correctness
evaluator combines it with the exact arm-specific repository realization inside
this pinned linux/amd64 image:

`python@sha256:2be5d3cb08aa616c6e38d922bd7072975166b2de772004f79ee1bae59fe983dc`

The declared runtime requires Docker client 29.6.1 and server 29.1.2. It uses no
host mounts, `--network=none`, a read-only root filesystem, an isolated 1 MiB
`/tmp`, UID/GID 65534, all capabilities dropped, no-new-privileges, the default
seccomp profile, 64 MiB memory/swap, half a CPU, 32 PIDs, bounded file descriptors
and file size, a ten-second infrastructure-startup deadline, a five-second
candidate deadline, and a 65,536-byte combined output limit.
`--pull=never` makes a missing image fail before paid work rather than silently
resolving mutable remote state. A known implementation is self-tested before the
first provider request. External cancellation waits for forced cleanup of the
uniquely named container.

Within the container, each case runs in a separate isolated Python child process.
The child receives the repository, generated source, and one input, but never the
expected answer. Its captured output is parsed by the supervising harness, which
alone compares against expected values and emits the host-visible result. This
prevents candidate code from terminating the evaluator process or forging the
supervisor's aggregate result protocol.

Before either evaluator accepts generated source, its module is restricted to an
optional leading docstring, necessary imports, and exactly one undecorated
`implement` definition. Imports cannot replace the repository helper. The prompt
more narrowly requests no docstring and a single return statement.

Wrong values, ordinary exceptions, abnormal exits, timeouts, protocol tampering,
and output floods become `incorrect` results. Runtime/image/configuration failures
are evaluator failures and remain missing rather than being mislabeled incorrect.
Only exception type names and case indexes are retained; generated stdout, stderr,
values, and exception messages are not published.

This is a resource-isolation boundary, not remote attestation. Docker, its daemon,
the pinned image, the embedded harness, the host kernel, and the producer remain
trusted. Passing three hidden examples is finite-case correctness and is declared
as a proxy, not proof for all inputs.

## Provider and budget

The worker uses the separately qualified `anthropic/claude-3-haiku` model through
the sole `amazon-bedrock` route. OpenRouter routing continues to require data
collection denial, ZDR, no fallback, required parameters, exact model/provider
identity, and $0.25/$1.25 per-million input/output price caps.

`haiku_dry_settings()` proposes a conservative admission ceiling of **$2.88**:
48 requests reserving $0.06 each without refunds. The bound uses the endpoint's
full 200,000-token context plus 2,048 output tokens. The 12-call qualification
cost $0.002739, so similarly sized experiment calls would be roughly $0.011 in
aggregate; that observation is not a billing guarantee. Preparation, sandbox
self-tests, unit tests, and report recomputation make no provider calls.

Billing-safe failure handling deliberately favors stopping over retrying. A 429,
5xx response, connection reset, or request timeout whose no-charge status cannot
be proven halts budget admission, and every later cell becomes `BudgetHalted`.
Because cells are subject-blocked, a halt among the first 40 cells leaves fewer
than ten complete paired subjects and makes the primary report descriptive-only.
The prescribed response is not resumption or automatic retry: investigate, then
prepare and separately authorize a fresh run with a fresh budget.

## Prepare without provider or container calls

The image must already be present before execution, but preparation only binds
its digest and runtime policy:

```python
import paa_contracts

from assay.adapters.openrouter import HAIKU_BEDROCK, OpenRouterFactory
from assay.investigations.correctness import DockerPythonRunner
from consistency_pilot.dry_experiment import haiku_dry_settings, prepare_dry_experiment
from assay.store import ObjectStore

store = ObjectStore(".assay/dry-haiku-v1")
factory = OpenRouterFactory(HAIKU_BEDROCK)
runner = DockerPythonRunner()
prepared = prepare_dry_experiment(
    store,
    factory=factory,
    settings=haiku_dry_settings(),
    runner=runner,
    schemas={name: paa_contracts.load_schema(name) for name in (
        "paa-task", "paa-evidence-record", "paa-operating-record"
    )},
)
print(prepared)
```

Inspect the canonical plan and snapshot, verify the complete reference closure,
and recheck provider endpoint/rates, Docker versions, local image identity,
account prerequisites, and the $2.88 ceiling. Publishing this implementation is
not spending authorization.

## Execute after exact-plan approval

Execution requires the independently inspected plan hash twice, the paid opt-in,
and a new empty export destination:

```python
from pathlib import Path

from consistency_pilot.dry_experiment import run_dry_experiment

result = await run_dry_experiment(
    store,
    plan_ref=approved_plan_ref,
    authorization=approved_plan_ref,
    factory=OpenRouterFactory(HAIKU_BEDROCK),
    runner=DockerPythonRunner(),
    allow_paid=True,
    export_destination=Path(".assay/dry-haiku-v1-run-1-bundles"),
)
```

The destination contains independent `abstraction/` and `correctness/` report
bundles. Both close over the same manifest and immutable run records, but each
report selects only its own evaluator evidence. Verify both offline. Never retry
a partial or failed live run automatically; a second invocation is a new run with
a new budget and requires a separate operational decision.
