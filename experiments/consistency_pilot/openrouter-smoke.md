# OpenRouter smoke runs

The first two qualification runs used `qwen/qwen3-coder-30b-a3b-instruct`
through `novita/fp8`. The next proposed run uses the fixed
`anthropic/claude-3-haiku` model through `amazon-bedrock`; it does not use the
moving `~anthropic/claude-haiku-latest` alias. Each run is the existing
12-execution clean/inconsistent pilot, not a cross-model comparison. Haiku is a
separately prepared model configuration, not a fallback for Qwen, and results
from the two workers must not be pooled as though they were one worker.

These are plumbing smoke tests on three synthetic subjects. They do not establish
a DRY effect, measure functional correctness, or execute generated source.

## Bound configuration

`OpenRouterFactory` wraps the pinned Jig OpenRouter adapter. It creates a fresh
SDK/HTTP client per attempt and binds the model, provider endpoint tag, expected
response provider name, rate caps, SDK/HTTP library versions, and transport policy
into the study. The model slugs are catalogue canonical slugs; neither is a
cryptographic pin of remote weights or serving infrastructure.

- Routing uses one explicit `only`/`order` entry, `allow_fallbacks: false`, and
  `require_parameters: true`. Neither model fallback nor default load balancing
  is requested. The response must identify the exact requested model and expected
  provider name. A returned provider name does not independently prove the
  selected endpoint tag.
- Each request requires `data_collection: "deny"` and `zdr: true`. OpenRouter
  must reject routing when the pinned endpoint cannot meet both; neither the
  privacy constraints nor the provider restriction is relaxed on failure.
  This is upstream routing enforcement, not a local capability check: OpenRouter
  receives the request, and its policy enforcement remains a trust boundary.
- The only tool choice is `submit_output`; plugins and message transforms are
  explicitly empty. Caller provider overrides, reasoning switches, and alternate
  response formats are rejected. This profile is source-only, not a generic SDK.
  The complete submission tool definition (including schema, description and
  strictness) is fixed, recorded in configuration, and checked before sending.
- SDK retries are zero; the HTTP transport does not follow redirects or use
  environment proxy settings. The SDK major is constrained to 2 for the current
  HTTPX integration and its exact resolved version is locked in `uv.lock`.
- `max_request_body_bytes` caps the **serialized JSON request body** at 65,536
  bytes, including system prompt, schema, and any conversation history. It excludes
  HTTP headers, request-line/protocol overhead, and TLS framing. Output is capped at 2,048
  tokens; the transport timeout is 30 seconds, within the pilot attempt deadline.
- Raw JSON model/provider identity and required token counts/cost are checked
  before SDK coercion or Jig's missing-usage defaults. Missing cost never falls
  back to Jig's local pricing table. Malformed/unknown billing stops further
  requests through the existing pilot ledger. Published cost remains estimated
  USD credit usage, not an independent invoice audit.
- A typed, client-confirmed rejection before any HTTP send does not make billing
  uncertain or halt later attempts. An attempt consisting only of such rejections
  has zero calls and zero cost. Admission reservations are still never refunded;
  transport errors, timeouts, and unknown failures remain potentially billable
  and halt further requests. Error-type strings alone never establish no-send.
- SDK error bodies are not copied into result messages; the existing worker
  trace retains prompts, spans, response model names, and valid usage. The
  integration does not persist full HTTP bodies or headers.

## Response diagnostics (v3)

The worker trace's `provider_diagnostics` records allowlisted observations before
SDK parsing, including failed attempts. Each request-hook observation includes
the SHA-256 digest and byte count of the actual serialized JSON body, whether a
response arrived, and its HTTP status when available. A hook observation is not
proof that bytes were sent: locally rejected requests can also reach this hook.
Failures rejected before the hook have no request observation.

For successful HTTP responses with parseable JSON, diagnostics include a bounded
generation-ID hash, choice count, first-choice finish/native-finish reasons, known
message-field types (including missing versus null), content character count,
and tool-call count/names. Field types distinguish legacy `function_call`, refusal,
and reasoning-only shapes without recording their contents. Non-2xx responses
record status only; their error bodies are not inspected for diagnostic fields.

Capture is capped at ten request observations per client and eight tool names per
response, with explicit truncation flags. Generation IDs are limited to 128 ASCII
identifier characters with a `gen-` prefix, then recorded only as
`generation_id_sha256`; raw IDs are never retained. Hashes support equality checks,
not direct provider lookup, and are not a guarantee of anonymity for guessable IDs.
Invalid IDs or IDs containing the active API key are omitted (null).
Finish and native-finish reasons allow only `stop`, `length`, `tool_calls`,
`content_filter`, `function_call`, and `error`; tool names allow only `submit_output`.
Other string labels become a fixed `unknown` marker (including labels longer than
64 characters); missing/non-string labels and bounded labels containing the active
API key become null. No arbitrary label is retained or truncated. Arbitrary
field names, content, reasoning, refusal text, arguments, and headers are excluded.
These observations are detached from provider response objects. Returned
diagnostic snapshots are also detached and remain available after client cleanup.
The `openrouter-response-shape-v2` policy is bound into provider configuration;
plans prepared under the earlier raw-ID diagnostic policy require re-preparation.

Diagnostics do not alter response validation, introduce retries, accept legacy
calls as submissions, or mark otherwise known usage as unavailable. They remain
provider observations, not independent proof of a remote model's behavior.
Optional client diagnostics are validated as canonical-JSON-compatible objects
and detached before attaching them to the trace. Retrieval or validation failures
produce a fixed `capture_failed` marker without replacing the worker outcome,
trace, or accounting.

See OpenRouter's [provider-routing contract](https://openrouter.ai/docs/guides/routing/provider-selection)
and [usage-accounting contract](https://openrouter.ai/docs/cookbook/administration/usage-accounting).
Remote adherence, account defaults, and upstream internal retries remain trusted
service boundaries; disabling client retries is not proof of remote execution count.

## Proposed budget, not spending authorization

`qwen_smoke_settings()` proposes a **$0.48 admission ceiling per run**: at most
24 requests, reserving $0.02 each, without refunds. Two separately approved runs
therefore have a combined proposed ceiling of $0.96. This is not an expected cost
or an unconditional billing guarantee.

The [Novita endpoint catalogue](https://openrouter.ai/api/v1/models/qwen/qwen3-coder-30b-a3b-instruct/endpoints)
was checked on 2026-09-11: $0.07 per million input tokens, $0.27 per million output
tokens, and a 160,000-token endpoint context limit. These rates are sent as
`max_price` filters, with per-request price capped at zero. At those rates,
160,000 input plus 2,048 output tokens would cost $0.01175296, below the $0.02
reservation. This calculation assumes the stated token limit and no other
charges. The byte cap is not a tokenizer-based proof of a token bound.

`haiku_smoke_settings()` separately proposes a **$1.44 admission ceiling**:
at most 24 requests, reserving $0.06 each, without refunds. The
[Amazon Bedrock endpoint catalogue](https://openrouter.ai/api/v1/models/anthropic/claude-3-haiku/endpoints)
was checked on 2026-09-11: $0.25 per million input tokens, $1.25 per million
output tokens, a 200,000-token context limit, and required tool-choice support.
At those rates, 200,000 input plus 2,048 output tokens would cost $0.05256,
below the $0.06 reservation. This is a conservative admission bound, not expected
spend; the synthetic prompts are much smaller. The same assumptions and remote
trust boundaries apply.

Before execution, recheck that the endpoint, rate caps and context limit still
apply, and use an OpenRouter credits-only account/key with no BYOK or paid account
plugins/presets. Configure an appropriate provider-side key limit separately.
No account settings or key limits are changed by this code. Buying credits and
its fees are outside the run's `usage.cost` accounting.

## Prepare without credentials or paid calls

Run `uv sync --locked`, then use the library API in a Python session launched
with `cd experiments && uv run python -m consistency_pilot.openrouter_smoke`.
Preparation does not read the API key or create a client:

```python
import paa_contracts
from assay.adapters.openrouter import HAIKU_BEDROCK, OpenRouterFactory
from consistency_pilot.openrouter_smoke import haiku_smoke_settings
from consistency_pilot.pilot import PilotPrepared, prepare_pilot
from assay.store import ObjectStore

store = ObjectStore(".assay/haiku-smoke")
factory = OpenRouterFactory(HAIKU_BEDROCK)
prepared = prepare_pilot(
    store,
    factory=factory,
    settings=haiku_smoke_settings(),
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

`.assay/` is ignored by Git; preserve the object store and export each completed
run for archival. A dependency/configuration change requires preparing and
inspecting a new plan. Publish/review the implementation before a live run.
For the Qwen profile, use the default `OpenRouterFactory()` together with
`qwen_smoke_settings()` and a separate object store.
The v3 diagnostic policy is bound into the provider configuration and invalidates
previously prepared v1/v2 configurations. Prepare and independently approve a new
plan after updating; the completed first v2 run remains unchanged.

## Execute only after plan and budget approval

Provide `OPENROUTER_API_KEY` through the execution environment, not in a tracked
file, command-line argument, or published configuration. Do not print it. The
factory never falls back to `OPENAI_API_KEY`; unrelated OpenAI endpoint/project
environment settings are ignored. Unset `OPENAI_CUSTOM_HEADERS`, which is rejected.

In a separate operator step, supply the independently inspected plan hash:

```python
import asyncio
from pathlib import Path
from assay.adapters.openrouter import HAIKU_BEDROCK, OpenRouterFactory
from consistency_pilot.pilot import run_pilot
from assay.store import ObjectStore

# approved_plan_ref must be supplied from the independent inspection/approval.
result = asyncio.run(run_pilot(
    ObjectStore(".assay/haiku-smoke"),
    plan_ref=approved_plan_ref,
    authorization=approved_plan_ref,
    factory=OpenRouterFactory(HAIKU_BEDROCK),
    allow_paid=True,
    export_destination=Path(".assay/haiku-smoke-run-1-bundle"),
))
print(result)
```

Before a second invocation, inspect failures, missingness, usage, and the verified
bundle from run 1. Obtain a separate spending approval and use a new export path.
Reusing the same unchanged plan hash is possible, but every invocation gets a
fresh budget: it is not a resume operation or a lifetime cap. Do not put the two
paid runs in an unattended retry loop.

## Offline acceptance

`cd experiments && uv run pytest -q consistency_pilot/tests/test_openrouter.py`
runs the real Jig adapter, SDK and
HTTP hooks against an intercepted transport. It covers exact requests, credential
isolation, malformed billing/identity, no retries, cancellation and closure,
authorization gates, and two complete mocked pilots with offline bundle checks.
These tests make no provider calls and cannot establish live account access or
model availability.
