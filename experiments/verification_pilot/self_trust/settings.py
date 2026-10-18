"""Agent bounds for self-trust cells on the free local route.

The pilot's bounds (20 model requests, 15 tool calls a turn, 40 a cell) were
sized against spend, and they cut off careful verifiers: Qwen3.8 hit the
tool-call limit in all eight screen sessions. On the local route nothing is
billed, so these bounds only stop a runaway loop; the cell deadline is the
backstop. Limit hits are still recorded and reported.
"""

from __future__ import annotations

from pydantic import Field

from verification_pilot.settings import VerificationPilotSettings


class SelfTrustLocalSettings(VerificationPilotSettings):
    """Loose bounds for the zero-paid local route."""

    max_turns: int = Field(default=150, ge=20, le=200)  # type: ignore[assignment]
    max_tool_calls_per_turn: int = Field(default=100, ge=1, le=500)  # type: ignore[assignment]
    max_tool_calls_per_cell: int = Field(default=300, ge=1, le=1_000)  # type: ignore[assignment]


LOCAL_CELL_SECONDS = 7_200.0
