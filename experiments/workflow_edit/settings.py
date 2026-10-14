"""Part 1 repository-agent ceilings qualified by the wf-12 smoke run."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

MEASUREMENT_SOURCE = "experiments/workflow_edit/SMOKE.md"
SMOKE_SUBJECT_ID = "oakridge-dbos-smoke-wf12"


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
        description=f"Qualified ceiling; observed usage in {MEASUREMENT_SOURCE}.",
    )
    max_tool_output_bytes: int = Field(
        default=16_384,
        ge=1,
        le=1_000_000,
        description=f"Qualified per-tool ceiling; observed usage in {MEASUREMENT_SOURCE}.",
    )
    max_conversation_bytes: int = Field(
        default=262_144,
        ge=1,
        le=4_000_000,
        description=f"Qualified conversation ceiling; observed usage in {MEASUREMENT_SOURCE}.",
    )
    max_request_bytes: int = Field(
        default=327_680,
        ge=1,
        le=4_000_000,
        description=f"Qualified request ceiling; observed usage in {MEASUREMENT_SOURCE}.",
    )
    max_response_bytes: int = Field(
        default=65_536,
        ge=1,
        le=1_000_000,
        description=f"Qualified response ceiling; observed usage in {MEASUREMENT_SOURCE}.",
    )
    max_output_tokens: int = Field(
        default=2_048,
        ge=1,
        le=32_768,
        description=f"Qualified token ceiling; observed usage in {MEASUREMENT_SOURCE}.",
    )
    max_storage_mb: int = Field(
        default=512,
        ge=1,
        le=4_096,
        description=(
            f"Qualified per-cell writable quota; observed usage in {MEASUREMENT_SOURCE}."
        ),
    )
