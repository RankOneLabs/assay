"""Extension cell ceilings from qualified route envelopes and image smoke."""

from typing import Self

from pydantic import BaseModel, ConfigDict, Field

SMOKE_SUBJECT_IDS = frozenset(
    {
        "oakridge-dbos-smoke-wf12",
        "oakridge-dbos-smoke-edit-wf13",
        "oakridge-dbos-verification-pilot-edit",
    }
)

# Served contexts recorded by the fleet: workflow_edit/publish.py for coder and
# workflow_edit/DECISIONS.md for Qwen3.6. The coder byte envelope is qualified
# in workflow_edit/SMOKE.md; the Qwen3.6 envelope was pinned for the verification
# pilot's measured source slice in verification_pilot/settings.py. Extension
# image smoke measurements and their limits are recorded in DECISIONS.md.
DERIVATION_SOURCE = (
    "experiments/workflow_edit/SMOKE.md:126 and "
    "experiments/verification_pilot/settings.py:43; "
    "experiments/code_extension/DECISIONS.md: extension image smoke"
)
SERVED_CONTEXT_BY_MODEL = {
    "qwen-coder-32b": 32_768,
    "qwen3.6-27b": 131_072,
}


class ExtensionAgentSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    served_context_tokens: int = Field(default=32_768, ge=16_384, description=DERIVATION_SOURCE)
    max_turns: int = Field(default=20, ge=20, le=200, description=DERIVATION_SOURCE)
    timeout_s: float = Field(default=900.0, gt=0, description=DERIVATION_SOURCE)
    attempts: int = Field(default=1, ge=1, le=1, description=DERIVATION_SOURCE)
    concurrency: int = Field(default=1, ge=1, le=1, description=DERIVATION_SOURCE)
    provider_retries: int = Field(default=0, ge=0, le=0, description=DERIVATION_SOURCE)
    sdk_retries: int = Field(default=0, ge=0, le=0, description=DERIVATION_SOURCE)
    max_tool_schema_bytes: int = Field(default=16_384, gt=0, description=DERIVATION_SOURCE)
    max_tool_output_bytes: int = Field(default=32_768, gt=0, description=DERIVATION_SOURCE)
    max_conversation_bytes: int = Field(default=81_920, gt=0, description=DERIVATION_SOURCE)
    max_request_bytes: int = Field(default=98_304, gt=0, description=DERIVATION_SOURCE)
    max_response_bytes: int = Field(default=131_072, gt=0, description=DERIVATION_SOURCE)
    max_output_tokens: int = Field(default=8_192, gt=0, description=DERIVATION_SOURCE)
    max_storage_mb: int = Field(default=512, gt=0, description=DERIVATION_SOURCE)

    @classmethod
    def for_model(cls, model: str) -> Self:
        if model == "qwen-coder-32b":
            return cls(served_context_tokens=SERVED_CONTEXT_BY_MODEL[model])
        if model == "qwen3.6-27b":
            return cls(
                served_context_tokens=SERVED_CONTEXT_BY_MODEL[model],
                max_tool_schema_bytes=16_384,
                max_tool_output_bytes=32_768,
                max_conversation_bytes=3_670_016,
                max_request_bytes=3_932_160,
                max_response_bytes=131_072,
                max_output_tokens=8_192,
            )
        raise ValueError(f"unauthorized extension model: {model}")
