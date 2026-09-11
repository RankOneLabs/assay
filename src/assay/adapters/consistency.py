"""Isolated, source-only Jig worker for the single-file consistency pilot.

Provider factories are trusted integration boundaries, not a sandbox. They must
describe live settings, disable hidden retries, and create a fresh client. No
generated source is executed. Paid admission is conditional on the operator's
validated per-request billing bound; it cannot control a remote provider's bill.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import math
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal, Protocol

from jig import AgentConfig, run_agent
from jig.core.types import (
    CompletionParams,
    LLMClient,
    LLMResponse,
    Span,
    SpanKind,
    TracingLogger,
    Usage,
)
from jig.feedback.null import NullFeedbackLoop
from jig.tools.registry import ToolRegistry
from pydantic import BaseModel, ConfigDict, Field, model_validator

from assay.canonical import canonical_json
from assay.execution import Accounting, WorkerFailure, WorkerResult, WorkerSuccess
from assay.models import WireModel

SYSTEM_PROMPT = (
    "Complete the coding task using the supplied repository as context. "
    "Return only any necessary imports and the new implement function as source. "
    "The function must have no docstring and exactly one return statement; do not include "
    "the existing repository or an explanation. Submit the structured source output."
)


class SourceOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    source: str = Field(min_length=1, max_length=100_000)


class PilotSettings(WireModel):
    mode: Literal["offline", "paid"] = "offline"
    system_prompt: str = Field(default=SYSTEM_PROMPT, min_length=1, max_length=32_768)
    temperature: float = Field(default=0, ge=0, le=2, allow_inf_nan=False)
    max_output_tokens: int = Field(default=2048, ge=1, le=32_768, strict=True)
    max_input_bytes: int = Field(default=32_768, ge=1, le=1_000_000, strict=True)
    max_llm_calls: int = Field(default=2, ge=1, le=10, strict=True)
    max_total_requests: int = Field(default=24, ge=1, le=1000, strict=True)
    request_timeout_s: float = Field(default=30, gt=0, le=600, allow_inf_nan=False)
    attempt_timeout_s: float = Field(default=75, gt=0, le=1200, allow_inf_nan=False)
    cleanup_timeout_s: float = Field(default=5, gt=0, le=30, allow_inf_nan=False)
    max_spend_usd: Decimal = Field(default=Decimal(0), ge=0, le=1_000_000, allow_inf_nan=False)
    request_cost_bound_usd: Decimal = Field(
        default=Decimal(0),
        ge=0,
        le=1_000_000,
        allow_inf_nan=False,
    )
    pricing_basis: str = "offline-no-provider-charges"

    @model_validator(mode="after")
    def valid_budget(self) -> PilotSettings:
        if not self.pricing_basis.strip():
            raise ValueError("pricing basis must be nonblank")
        if self.request_timeout_s > self.attempt_timeout_s:
            raise ValueError("request timeout must not exceed attempt timeout")
        if self.mode == "offline":
            if self.max_spend_usd != 0 or self.request_cost_bound_usd != 0:
                raise ValueError("offline mode cannot authorize spend")
        elif not (
            0 < self.request_cost_bound_usd <= self.max_spend_usd
            and self.pricing_basis != "offline-no-provider-charges"
        ):
            raise ValueError(
                "paid mode requires a positive request bound, budget and pricing basis"
            )
        return self


@dataclasses.dataclass(frozen=True, slots=True)
class CompletionNotSent(WorkerFailure):
    """Trusted client assertion: this completion failed before any HTTP send.

    Ordinary failures and transport errors must remain WorkerFailure, even when
    an exception suggests no charge. This marker is internal, not a wire field.
    """


class DescribedClient(LLMClient):
    """configuration includes model, endpoint, revision, billing and retry policy."""

    def configuration(self) -> dict[str, Any]:
        raise NotImplementedError

    def diagnostics(self) -> dict[str, Any] | None:
        """Detached, credential-free observations; optional for trusted providers."""
        return None

    async def complete_result(self, params: CompletionParams) -> LLMResponse | WorkerFailure:
        """Adapt exception-based providers; governed clients may return failures directly."""
        try:
            return await self.complete(params)
        except Exception as error:
            return WorkerFailure(type(error).__name__, str(error))


class ClientFactory(Protocol):
    def configuration(self) -> dict[str, Any]: ...

    def create(self) -> DescribedClient: ...


def render_input(value: Any, limit: int) -> WorkerSuccess | WorkerFailure:
    """Whitelist model-visible fields; never expose evaluator hints or arm IDs."""
    try:
        if not isinstance(value, dict) or set(value) != {"task", "repository", "base_subject_ref"}:
            raise ValueError("expected a materialized consistency realization")
        instruction = value["task"]["instruction"]
        repository = value["repository"]
        if not isinstance(instruction, str) or not instruction.strip():
            raise ValueError("task instruction must be nonempty text")
        if not isinstance(repository, dict) or set(repository) != {"module.py"}:
            raise ValueError("pilot supports exactly module.py")
        if not isinstance(repository["module.py"], str):
            raise ValueError("repository source must be text")
        prompt = canonical_json({"instruction": instruction, "repository": repository})
        if len(prompt) > limit:
            raise ValueError("rendered input exceeds the authorized byte limit")
        return WorkerSuccess(prompt.decode("utf-8"))
    except (KeyError, TypeError, ValueError, UnicodeError) as error:
        return WorkerFailure("InvalidInput", str(error))


class _Trace(TracingLogger):
    """One attempt's spans, copied into the published worker trace on completion."""

    def __init__(self) -> None:
        self.spans: dict[str, Span] = {}

    def start_trace(
        self,
        name: str,
        metadata: dict[str, Any] | None = None,
        kind: SpanKind = SpanKind.AGENT_RUN,
    ) -> Span:
        span = Span(
            id=str(uuid.uuid4()),
            trace_id=str(uuid.uuid4()),
            kind=kind,
            name=name,
            started_at=datetime.now(UTC),
            metadata=metadata,
        )
        self.spans[span.id] = span
        return span

    def start_span(
        self,
        parent_id: str,
        kind: SpanKind,
        name: str,
        input: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> Span:
        span = self.start_trace(name, metadata, kind)
        span.parent_id = parent_id
        span.trace_id = self.spans[parent_id].trace_id
        span.input = input
        return span

    def end_span(
        self,
        span_id: str,
        output: Any = None,
        error: str | None = None,
        usage: Usage | None = None,
    ) -> None:
        span = self.spans[span_id]
        span.ended_at = datetime.now(UTC)
        span.duration_ms = (span.ended_at - span.started_at).total_seconds() * 1000
        span.output, span.error, span.usage = output, error, usage

    async def get_trace(self, trace_id: str) -> list[Span]:
        return [span for span in self.spans.values() if span.trace_id == trace_id]

    async def list_traces(
        self,
        since: datetime | None = None,
        limit: int = 50,
        name: str | None = None,
    ) -> list[Span]:
        return [
            span
            for span in self.spans.values()
            if span.parent_id is None
            and (since is None or span.started_at >= since)
            and (name is None or span.name == name)
        ][:limit]

    def dump(self) -> list[dict[str, Any]]:
        records = []
        for span in self.spans.values():
            record = dataclasses.asdict(span)
            for key in ("started_at", "ended_at"):
                if record[key] is not None:
                    record[key] = record[key].isoformat()
            records.append(record)
        return records


class _Admission:
    def __init__(self, settings: PilotSettings) -> None:
        self.settings = settings
        self.requests = 0
        self.halted = False

    def reserve(self) -> WorkerFailure | None:
        # No await between checking and reserving: atomic on the run's event loop.
        if self.halted:
            return WorkerFailure("BudgetHalted", "a previous request has uncertain billing")
        if self.requests >= self.settings.max_total_requests:
            return WorkerFailure("RequestLimit", "authorized request count exhausted")
        if (self.requests + 1) * self.settings.request_cost_bound_usd > self.settings.max_spend_usd:
            return WorkerFailure("SpendLimit", "insufficient unreserved budget")
        self.requests += 1
        # Reservations are never refunded, even on cancellation/provider failure.
        return None


class _RequestFailed(Exception):
    def __init__(self, result: WorkerFailure) -> None:
        self.result = result
        super().__init__(result.message)


class _BoundedClient(LLMClient):
    def __init__(self, inner: DescribedClient, admission: _Admission, model: str) -> None:
        self.inner, self.admission = inner, admission
        self._model = model
        self.settings = admission.settings
        self.requests = 0
        self.not_sent = 0
        self.usages: list[dict[str, Any]] = []
        self.response_models: list[str] = []
        self.uncertain = False

    async def complete_result(self, params: CompletionParams) -> LLMResponse | WorkerFailure:
        refused = self.admission.reserve()
        if refused is not None:
            return refused
        self.requests += 1
        params = dataclasses.replace(
            params,
            temperature=self.settings.temperature,
            max_tokens=self.settings.max_output_tokens,
        )
        try:
            async with asyncio.timeout(self.settings.request_timeout_s):
                response = await self.inner.complete_result(params)
            if isinstance(response, WorkerFailure):
                if isinstance(response, CompletionNotSent):
                    self.not_sent += 1
                else:
                    self.uncertain = self.admission.halted = True
                return response
            usage = response.usage
            for value in (usage.input_tokens, usage.output_tokens):
                if type(value) is not int or not 0 <= value <= 2**53 - 1:
                    raise ValueError("provider returned invalid token usage")
            cost = usage.cost
            if cost is not None and (isinstance(cost, bool) or not math.isfinite(cost) or cost < 0):
                raise ValueError("provider returned invalid cost")
            self.usages.append(dataclasses.asdict(usage))
            if not isinstance(response.model, str):
                raise ValueError("provider returned an invalid model identity")
            self.response_models.append(response.model)
            if response.model != self._model:
                raise ValueError("response model differs from the declared model")
            if self.settings.mode == "paid" and cost is None:
                raise ValueError("paid provider returned unknown cost")
            if cost is not None and Decimal(str(cost)) > self.settings.request_cost_bound_usd:
                raise ValueError("provider cost exceeded the declared request bound")
            return response
        except asyncio.CancelledError:
            self.uncertain = self.admission.halted = True
            raise
        except Exception as error:
            self.uncertain = self.admission.halted = True
            return WorkerFailure(type(error).__name__, str(error))

    async def complete(self, params: CompletionParams) -> LLMResponse:
        # Jig's LLM protocol requires exceptions. Keep that translation at this
        # boundary; the intermediate operation and caller-facing worker use Result.
        result = await self.complete_result(params)
        if isinstance(result, WorkerFailure):
            raise _RequestFailed(result)
        return result

    def accounting(self) -> Accounting:
        usage = {
            "llm_calls": self.requests - self.not_sent,
            "input_tokens": sum(item["input_tokens"] for item in self.usages),
            "output_tokens": sum(item["output_tokens"] for item in self.usages),
        }
        if self.uncertain:
            # Do not present partial token totals as complete attempt usage.
            return Accounting(usage={"llm_calls": self.requests - self.not_sent})
        if self.not_sent and self.not_sent == self.requests:
            return Accounting(
                usage=usage,
                amount=0,
                currency="USD",
                coverage="measured",
                basis="client-confirmed-no-http-send",
            )
        costs = [item["cost"] for item in self.usages]
        if costs and all(cost is not None for cost in costs):
            return Accounting(
                usage=usage,
                amount=float(sum(Decimal(str(cost)) for cost in costs)),
                currency="USD",
                coverage="estimated",
                basis=self.settings.pricing_basis,
            )
        return Accounting(usage=usage)


async def _close_client(client: DescribedClient, timeout_s: float) -> WorkerFailure | None:
    """Drain a separately timed close despite repeated caller cancellation."""

    async def close() -> WorkerFailure | None:
        try:
            async with asyncio.timeout(timeout_s):
                await client.aclose()
        except Exception as error:
            return WorkerFailure("CleanupFailed", f"{type(error).__name__}: {error}")
        return None

    # The deadline belongs to the close task, so caller cancellation neither
    # interrupts cleanup nor restarts its timeout. The provider must cooperate.
    closing = asyncio.create_task(close())
    cancellation: asyncio.CancelledError | None = None
    while not closing.done():
        try:
            await asyncio.shield(closing)
        except asyncio.CancelledError as error:
            cancellation = error
    if cancellation is not None:
        raise cancellation
    return closing.result()


@dataclasses.dataclass(frozen=True)
class ConsistencyWorker:
    """Fresh client, trace, tools and conversation per attempt; no generated code execution."""

    factory: ClientFactory
    settings: PilotSettings
    allow_paid: bool = dataclasses.field(default=False, kw_only=True)
    _admission: _Admission = dataclasses.field(init=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_admission", _Admission(self.settings))

    def configuration(self, arm_id: str) -> dict[str, Any]:
        if arm_id not in {"clean", "inconsistent"}:
            raise ValueError("unknown consistency arm")
        provider = self.factory.configuration()
        if not all(
            isinstance(provider.get(key), str) and provider[key].strip()
            for key in ("model", "endpoint", "revision")
        ):
            raise ValueError("provider must declare model, endpoint and revision")
        if (
            provider.get("billing") != self.settings.mode
            or type(provider.get("hidden_retries")) is not int
            or provider["hidden_retries"] != 0
        ):
            raise ValueError("provider billing must match settings and hidden retries must be zero")
        canonical_json(provider)
        return {
            "id": "consistency-jig-source",
            "version": "1",
            "provider": provider,
            "settings": self.settings.model_dump(mode="json"),
            "rendering": "instruction-and-module-canonical-json-v1",
            "extraction": "parsed-source-only-v1",
            "output_schema": SourceOutput.model_json_schema(),
            "runtime": {
                "memory": False,
                "feedback": False,
                "session": False,
                "grader": False,
                "tools": [],
                "structured_output": "legacy",
                "max_llm_retries": 1,
                "max_parse_retries": 0,
            },
        }

    async def run(self, *, input_value: Any, arm_id: str) -> WorkerResult:
        rendered = render_input(input_value, self.settings.max_input_bytes)
        if isinstance(rendered, WorkerFailure):
            return rendered
        if self.settings.mode == "paid" and not self.allow_paid:
            return WorkerFailure("PaidExecutionDenied", "explicit paid execution opt-in required")
        trace = _Trace()
        client: DescribedClient | None = None
        bounded: _BoundedClient | None = None
        result: WorkerResult
        cleanup_error: str | None = None
        try:
            declared = self.configuration(arm_id)["provider"]
            client = self.factory.create()
            if canonical_json(client.configuration()) != canonical_json(declared):
                raise ValueError("created provider configuration differs from declaration")
            bounded = _BoundedClient(client, self._admission, declared["model"])
            config = AgentConfig(
                name="consistency-source",
                description="Single-file code generation",
                system_prompt=self.settings.system_prompt,
                llm=bounded,
                feedback=NullFeedbackLoop(),
                tracer=trace,
                tools=ToolRegistry(),
                include_memory_in_prompt=False,
                include_feedback_in_prompt=False,
                output_schema=SourceOutput,
                max_parse_retries=0,
                max_llm_retries=1,
                max_llm_calls=self.settings.max_llm_calls,
            )
            async with asyncio.timeout(self.settings.attempt_timeout_s):
                agent = await run_agent(config, rendered.output)
            if agent.error is not None:
                result = WorkerFailure(type(agent.error).__name__, str(agent.error))
            elif not isinstance(agent.parsed, SourceOutput) or not agent.parsed.source.strip():
                result = WorkerFailure("InvalidOutput", "structured source output is required")
            else:
                result = WorkerSuccess(agent.parsed.model_dump(mode="json"))
        except _RequestFailed as error:
            result = error.result
        except Exception as error:
            result = WorkerFailure(type(error).__name__, str(error))
        finally:
            if client is not None:
                cleanup = await _close_client(client, self.settings.cleanup_timeout_s)
                cleanup_error = None if cleanup is None else cleanup.message
        if cleanup_error is not None and isinstance(result, WorkerSuccess):
            result = WorkerFailure("CleanupFailed", cleanup_error)
        detail = {
            "prompt": rendered.output,
            "spans": trace.dump(),
            "cleanup_error": cleanup_error,
            "provider_usage": [] if bounded is None else bounded.usages,
            "response_models": [] if bounded is None else bounded.response_models,
            "billing_uncertain": False if bounded is None else bounded.uncertain,
        }
        if client is not None:
            try:
                diagnostics = client.diagnostics()
                if diagnostics is not None:
                    if not isinstance(diagnostics, dict):
                        raise ValueError("provider diagnostics must be an object")
                    diagnostics = json.loads(canonical_json(diagnostics))
            except Exception:
                # Observability must not discard an outcome or its known usage.
                diagnostics = {"capture_failed": True}
            if diagnostics is not None:
                detail["provider_diagnostics"] = diagnostics
        return dataclasses.replace(
            result,
            trace=detail,
            accounting=Accounting() if bounded is None else bounded.accounting(),
        )
