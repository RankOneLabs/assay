"""Part 1 repository-agent ceilings qualified by the wf-13 smoke run."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from verification_pilot import PILOT_SUBJECT_IDS

MEASUREMENT_SOURCE = "experiments/workflow_edit/SMOKE.md"
SMOKE_EDIT_SUBJECT_ID = "oakridge-dbos-smoke-edit-wf13"
# Every qualification subject ever run, so none can enter a study population.
SMOKE_SUBJECT_IDS = (
    frozenset({"oakridge-dbos-smoke-wf12", SMOKE_EDIT_SUBJECT_ID}) | PILOT_SUBJECT_IDS
)


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
        description=f"Qualified ceiling; derivation and observed usage in {MEASUREMENT_SOURCE}.",
    )
    max_tool_output_bytes: int = Field(
        default=32_768,
        ge=1,
        le=1_000_000,
        description=(
            f"Qualified per-tool ceiling; derivation and observed usage in {MEASUREMENT_SOURCE}."
        ),
    )
    max_conversation_bytes: int = Field(
        default=81_920,
        ge=1,
        le=4_000_000,
        description=(
            "Qualified conversation ceiling, sized to the served context window; "
            f"derivation and observed usage in {MEASUREMENT_SOURCE}."
        ),
    )
    max_request_bytes: int = Field(
        default=98_304,
        ge=1,
        le=4_000_000,
        description=(
            f"Qualified request ceiling; derivation and observed usage in {MEASUREMENT_SOURCE}."
        ),
    )
    max_response_bytes: int = Field(
        default=131_072,
        ge=1,
        le=1_000_000,
        description=(
            f"Qualified response ceiling; derivation and observed usage in {MEASUREMENT_SOURCE}."
        ),
    )
    max_output_tokens: int = Field(
        default=8_192,
        ge=1,
        le=32_768,
        description=(
            f"Qualified token ceiling; derivation and observed usage in {MEASUREMENT_SOURCE}."
        ),
    )
    max_storage_mb: int = Field(
        default=512,
        ge=1,
        le=4_096,
        description=(
            "Qualified per-cell writable quota; derivation and observed usage in "
            f"{MEASUREMENT_SOURCE}."
        ),
    )
