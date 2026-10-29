"""Extension cell ceilings, pending requalification against the served context."""

from typing import Self

from pydantic import BaseModel, ConfigDict, Field

SMOKE_SUBJECT_IDS = frozenset(
    {
        "oakridge-dbos-smoke-wf12",
        "oakridge-dbos-smoke-edit-wf13",
        "oakridge-dbos-verification-pilot-edit",
    }
)

# Served contexts recorded by the fleet: workflow_edit/publish.py for coder,
# workflow_edit/DECISIONS.md (Qwen3.6 section) for the newer route. Extension
# requalification must verify both values and the byte-envelope measurements.
DERIVATION_SOURCE = (
    "experiments/workflow_edit/publish.py:30 and "
    "experiments/workflow_edit/DECISIONS.md:312; extension requalification smoke"
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
    max_tool_schema_bytes: int = Field(default=12_288, gt=0, description=DERIVATION_SOURCE)
    max_tool_output_bytes: int = Field(default=24_576, gt=0, description=DERIVATION_SOURCE)
    max_conversation_bytes: int = Field(default=81_920, gt=0, description=DERIVATION_SOURCE)
    max_request_bytes: int = Field(default=98_304, gt=0, description=DERIVATION_SOURCE)
    max_response_bytes: int = Field(default=65_536, gt=0, description=DERIVATION_SOURCE)
    max_output_tokens: int = Field(default=4_096, gt=0, description=DERIVATION_SOURCE)
    max_storage_mb: int = Field(default=512, gt=0, description=DERIVATION_SOURCE)

    @classmethod
    def from_served_context(cls, tokens: int) -> Self:
        """Derive byte budgets from the observed context before requalification."""
        if tokens < 16_384:
            raise ValueError("extension route serves fewer than 16,384 context tokens")
        return cls(
            served_context_tokens=tokens,
            max_tool_schema_bytes=3 * tokens // 8,
            max_tool_output_bytes=3 * tokens // 4,
            max_conversation_bytes=5 * tokens // 2,
            max_request_bytes=3 * tokens,
            max_response_bytes=2 * tokens,
            max_output_tokens=min(tokens // 8, 8_192),
        )

    @classmethod
    def for_model(cls, model: str) -> Self:
        try:
            served = SERVED_CONTEXT_BY_MODEL[model]
        except KeyError as error:
            raise ValueError(f"unauthorized extension model: {model}") from error
        return cls.from_served_context(served)
