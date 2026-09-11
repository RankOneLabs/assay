"""Bounded, allowlisted transport observations; never raw bodies or headers."""

from __future__ import annotations

import copy
import re
from typing import Any

from assay.canonical import digest_bytes

MAX_REQUESTS = 10
MAX_TOOL_NAMES = 8
MAX_ID_CHARS = 128
MAX_LABEL_CHARS = 64
POLICY_REVISION = "openrouter-response-shape-v2"
FINISH_REASONS = ("stop", "length", "tool_calls", "content_filter", "function_call", "error")
TOOL_NAMES = ("submit_output",)
MESSAGE_FIELDS = (
    "content",
    "tool_calls",
    "function_call",
    "refusal",
    "reasoning",
    "reasoning_content",
    "reasoning_details",
)


def diagnostic_policy() -> dict[str, Any]:
    return {
        "revision": POLICY_REVISION,
        "max_requests": MAX_REQUESTS,
        "max_tool_names": MAX_TOOL_NAMES,
        "max_id_chars": MAX_ID_CHARS,
        "max_label_chars": MAX_LABEL_CHARS,
        "generation_id": "sha256-only",
        "finish_reasons": list(FINISH_REASONS),
        "native_finish_reasons": list(FINISH_REASONS),
        "tool_names": list(TOOL_NAMES),
        "unknown_label": "unknown",
        "message_fields": list(MESSAGE_FIELDS),
        "content_measure": "characters-not-bytes",
        "raw_bodies": False,
        "headers": False,
    }


def _kind(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, bool):
        return "boolean"
    return "number"


class ResponseDiagnostics:
    """One sequential client's request/response observations, capped at ten."""

    def __init__(self, secret: str) -> None:
        self._secret = secret
        self._requests: list[dict[str, Any]] = []
        self._current: dict[str, Any] | None = None
        self._truncated = False

    def _label(self, value: Any, allowed: tuple[str, ...]) -> str | None:
        if not isinstance(value, str):
            return None
        if not 0 < len(value) <= MAX_LABEL_CHARS:
            return "unknown"
        if self._secret in value:
            return None
        return value if value in allowed else "unknown"

    def _generation_id_sha256(self, value: Any) -> str | None:
        if not isinstance(value, str) or not 0 < len(value) <= MAX_ID_CHARS:
            return None
        if self._secret in value or re.fullmatch(r"gen-[A-Za-z0-9_-]+", value) is None:
            return None
        return digest_bytes(value.encode("ascii"))

    def request(self, body: bytes) -> None:
        self._current = None
        if len(self._requests) >= MAX_REQUESTS:
            self._truncated = True
            return
        self._current = {
            "request_body_sha256": digest_bytes(body),
            "request_body_bytes": len(body),
            "response_received": False,
        }
        self._requests.append(self._current)

    def status(self, status_code: int) -> None:
        if self._current is not None:
            self._current.update(response_received=True, http_status=status_code)

    def invalid_json(self) -> None:
        if self._current is not None:
            self._current["json_state"] = "invalid"

    def response(self, data: Any) -> None:
        event = self._current
        if event is None:
            return
        event["json_state"] = _kind(data)
        if not isinstance(data, dict):
            return
        event["generation_id_sha256"] = self._generation_id_sha256(data.get("id"))
        choices = data.get("choices")
        event["choices_kind"] = _kind(choices) if "choices" in data else "missing"
        event["choice_count"] = len(choices) if isinstance(choices, list) else None
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            return
        choice = choices[0]
        for name in ("finish_reason", "native_finish_reason"):
            event[name] = self._label(choice.get(name), FINISH_REASONS)
        message = choice.get("message")
        event["message_kind"] = _kind(message) if "message" in choice else "missing"
        if not isinstance(message, dict):
            return
        event["message_fields"] = {
            name: _kind(message[name]) if name in message else "missing" for name in MESSAGE_FIELDS
        }
        content = message.get("content")
        event["content_characters"] = len(content) if isinstance(content, str) else None
        calls = message.get("tool_calls")
        event["tool_call_count"] = len(calls) if isinstance(calls, list) else None
        if isinstance(calls, list):
            event["tool_names"] = [
                self._label(call["function"].get("name"), TOOL_NAMES)
                if isinstance(call, dict) and isinstance(call.get("function"), dict)
                else None
                for call in calls[:MAX_TOOL_NAMES]
            ]
            event["tool_names_truncated"] = len(calls) > MAX_TOOL_NAMES

    def snapshot(self) -> dict[str, Any]:
        return copy.deepcopy(
            {
                "revision": POLICY_REVISION,
                "requests": self._requests,
                "truncated": self._truncated,
            }
        )
