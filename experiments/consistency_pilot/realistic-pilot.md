# Realistic repository qualification pilot

From the repository root, run with
`cd experiments && uv run python -m consistency_pilot.realistic_pilot`.

This pilot qualifies Assay's multi-file repository path before a larger
12-subject experiment. It is intentionally descriptive: four subjects are not
enough for the preregistered inferential floor used by the full DRY study.

## Frozen fixtures

`REALISTIC_PILOT_FIXTURES` deterministically produces four independent Python
service repositories:

- marketplace operations;
- support desk;
- telemetry ingestion; and
- identity management.

Each arm contains the same 31 paths and 1,225 physical lines (roughly 37 KB).
The packages include domain models, repositories, validation, serialization,
services, configuration, errors, packaging metadata, and documentation. Every
Python file is parsed during fixture validation.

The treatment is confined to three return expressions in the governed
normalization module. In the clean arm, three existing functions call the
relevant helper. In the inconsistent arm, those functions spell out the
helper's primitive expression. Paths, line counts, task text, helper behavior,
and every other byte are held fixed. Neither repository contains the requested
`implement` function.

The model receives canonical JSON containing only the task instruction and the
complete path-to-text repository. Hidden cases, family, helper identity, arm,
target metadata, and evaluator hints are not rendered.

## Low-cost smoke gate

Before the Haiku qualification pilot, `prepare_realistic_smoke` freezes a
smaller operational check using the `commerce-sku` repository and GPT-OSS 120B
through the pinned CoreWeave fp4 route. Both arms run twice, so
the smoke plan contains four provider calls and eight local evaluations. Its
conservative admission ceiling is $0.02: $0.005 per request under the declared
$0.03/$0.17 per-million input/output token caps. This pre-call bound stops new
requests once exhausted, but it cannot cap a remote provider's final charge.

This smoke result is not evidence about the treatment. It checks provider
routing and identity, large-context rendering, repeated calls, sandboxed
package execution, reports, and bundle verification at lower cost. It has its
own fail-closed provider validator and cannot authorize or substitute for the
Haiku qualification plan.

```python
import paa_contracts

from assay.adapters.openrouter import GPT_OSS_120B_COREWEAVE, OpenRouterFactory
from assay.investigations.correctness import DockerPythonRunner
from consistency_pilot.realistic_pilot import (
    prepare_realistic_smoke,
    realistic_gpt_oss_smoke_settings,
)
from assay.store import ObjectStore

smoke_store = ObjectStore(".assay/realistic-gpt-oss-smoke-v1")
smoke = prepare_realistic_smoke(
    smoke_store,
    factory=OpenRouterFactory(GPT_OSS_120B_COREWEAVE),
    settings=realistic_gpt_oss_smoke_settings(),
    runner=DockerPythonRunner(),
    schemas={name: paa_contracts.load_schema(name) for name in (
        "paa-task", "paa-evidence-record", "paa-operating-record"
    )},
)
print(smoke)
```

After inspecting and explicitly authorizing `smoke.plan_ref`, execute it with
`run_realistic_smoke`, the same factory and runner, `allow_paid=True`, and a new
bundle destination.

## Execution boundary

The worker still returns only optional imports and one `implement` function.
Its governed prompt states that this source is appended verbatim to the target
file, so names already defined there must be called directly rather than
self-imported from that module.
Correctness evaluation validates every repository path, writes the governed
snapshot into the container's bounded tmpfs, appends the candidate only to the
declared target file, and loads that module with both the repository root and
`src/` available for imports. There are no host mounts or network access, and
the container image/runtime checks remain pinned.

The generic consistency runner revalidates the exact task population,
repository bytes, schedule, declarations, evaluator configuration, runtime,
and complete object closure against the authorized plan before admitting a
provider call. The original 12-subject experiment uses the same path with its
single-file fixture definition.

## Prepare without spending

```python
import paa_contracts

from assay.adapters.openrouter import HAIKU_BEDROCK, OpenRouterFactory
from assay.investigations.correctness import DockerPythonRunner
from consistency_pilot.realistic_pilot import (
    prepare_realistic_pilot,
    realistic_haiku_settings,
)
from assay.store import ObjectStore

store = ObjectStore(".assay/realistic-haiku-pilot-v1")
prepared = prepare_realistic_pilot(
    store,
    factory=OpenRouterFactory(HAIKU_BEDROCK),
    settings=realistic_haiku_settings(),
    runner=DockerPythonRunner(),
    schemas={name: paa_contracts.load_schema(name) for name in (
        "paa-task", "paa-evidence-record", "paa-operating-record"
    )},
)
print(prepared)
```

Preparation creates 16 worker cells and 32 local evaluations: four subjects,
two arms, and two worker repeats. It does not create a provider client or start
a container. The paid profile has a conservative $0.96 ceiling (16 requests at
$0.06); a plan must be inspected and its exact hash separately authorized. Both
the per-arm and total ceilings are recorded as estimated plan costs.

## Execute only after exact-plan approval

```python
from pathlib import Path

from consistency_pilot.realistic_pilot import run_realistic_pilot

result = await run_realistic_pilot(
    store,
    plan_ref=approved_plan_ref,
    authorization=approved_plan_ref,
    factory=OpenRouterFactory(HAIKU_BEDROCK),
    runner=DockerPythonRunner(),
    allow_paid=True,
    export_destination=Path(".assay/realistic-haiku-pilot-v1-run-1-bundles"),
)
```

Do not interpret the qualification pilot as a confirmatory result. Its purpose
is to expose navigation, patch-shape, evaluator, context-size, and operational
failures before freezing eight additional repositories for a full study.
