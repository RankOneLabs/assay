# DRY consistency experiment

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

The structural evaluator tolerates one leading function docstring, then requires
a single return statement for an automatic verdict. It recognizes every named
primitive used by the task helper, so calling the helper while also repeating any
of those operations is `mixed`. Assignments, branches, aliases, and other shapes
are `AmbiguousStructure`; without an ambiguity judge that is missing evidence.
Both worker repeats must be present for both arms, so any such missing cell makes
the subject incomplete and removes it from the paired comparison.

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
from assay.investigations.dry_experiment import haiku_dry_settings, prepare_dry_experiment
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

from assay.investigations.dry_experiment import run_dry_experiment

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
