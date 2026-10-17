"""Frozen repository-agent bounds for the verification pilot.

The tool digest and limits remain pinned while the raw slice and fixture
population are rebuilt. Live qualification must record actual conversation
usage and limit hits for the new 24-session design before interpreting a
route. The bridge reports a conversation-limit stop as ``no_submission`` with
``conversation_limit`` in its detail because the shared ``CandidateCause``
wire type has no dedicated member.

Only ``src/`` and ``tests/`` are writable in generated workspaces. Historical
G6 decoy carriers are read-only documents; the protected-name guard also
rejects package and TypeScript manifest changes.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# Canonical JSON digest of PILOT_TOOL_SCHEMAS (T1 and T2/T3) in agent_loop.py.
# The separate legacy TOOLS digest remains pinned by workflow_edit's identity test.
PILOT_TOOLS_SHA256 = "sha256:615837c38e0f50abc34b5c5e4d3b41571d241b3199ca70743ef4346583c73cdd"


class VerificationPilotSettings(BaseModel):
    """Frozen bounds for one verification-pilot repository-agent attempt."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    max_turns: Literal[20] = 20
    attempts: Literal[1] = 1
    concurrency: Literal[1] = 1
    provider_retries: Literal[0] = 0
    sdk_retries: Literal[0] = 0
    max_tool_schema_bytes: int = Field(default=16_384, ge=1, le=1_000_000)
    max_tool_output_bytes: int = Field(default=32_768, ge=1, le=1_000_000)
    max_conversation_bytes: int = Field(default=3_670_016, ge=1, le=4_000_000)
    max_request_bytes: int = Field(default=3_932_160, ge=1, le=4_000_000)
    max_response_bytes: int = Field(default=131_072, ge=1, le=1_000_000)
    max_output_tokens: int = Field(default=8_192, ge=1, le=32_768)
    max_storage_mb: int = Field(default=512, ge=1, le=4_096)
    writable_prefixes: tuple[Literal["src/"], Literal["tests/"]] = ("src/", "tests/")
    max_tool_calls_per_turn: Literal[15] = 15
    max_tool_calls_per_cell: Literal[40] = 40
