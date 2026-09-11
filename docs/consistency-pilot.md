# Single-file consistency pilot

This pilot asks a real provider, through Jig, to produce an `implement` function
for a supplied one-file repository. It does **not** run generated code, edit a
checkout, supply shell tools, or measure functional correctness. The three built-in
tasks are smoke-test fixtures, not a representative population of coding work.

`ConsistencyWorker` renders only the task instruction and `module.py`, in canonical
JSON. Task IDs, stakes labels, evaluator helper/primitive hints, reference answers,
and arm IDs are not included. Both arms use identical worker settings; repository
contents carry the intervention. Source must arrive through Jig's structured
`submit_output` mechanism. Plain text, Markdown fences and malformed submissions
are failures, not alternative parsers. Each attempt creates a fresh provider
client, conversation, trace, empty tool registry and null feedback loop. Memory,
sessions, feedback injection and Jig grading are disabled.

## Provider integration contract

Supply a `ClientFactory` from `assay.adapters.consistency`:

- `configuration()` returns canonical JSON containing nonempty `model`, `endpoint`
  and implementation `revision`, `billing` (`offline` or `paid`), and integer
  `hidden_retries: 0`. Include every additional effective provider option and
  pinned model revision. Do not include credentials, mutable counters or connection
  IDs. No client construction or network access belongs in this method.
- `create()` is a quick, synchronous constructor returning a **fresh**
  `DescribedClient`. Its `configuration()` must match the factory declaration.
- `complete(params)` implements Jig's LLM protocol, honors the supplied temperature,
  maximum output tokens and structured-output tool, and has no hidden SDK/transport
  retries. It must report the declared model identity, token usage and known USD
  cost where available. If provider model names need translation, bind that
  translation in the declared configuration; do not silently accept a different model.
- `aclose()` releases the attempt's connections; the adapter calls it even after
  failure or cancellation. The client must cooperate with asyncio cancellation.

This is a trusted extension boundary. Assay can check configuration equality, not
prove that an arbitrary client tells the truth or that a mutable remote alias is
reproducible. No provider/model has been selected or qualified by this change.
The existing Jig provider clients need this small describing/factory wrapper;
they cannot be passed directly as factories.

`PilotSettings` binds the static system prompt, inference settings, maximum prompt
bytes, maximum output tokens, attempt/request counts, timeouts and billing policy.
The rendered prompt and complete attempt spans are published with the outcome.
Intermediate rendering/request failures use typed results. Only the required Jig
LLM protocol boundary translates a failure into an exception, which the worker
converts back to `WorkerFailure`. External cancellation propagates.

## Prepare and inspect — no provider calls

The library API is authoritative; no new CLI or automatic provider loading is
introduced. With your `factory` defined, materialize using the pinned schema corpus
(available in the development environment), or supply the same schemas yourself:

```python
import paa_contracts
from assay.adapters.consistency import PilotSettings
from assay.investigations.pilot import PilotPrepared, prepare_pilot
from assay.store import ObjectStore

store = ObjectStore("pilot-store")
settings = PilotSettings()  # offline only; factory must declare offline billing
prepared = prepare_pilot(
    store,
    factory=factory,
    settings=settings,
    schemas={name: paa_contracts.load_schema(name) for name in (
        "paa-task", "paa-evidence-record", "paa-operating-record"
    )},
)
if not isinstance(prepared, PilotPrepared):
    raise RuntimeError(prepared)
print(prepared)
print(store.read_bytes(prepared.plan_ref).decode())
print(store.read_bytes(prepared.snapshot_ref).decode())
```

Inspect the snapshot's worker settings as well as the plan. Defaults yield three
tasks × two arms × two worker repeats = **12 executions**, with one deterministic
evaluation per successful execution and concurrency **1**. Jig's installed VCS
revision is read from package metadata, not supplied as an arbitrary label.
Unpinned/editable Jig installs fail closed. Materialization validates the snapshot
without constructing a provider client. Total expected cost remains explicitly
unavailable: a reservation ceiling is not a prediction of spend.

## Execute an independently approved plan

Run this as a separate operator step, passing the **inspected** plan hash. Do not
automatically approve whatever a new preparation invocation produces.

```python
from pathlib import Path
from assay.investigations.pilot import PilotSucceeded, run_pilot

result = await run_pilot(
    store,
    plan_ref=approved_plan_ref,
    authorization=approved_plan_ref,
    factory=factory,
    export_destination=Path("pilot-bundle"),  # must be empty/nonexistent
)
if not isinstance(result, PilotSucceeded):
    print(result)  # retains manifest/report refs if a later stage failed
else:
    print(result.manifest_ref, result.report_ref)
```

Authorization and runtime/configuration drift are checked before execution.
Every input rendering is preflighted before the first request. Failed workers,
invalid outputs, ambiguous grading and unavailable billing remain explicit in
the records/report. `PilotSucceeded` means the recording/reporting workflow
completed, **not** that every worker succeeded or that the experiment found an
effect. Inspect missingness and individual records. Three subjects are below the
inference floor; the ordinal report is descriptive only. Exports are verified
offline before returning, and can be checked independently with `assay verify`.

## Paid-run gate and limits

No paid run is performed by tests or preparation. Paid settings must declare a
positive `max_spend_usd`, positive `request_cost_bound_usd`, and a nonempty paid
`pricing_basis`. Both the inspected plan authorization and explicit
`allow_paid=True` are required for `run_pilot`. A fake client exercises this path
in tests without network calls.

Before admitting each request, the shared run-local ledger reserves the full
declared request cost bound and increments the total request count. Reservations
are **never refunded**, even if actual cost is lower or a request fails. Admission
stops before reserved bounds exceed the budget, or before the request count is
exceeded. Unknown/invalid cost, transport failure, timeout or a bound violation
halts further provider calls. Partial usage and known cost details stay in the
trace; uncertain totals are reported as unavailable, never zero. Provider-reported
costs are labelled estimated, not independently measured charges.

This is a conservative **admission bound**, not an unconditional guarantee about a
provider's bill. The operator must validate a true upper bound covering the entire
request (system/schema/history input, output/reasoning tokens, provider fees and
all retries), or enforce a suitable hard limit at the provider. An underestimate
can already have overspent when the response arrives. Remote work may continue
after local cancellation. Request/attempt timeouts are cooperative asyncio
deadlines, not a killable process sandbox; cleanup has a separate bounded timeout.
Do not use a cancellation-suppressing or blocking client with this adapter.

Each `run_pilot` invocation has a fresh budget. Reinvocation is a **new run**, not a
resume or a lifetime cap; it requires a new operational spending decision.

## Grading version and acceptance

Structural evaluator version **2** routes deferred/conditional expressions
(lambdas, comprehensions, generators, conditional expressions and boolean
short-circuiting) to ambiguity. Version 1 could classify helper calls inside a
returned lambda as actual reuse. Old evidence is not rewritten; evaluator identity
and basis changes prevent pooling it as the same evaluator. Calls in defaults
and decorators are excluded from the return-expression analysis. The pilot has no
ambiguity judge: these cases remain `AmbiguousStructure` failures. Straight-line
syntactic call detection remains a proxy, not name resolution or correctness proof.

Run `uv run pytest -q tests/test_consistency_pilot.py`. Tests call the **real Jig
runner** with an in-memory fake provider, covering isolation, typed failures,
authorization/configuration drift, output validation, cancellation/cleanup,
concurrent budget admission, missingness, and report export/offline verification.
These fake-provider outputs are never experimental evidence about a real model.

Before a real pilot: select and test the provider factory/model, validate the
billing bound, inspect/approve the frozen settings and plan, then explicitly
authorize the paid run. A repository-editing/tool-using coding agent and any
functional-correctness evaluator remain separate work.
