"""Part 1 repository-agent limits, separate from the DRY pilot settings.

Every size below is provisional until the wf-12 measurements in
``experiments/workflow_edit/SMOKE.md`` replace it.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

PROVISIONAL_SOURCE = "experiments/workflow_edit/SMOKE.md"


class Part1AgentSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    max_turns: Literal[20] = 20
    attempts: Literal[1] = 1
    concurrency: Literal[1] = 1
    provider_retries: Literal[0] = 0
    sdk_retries: Literal[0] = 0
    max_tool_schema_bytes: int = Field(
        default=16_384,
        ge=1,
        le=1_000_000,
        description=f"Provisional; replace from {PROVISIONAL_SOURCE} (wf-12).",
    )
    max_tool_output_bytes: int = Field(
        default=16_384,
        ge=1,
        le=1_000_000,
        description=f"Provisional per tool result; replace from {PROVISIONAL_SOURCE} (wf-12).",
    )
    max_conversation_bytes: int = Field(
        default=262_144,
        ge=1,
        le=4_000_000,
        description=f"Provisional across 20 turns; replace from {PROVISIONAL_SOURCE} (wf-12).",
    )
    max_request_bytes: int = Field(
        default=327_680,
        ge=1,
        le=4_000_000,
        description=f"Provisional including tools; replace from {PROVISIONAL_SOURCE} (wf-12).",
    )
    max_response_bytes: int = Field(
        default=65_536,
        ge=1,
        le=1_000_000,
        description=f"Provisional per turn; replace from {PROVISIONAL_SOURCE} (wf-12).",
    )
    max_output_tokens: int = Field(
        default=2_048,
        ge=1,
        le=32_768,
        description=f"Provisional per turn; replace from {PROVISIONAL_SOURCE} (wf-12).",
    )
    max_storage_mb: int = Field(
        default=512,
        ge=1,
        le=4_096,
        description=(
            f"Provisional per-cell writable quota; replace from {PROVISIONAL_SOURCE} (wf-12)."
        ),
    )
