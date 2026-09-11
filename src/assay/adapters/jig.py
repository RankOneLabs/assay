"""The narrow Jig boundary used by Assay cells."""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

from jig import AgentConfig, run_agent
from pydantic import BaseModel

from assay.canonical import canonical_json
from assay.execution import Accounting, WorkerFailure, WorkerResult, WorkerSuccess


def _configuration(value: Any) -> Any:
    """Serialize settings, requiring live resources to describe their own identity.

    Opaque clients, tools and dynamic prompt callbacks cannot be authorized by a
    caller-supplied label. Resource adapters must expose a JSON configuration()
    which includes model, endpoint, implementation revision and inference options.
    Credentials and connection state must not be included.
    """
    if isinstance(value, Enum):
        return value.value
    if value is None or isinstance(value, str | bool | int | float):
        return value
    if isinstance(value, type) and issubclass(value, BaseModel):
        return {
            "type": f"{value.__module__}.{value.__qualname__}",
            "schema": value.model_json_schema(),
        }
    describe = getattr(value, "configuration", None)
    if callable(describe):
        configuration = describe()
        canonical_json(configuration)
        return {
            "type": f"{type(value).__module__}.{type(value).__qualname__}",
            "configuration": configuration,
        }
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            item.name: _configuration(getattr(value, item.name))
            for item in dataclasses.fields(value)
        }
    if isinstance(value, tuple | list):
        return [_configuration(item) for item in value]
    if isinstance(value, dict):
        return {key: _configuration(item) for key, item in value.items()}
    raise ValueError(f"{type(value).__name__} must expose a stable configuration()")


@dataclass(slots=True)
class JigWorker:
    """Invoke ``jig.run_agent`` once; Assay remains responsible for the grid."""

    configs: Mapping[str, AgentConfig[Any]]
    version: str

    def configuration(self, arm_id: str) -> dict[str, Any]:
        config = self.configs[arm_id]
        if not isinstance(config.system_prompt, str):
            raise ValueError("materialize a static system prompt before authorization")
        return {
            "id": "jig-agent",
            "version": self.version,
            "config": _configuration(config),
            "output": "parsed-or-text-v1",
        }

    async def run(self, *, input_value: Any, arm_id: str) -> WorkerResult:
        # Strings are the materialized prompt; converting a JSON object with str()
        # silently changes its representation and therefore its governed boundary.
        if not isinstance(input_value, str):
            return WorkerFailure("InvalidInput", "Jig realizations must contain a prompt string")
        result = await run_agent(self.configs[arm_id], input_value)
        grading = dataclasses.asdict(result.grading) if result.grading is not None else None
        trace = {
            "trace_id": result.trace_id,
            "grading": grading,
            "usage": result.usage,
            "duration_ms": result.duration_ms,
        }
        # Jig's total_cost defaults to zero even when a provider has no rates.
        # Preserve that raw value in the trace but never claim it is measured spend.
        names = {
            "total_input_tokens": "input_tokens",
            "total_output_tokens": "output_tokens",
            "llm_calls": "llm_calls",
            "tool_calls": "tool_calls",
        }
        usage = {
            target: result.usage[source]
            for source, target in names.items()
            if source in result.usage
        }
        accounting = Accounting(usage=usage or None)
        if result.error is not None:
            return WorkerFailure(
                type(result.error).__name__, str(result.error), trace=trace, accounting=accounting
            )
        output = result.parsed if result.parsed is not None else result.output
        if isinstance(output, BaseModel):
            output = output.model_dump(mode="json")
        return WorkerSuccess(
            output=output,
            trace=trace,
            accounting=accounting,
        )
