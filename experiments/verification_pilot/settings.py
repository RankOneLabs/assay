"""Frozen repository-agent bounds for the verification pilot.

The pinned envelope is sized against the rendered fixture, rather than a
per-use-site tool-output projection: the largest rendered request message
array is 2,843 bytes, the StageInstanceId use-site lines total 9,512 bytes,
and the whole 62-file source slice is 348,936 bytes. The 3,670,016-byte
conversation ceiling leaves room for repeated inspection of that real slice;
the 3,932,160-byte request ceiling adds room for the tool schema. Live
qualification still records actual usage and limit hits, since arbitrary
tool outputs can exceed either ceiling. The bridge records a typed
``conversation_limit`` stop in the partial trace.

The pilot defaults to writable ``src/`` and ``tests/`` directories; self-trust
rungs derive their own writable directories from fixture changes. Historical
G6 decoy carriers are read-only documents; the protected-name guard also
rejects package and TypeScript manifest changes.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

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
    writable_prefixes: tuple[str, ...] = ("src/", "tests/")

    @field_validator("writable_prefixes")
    @classmethod
    def validate_writable_prefixes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or any(not prefix or not prefix.endswith("/") or prefix.startswith("/")
                            or "//" in prefix or any(part in (".", "..")
                                                  for part in prefix[:-1].split("/"))
                            for prefix in value):
            raise ValueError("writable_prefixes must contain canonical relative directories")
        return value
    max_tool_calls_per_turn: Literal[15] = 15
    max_tool_calls_per_cell: Literal[40] = 40
