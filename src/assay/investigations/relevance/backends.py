"""The two IO boundaries of the relevance arms: Typesafe and OpenRouter.

Each backend takes a state object and a loaded catalogue and returns one
``ArmAnswer``. Both return answers in Jev's shape, so every decision mapping
downstream is backend-agnostic.

Exceptions are caught here and re-raised as ``BackendError`` carrying the arm,
evaluation id and detail, which is what the runner records as a failed cell. No
backend ever returns a partial or default answer vector: a short or malformed
reply is a failure, never a silent negative.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, cast

from assay.investigations.relevance.render import (
    answer_schema,
    normalize_answers,
    render_prompt,
    render_state,
)

OPENROUTER_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
REQUEST_TIMEOUT_SECONDS = 120.0


class BackendError(RuntimeError):
    """A single arm cell failed at its IO boundary."""

    def __init__(self, arm: str, evaluation_id: int, detail: str) -> None:
        super().__init__(f"{arm} evaluation {evaluation_id}: {detail}")
        self.arm = arm
        self.evaluation_id = evaluation_id
        self.detail = detail


@dataclass(frozen=True, slots=True)
class ArmAnswer:
    """One backend reply, normalized to Jev's answer shape."""

    answers: dict[str, Any]
    model: str
    request_id: str
    latency_ms: int
    usage: dict[str, int] = field(default_factory=dict)


class Backend(Protocol):
    """One arm's answering backend: ready-checked once, then called per cell."""

    def check_ready(self) -> None: ...

    def __call__(
        self, state: Mapping[str, Any], questions: Mapping[str, Any], evaluation_id: int
    ) -> ArmAnswer: ...


@dataclass(frozen=True, slots=True)
class TypesafeBackend:
    """Typesafe System One. The SDK is imported lazily so the module stays optional."""

    arm: str
    model: str = "jev-latest"

    def check_ready(self) -> None:
        """Fail before any cell dispatches if the optional SDK or key is absent."""
        import msgspec  # noqa: F401
        import typesafe_sdk  # noqa: F401

        if not os.environ.get("TYPESAFE_API_KEY"):
            raise RuntimeError(f"{self.arm}: TYPESAFE_API_KEY is not set")

    def __call__(
        self, state: Mapping[str, Any], questions: Mapping[str, Any], evaluation_id: int
    ) -> ArmAnswer:
        import msgspec
        from typesafe_sdk import JSONContent, RetryPolicy, TypeSafeClient

        started = time.monotonic()
        try:
            with TypeSafeClient(
                api_key=os.environ["TYPESAFE_API_KEY"],
                model=self.model,
                retry=RetryPolicy(max_retries=0),
                timeout=60.0,
            ) as client:
                response = client.system_one(
                    state=cast(JSONContent, state),
                    questions=questions,
                )
            payload = msgspec.to_builtins(response)
        except Exception as exc:  # IO boundary
            raise BackendError(self.arm, evaluation_id, f"{type(exc).__name__}: {exc}") from exc
        answers = payload.get("answers")
        if not isinstance(answers, dict):
            raise BackendError(self.arm, evaluation_id, "response answers are not an object")
        return ArmAnswer(
            answers=answers,
            model=str(payload.get("model", self.model)),
            request_id=str(payload.get("request_id", "")),
            latency_ms=round((time.monotonic() - started) * 1000),
            usage={
                key: int(value)
                for key, value in (payload.get("usage") or {}).items()
                if isinstance(value, int)
            },
        )


@dataclass(frozen=True, slots=True)
class OpenRouterBackend:
    """An LLM answering the rendered catalogue through OpenRouter structured output."""

    arm: str
    model: str

    def check_ready(self) -> None:
        """Fail before any cell dispatches if the client or key is absent."""
        import httpx  # noqa: F401

        if not os.environ.get("OPENROUTER_API_KEY"):
            raise RuntimeError(f"{self.arm}: OPENROUTER_API_KEY is not set")

    def __call__(
        self, state: Mapping[str, Any], questions: Mapping[str, Any], evaluation_id: int
    ) -> ArmAnswer:
        import httpx

        body = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": render_prompt(questions)},
                {"role": "user", "content": render_state(state)},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "catalogue_answers",
                    "strict": True,
                    "schema": answer_schema(questions),
                },
            },
            "provider": {
                "allow_fallbacks": False,
                "data_collection": "deny",
                "require_parameters": True,
            },
        }
        started = time.monotonic()
        try:
            response = httpx.post(
                OPENROUTER_ENDPOINT,
                headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"},
                json=body,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:  # IO boundary
            raise BackendError(self.arm, evaluation_id, f"{type(exc).__name__}: {exc}") from exc
        try:
            content = payload["choices"][0]["message"]["content"]
            reply = json.loads(content)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise BackendError(
                self.arm, evaluation_id, f"unreadable reply: {type(exc).__name__}: {exc}"
            ) from exc
        try:
            answers = normalize_answers(reply, questions)
        except ValueError as exc:
            raise BackendError(self.arm, evaluation_id, str(exc)) from exc
        usage = payload.get("usage") or {}
        return ArmAnswer(
            answers=answers,
            model=str(payload.get("model", self.model)),
            request_id=str(payload.get("id", "")),
            latency_ms=round((time.monotonic() - started) * 1000),
            usage={
                "input_tokens": int(usage.get("prompt_tokens", 0)),
                "output_tokens": int(usage.get("completion_tokens", 0)),
            },
        )
