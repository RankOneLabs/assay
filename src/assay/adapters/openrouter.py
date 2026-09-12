"""Governed OpenRouter client for source-only pilots; no calls during preparation."""

from __future__ import annotations

import dataclasses
import json
import math
import os
from importlib.metadata import version
from typing import Any

import httpx
from jig.core.types import CompletionParams, LLMResponse, ToolDefinition
from jig.llm.openrouter import OpenRouterClient
from pydantic import Field

from assay.adapters.consistency import CompletionNotSent, DescribedClient, SourceOutput
from assay.adapters.openrouter_diagnostics import ResponseDiagnostics, diagnostic_policy
from assay.canonical import canonical_json
from assay.execution import WorkerFailure
from assay.models import WireModel

ENDPOINT = "https://openrouter.ai/api/v1"


def source_output_tool() -> ToolDefinition:
    """Fresh copy of the pinned Jig runner's source-only submission contract."""
    return ToolDefinition(
        name="submit_output",
        description=(
            "Submit your final answer. Call this exactly once when you have "
            "your result — do not produce a free-form text response as your "
            "final answer."
        ),
        parameters=SourceOutput.model_json_schema(),
        strict=True,
    )


def _source_tools_match(tools: list[ToolDefinition] | None) -> bool:
    if tools is None or len(tools) != 1 or not isinstance(tools[0], ToolDefinition):
        return False
    try:
        return canonical_json(dataclasses.asdict(tools[0])) == canonical_json(
            dataclasses.asdict(source_output_tool())
        )
    except (TypeError, ValueError):
        return False


class OpenRouterSettings(WireModel):
    """One explicit model/route. Price limits are USD per million tokens."""

    model: str = Field(pattern=r"^[a-z0-9-]+/[a-z0-9._-]+$")
    provider: str = Field(pattern=r"^[a-z0-9-]+(?:/[a-z0-9._-]+)?$")
    provider_name: str = Field(min_length=1, pattern=r"^\S(?:.*\S)?$")
    max_prompt_price: float = Field(gt=0, le=100, allow_inf_nan=False)
    max_completion_price: float = Field(gt=0, le=1000, allow_inf_nan=False)
    max_request_body_bytes: int = Field(default=65_536, ge=1, le=1_000_000, strict=True)
    max_output_tokens: int = Field(default=2048, ge=1, le=32_768, strict=True)
    timeout_s: float = Field(default=30, gt=0, le=600, allow_inf_nan=False)

    def routing(self) -> dict[str, Any]:
        return {
            "data_collection": "deny",
            "zdr": True,
            "only": [self.provider],
            "order": [self.provider],
            "allow_fallbacks": False,
            "require_parameters": True,
            "max_price": {
                "prompt": self.max_prompt_price,
                "completion": self.max_completion_price,
                "request": 0,
            },
        }


# Catalogue checked 2026-09-11. These are explicit rate caps, not live discovery
# or a promise that this remote model/route will remain available or unchanged.
QWEN_NOVITA = OpenRouterSettings(
    model="qwen/qwen3-coder-30b-a3b-instruct",
    provider="novita/fp8",
    provider_name="Novita",
    max_prompt_price=0.07,
    max_completion_price=0.27,
)


# Catalogue checked 2026-09-11. CoreWeave advertises required/function tool
# choice for this fixed route; the governed request still requires ZDR and
# rejects fallback providers.
GPT_OSS_120B_COREWEAVE = OpenRouterSettings(
    model="openai/gpt-oss-120b",
    provider="coreweave/fp4",
    provider_name="CoreWeave",
    max_prompt_price=0.03,
    max_completion_price=0.17,
)


# Catalogue checked 2026-09-11. The fixed model slug avoids the moving
# `~anthropic/claude-haiku-latest` alias; this remains a remote service boundary.
HAIKU_BEDROCK = OpenRouterSettings(
    model="anthropic/claude-3-haiku",
    provider="amazon-bedrock",
    provider_name="Amazon Bedrock",
    max_prompt_price=0.25,
    max_completion_price=1.25,
)


@dataclasses.dataclass(frozen=True)
class OpenRouterFactory:
    settings: OpenRouterSettings = QWEN_NOVITA
    api_key: str | None = dataclasses.field(default=None, repr=False, compare=False)

    def configuration(self) -> dict[str, Any]:
        """Describe effective settings without reading credentials or opening clients."""
        return {
            "model": self.settings.model,
            "endpoint": ENDPOINT,
            "revision": "assay-openrouter-source-v3",
            "billing": "paid",
            "hidden_retries": 0,
            "settings": self.settings.model_dump(mode="json"),
            "routing": self.settings.routing(),
            "tool_choice": "submit_output",
            "tool_definition": dataclasses.asdict(source_output_tool()),
            "transforms": [],
            "plugins": [],
            "stream": False,
            "usage": "required-inline-openrouter-cost-no-local-price-fallback",
            "response_identity": "exact-model-and-provider-name",
            "diagnostics": diagnostic_policy(),
            "transport": {
                "openai": version("openai"),
                "httpx": version("httpx"),
                "retries": 0,
                "follow_redirects": False,
                "trust_env": False,
                "custom_headers": False,
            },
        }

    def create(self) -> DescribedClient:
        key = self.api_key if self.api_key is not None else os.environ.get("OPENROUTER_API_KEY")
        if not key or not key.strip() or any(char.isspace() for char in key):
            raise ValueError("a nonblank OPENROUTER_API_KEY is required for execution")
        if os.environ.get("OPENAI_CUSTOM_HEADERS"):
            raise ValueError("unset OPENAI_CUSTOM_HEADERS for the governed OpenRouter client")
        return _PilotClient(self.settings, key, self.configuration())


class _RequestRejected(Exception):
    def __init__(self, result: WorkerFailure) -> None:
        self.result = result
        super().__init__(result.message)


def _response_failure(data: Any, settings: OpenRouterSettings) -> WorkerFailure | None:
    """Validate original JSON values before SDK coercion or Jig usage defaults."""
    if not isinstance(data, dict) or data.get("error") is not None:
        return WorkerFailure("InvalidResponse", "OpenRouter returned an error or invalid response")
    if data.get("model") != settings.model or data.get("provider") != settings.provider_name:
        return WorkerFailure("IdentityMismatch", "OpenRouter model/provider differs from the plan")
    usage = data.get("usage")
    if not isinstance(usage, dict):
        return WorkerFailure("InvalidUsage", "OpenRouter usage is required")
    for name in ("prompt_tokens", "completion_tokens"):
        value = usage.get(name)
        if type(value) is not int or not 0 <= value <= 2**53 - 1:
            return WorkerFailure("InvalidUsage", "missing or invalid OpenRouter token usage")
    cost = usage.get("cost")
    if (
        isinstance(cost, bool)
        or not isinstance(cost, (int, float))
        or not math.isfinite(cost)
        or cost < 0
    ):
        return WorkerFailure("InvalidUsage", "OpenRouter returned missing or invalid cost")
    return None


class _PilotClient(OpenRouterClient, DescribedClient):
    def __init__(
        self, settings: OpenRouterSettings, api_key: str, configuration: dict[str, Any]
    ) -> None:
        self.settings = settings
        self._configuration = canonical_json(configuration)
        self._failure: WorkerFailure | None = None
        self._diagnostics = ResponseDiagnostics(api_key)
        http = httpx.AsyncClient(
            timeout=settings.timeout_s,
            follow_redirects=False,
            trust_env=False,
            event_hooks={"request": [self._check_request], "response": [self._check_response]},
        )
        super().__init__(
            model=settings.model,
            api_key=api_key,
            base_url=ENDPOINT,
            max_retries=0,
            timeout=settings.timeout_s,
            organization="",
            project="",
            http_client=http,
        )

    def configuration(self) -> dict[str, Any]:
        value: dict[str, Any] = json.loads(self._configuration)
        return value

    async def _check_request(self, request: httpx.Request) -> None:
        self._diagnostics.request(request.content)
        if request.method != "POST" or str(request.url) != ENDPOINT + "/chat/completions":
            self._failure = CompletionNotSent("InvalidRequest", "unexpected OpenRouter endpoint")
        elif len(request.content) > self.settings.max_request_body_bytes:
            self._failure = CompletionNotSent("InvalidRequest", "request body exceeds byte limit")
        if self._failure is not None:
            raise _RequestRejected(self._failure)

    async def _check_response(self, response: httpx.Response) -> None:
        self._diagnostics.status(response.status_code)
        if not response.is_success:
            return  # SDK raises; complete_result publishes only a safe status message.
        await response.aread()
        try:
            data = response.json()
        except (ValueError, UnicodeError, OverflowError):
            self._diagnostics.invalid_json()
            self._failure = WorkerFailure("InvalidResponse", "invalid OpenRouter JSON response")
        else:
            self._diagnostics.response(data)
            try:
                self._failure = _response_failure(data, self.settings)
            except (ValueError, UnicodeError, OverflowError):
                self._failure = WorkerFailure("InvalidResponse", "invalid OpenRouter JSON response")
        if self._failure is not None:
            raise _RequestRejected(self._failure)

    def diagnostics(self) -> dict[str, Any]:
        return self._diagnostics.snapshot()

    def _apply_extra_kwargs(self, kwargs: dict[str, Any]) -> None:
        super()._apply_extra_kwargs(kwargs)
        kwargs["extra_body"].update(provider=self.settings.routing(), transforms=[], plugins=[])
        kwargs["tool_choice"] = {"type": "function", "function": {"name": "submit_output"}}
        kwargs["stream"] = False

    async def complete_result(self, params: CompletionParams) -> LLMResponse | WorkerFailure:
        if self._closed:
            return CompletionNotSent("ClientClosed", "OpenRouter client is closed")
        if self._failure is not None:
            return self._failure
        if (
            params.provider_params
            or params.reasoning is not None
            or params.response_format is not None
            or type(params.max_tokens) is not int
            or not 1 <= params.max_tokens <= self.settings.max_output_tokens
            or not _source_tools_match(params.tools)
        ):
            return CompletionNotSent("InvalidRequest", "unsupported source-pilot request settings")
        try:
            return await super().complete(params)
        except Exception as error:
            # Do not publish raw SDK error bodies, which can contain provider
            # text or credentials. Cancellation remains control flow.
            self._failure = self._failure or WorkerFailure(
                "OpenRouterRequestFailed", f"OpenRouter request failed ({type(error).__name__})"
            )
            return self._failure

    async def complete(self, params: CompletionParams) -> LLMResponse:
        result = await self.complete_result(params)
        if isinstance(result, WorkerFailure):
            raise _RequestRejected(result)
        return result
