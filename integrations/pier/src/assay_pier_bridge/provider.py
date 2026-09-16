"""A narrow, fail-closed OpenRouter client bound to exactly one guarded route.

Deliberately self-contained: no dependency on ``assay`` or ``jig``, so the
bridge image's dependency set stays separately locked. The constants below
intentionally mirror ``assay.adapters.openrouter_policy.HAIKU_BEDROCK`` in
the root project rather than importing it (see README.md).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any, Final

import httpx

ENDPOINT: Final = "https://openrouter.ai/api/v1"
CHAT_COMPLETIONS_URL: Final = f"{ENDPOINT}/chat/completions"
MODEL: Final = "anthropic/claude-3-haiku"
PROVIDER: Final = "amazon-bedrock"
PROVIDER_NAME: Final = "Amazon Bedrock"
# USD per million tokens, mirroring assay.adapters.openrouter_policy.HAIKU_BEDROCK
# so this guarded route never routes to a more expensive provider than the
# root project's own governed catalogue permits.
MAX_PROMPT_PRICE_PER_MILLION: Final = 0.25
MAX_COMPLETION_PRICE_PER_MILLION: Final = 1.25
TOOL_NAME: Final = "submit_output"
MAX_REQUEST_BODY_BYTES: Final = 65_536
MAX_RESPONSE_BODY_BYTES: Final = 65_536
MAX_OUTPUT_TOKENS: Final = 2048
TIMEOUT_S: Final = 30.0


class GuardedRouteError(Exception):
    """The guarded HTTP boundary was not exactly the qualified route.

    Never carries a raw response body, header, or credential: only a stable
    machine-readable reason.
    """

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def submit_output_tool() -> dict[str, Any]:
    """The single tool this route's model may call, submitted exactly once."""
    return {
        "type": "function",
        "function": {
            "name": TOOL_NAME,
            "description": (
                "Submit your final answer. Call this exactly once when you have "
                "your result."
            ),
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "required": ["source"],
                "properties": {"source": {"type": "string", "minLength": 1}},
            },
            "strict": True,
        },
    }


@dataclass(frozen=True, slots=True)
class RouteUsage:
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float


@dataclass(frozen=True, slots=True)
class SubmittedOutput:
    call_id: str
    source: str


@dataclass(frozen=True, slots=True)
class RouteResponse:
    message: dict[str, Any]
    usage: RouteUsage
    submission: SubmittedOutput
    request_bytes: int


_ALLOWED_TOP_LEVEL_FIELDS = frozenset(
    {"id", "object", "created", "model", "provider", "choices", "usage"}
)
_ALLOWED_CHOICE_FIELDS = frozenset(
    {"index", "message", "finish_reason", "native_finish_reason", "logprobs"}
)
_ALLOWED_MESSAGE_FIELDS = frozenset({"role", "content", "tool_calls", "refusal", "reasoning"})
_ALLOWED_TOOL_CALL_FIELDS = frozenset({"id", "type", "function", "index"})
_ALLOWED_FUNCTION_CALL_FIELDS = frozenset({"name", "arguments"})
_ALLOWED_USAGE_FIELDS = frozenset(
    {"prompt_tokens", "completion_tokens", "total_tokens", "cost", "cost_details"}
)
_ALLOWED_SUBMISSION_ARGUMENT_FIELDS = frozenset({"source"})


def _fail_closed_on_unknown_fields(data: dict[str, Any], message: dict[str, Any]) -> None:
    if not _ALLOWED_TOP_LEVEL_FIELDS.issuperset(data):
        raise GuardedRouteError("unknown top-level response field")
    choices = data.get("choices")
    if (
        isinstance(choices, list)
        and choices
        and isinstance(choices[0], dict)
        and not _ALLOWED_CHOICE_FIELDS.issuperset(choices[0])
    ):
        raise GuardedRouteError("unknown choice field")
    usage = data.get("usage")
    if isinstance(usage, dict) and not _ALLOWED_USAGE_FIELDS.issuperset(usage):
        raise GuardedRouteError("unknown usage field")
    if not _ALLOWED_MESSAGE_FIELDS.issuperset(message):
        raise GuardedRouteError("unknown message field")
    tool_calls = message.get("tool_calls")
    if isinstance(tool_calls, list):
        for call in tool_calls:
            if not isinstance(call, dict) or not _ALLOWED_TOOL_CALL_FIELDS.issuperset(call):
                raise GuardedRouteError("unknown tool call field")
            function = call.get("function")
            if isinstance(function, dict) and not _ALLOWED_FUNCTION_CALL_FIELDS.issuperset(
                function
            ):
                raise GuardedRouteError("unknown tool call function field")


def _validate_submission(message: dict[str, Any], finish_reason: Any) -> SubmittedOutput:
    if finish_reason != "tool_calls":
        raise GuardedRouteError("response did not finish on a tool call")
    tool_calls = message.get("tool_calls")
    if not isinstance(tool_calls, list) or len(tool_calls) != 1:
        raise GuardedRouteError("response must carry exactly one tool call")
    call = tool_calls[0]
    if not isinstance(call, dict) or call.get("type") != "function":
        raise GuardedRouteError("tool call must be a function call")
    call_id = call.get("id")
    if not isinstance(call_id, str) or not call_id:
        raise GuardedRouteError("tool call is missing an id")
    function = call.get("function")
    if not isinstance(function, dict) or function.get("name") != TOOL_NAME:
        raise GuardedRouteError(f"tool call must invoke {TOOL_NAME}")
    raw_arguments = function.get("arguments")
    if not isinstance(raw_arguments, str):
        raise GuardedRouteError("tool call arguments must be a JSON string")
    try:
        arguments = json.loads(raw_arguments)
    except ValueError as error:
        raise GuardedRouteError("tool call arguments are not valid JSON") from error
    if not isinstance(arguments, dict) or not _ALLOWED_SUBMISSION_ARGUMENT_FIELDS.issuperset(
        arguments
    ):
        raise GuardedRouteError("tool call arguments carry an unknown field")
    source = arguments.get("source")
    if not isinstance(source, str) or not source:
        raise GuardedRouteError("tool call arguments are missing a nonblank source")
    return SubmittedOutput(call_id=call_id, source=source)


def _validate_response(data: Any, *, request_bytes: int) -> RouteResponse:
    if not isinstance(data, dict):
        raise GuardedRouteError("response is not a JSON object")
    if data.get("error") is not None:
        raise GuardedRouteError("response carries an error")
    choices = data.get("choices")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        raise GuardedRouteError("response must carry exactly one choice")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise GuardedRouteError("response choice is missing a message")
    _fail_closed_on_unknown_fields(data, message)
    if data.get("model") != MODEL or data.get("provider") != PROVIDER_NAME:
        raise GuardedRouteError("response model/provider identity mismatch")
    usage = data.get("usage")
    if not isinstance(usage, dict):
        raise GuardedRouteError("response is missing usage")
    prompt_tokens = usage.get("prompt_tokens")
    completion_tokens = usage.get("completion_tokens")
    cost = usage.get("cost")
    if type(prompt_tokens) is not int or type(completion_tokens) is not int:
        raise GuardedRouteError("response usage token counts are missing or invalid")
    if isinstance(cost, bool) or not isinstance(cost, (int, float)) or not math.isfinite(cost):
        raise GuardedRouteError("response usage cost is missing or invalid")
    if cost < 0 or prompt_tokens < 0 or completion_tokens < 0:
        raise GuardedRouteError("response usage values must be non-negative")
    submission = _validate_submission(message, choices[0].get("finish_reason"))
    return RouteResponse(
        message=message,
        usage=RouteUsage(
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens, cost_usd=float(cost)
        ),
        submission=submission,
        request_bytes=request_bytes,
    )


class GuardedOpenRouterClient:
    """One trial's client: at most one in-flight request, zero retries, no fallback."""

    def __init__(self, *, api_key: str, transport: httpx.BaseTransport | None = None) -> None:
        if not api_key or not api_key.strip() or any(char.isspace() for char in api_key):
            raise ValueError("a nonblank OpenRouter API key is required")
        self._api_key = api_key
        self._client = httpx.Client(
            timeout=TIMEOUT_S,
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )
        self._request_count = 0

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> GuardedOpenRouterClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def complete(self, *, system_prompt: str, user_message: str) -> RouteResponse:
        if self._request_count >= 1:
            raise GuardedRouteError("this route permits exactly one request per trial")
        body = {
            "model": MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "tools": [submit_output_tool()],
            "tool_choice": {"type": "function", "function": {"name": TOOL_NAME}},
            "max_tokens": MAX_OUTPUT_TOKENS,
            "stream": False,
            "provider": {
                "data_collection": "deny",
                "zdr": True,
                "only": [PROVIDER],
                "order": [PROVIDER],
                "allow_fallbacks": False,
                "require_parameters": True,
                "max_price": {
                    "prompt": MAX_PROMPT_PRICE_PER_MILLION,
                    "completion": MAX_COMPLETION_PRICE_PER_MILLION,
                    "request": 0,
                },
            },
        }
        payload = json.dumps(body).encode("utf-8")
        if len(payload) > MAX_REQUEST_BODY_BYTES:
            raise GuardedRouteError("request body exceeds byte limit")
        self._request_count += 1
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        try:
            with self._client.stream(
                "POST", CHAT_COMPLETIONS_URL, content=payload, headers=headers
            ) as response:
                if str(response.url) != CHAT_COMPLETIONS_URL or response.request.method != "POST":
                    raise GuardedRouteError("request left the guarded endpoint")
                if not response.is_success:
                    raise GuardedRouteError(f"non-success status {response.status_code}")
                body_bytes = bytearray()
                for chunk in response.iter_bytes():
                    body_bytes.extend(chunk)
                    if len(body_bytes) > MAX_RESPONSE_BODY_BYTES:
                        raise GuardedRouteError("response body exceeds byte limit")
        except httpx.HTTPError as error:
            raise GuardedRouteError(f"transport failure ({type(error).__name__})") from error
        try:
            data = json.loads(bytes(body_bytes))
        except ValueError as error:
            raise GuardedRouteError("response is not valid JSON") from error
        return _validate_response(data, request_bytes=len(payload))
