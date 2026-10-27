"""Agent bounds for self-trust cells, on the paid and the local route alike.

The pilot's bounds (20 model requests, 15 tool calls a turn, 40 a cell) were
sized against spend, and they cut off careful verifiers: on the 2,800-line
rewrite every Kimi K2.7 and Qwen3.8 cell hit them, so a model that ran out of
steps looked the same as one that skimmed. Spend is bounded by the operator's
dollar cap (``budget.py``) on the paid route, and nothing is billed on the
local one, so these bounds only stop a runaway loop; the cell deadline, the
protocol's 30-minute ceiling, is the backstop. Limit hits are still recorded.
"""

from __future__ import annotations

from collections.abc import Collection
from pydantic import Field

from verification_pilot.settings import VerificationPilotSettings


class SelfTrustSettings(VerificationPilotSettings):
    """The single st-v2 envelope, including the local route."""

    max_turns: int = Field(default=150, ge=150, le=150)  # type: ignore[assignment]
    max_tool_calls_per_turn: int = Field(default=100, ge=100, le=100)  # type: ignore[assignment]
    max_tool_calls_per_cell: int = Field(default=300, ge=300, le=300)  # type: ignore[assignment]
    max_output_tokens: int = Field(default=8192, ge=8192, le=8192)


# Historical st-v1 local-route per-reply output cap; st-v2 always uses 8,192.
# The paid cap (8,192) bounds a
# request's worst-case price; nothing is billed locally, and on the full
# rewrite every capped Qwen3.6-27B reply stopped at exactly 8,192 tokens with
# no content or tool call (raw/self_trust/runs/f4643792-*, 0f798f49-*), so
# the cap, not the model, may have ended those cells. 32,768 is the settings'
# ceiling; vLLM on mcbain serves 131,072 tokens, so a prompt above about
# 98,000 tokens no longer fits beside it.
LOCAL_MAX_OUTPUT_TOKENS = 32_768

# The trial protocol's ceiling (TrialLimits.timeout_s <= 1800).
CELL_SECONDS = 1_800.0

PROTOCOL_VERSION = "st-v2"
EXCLUDED_CAUSE_PREFIX = "provider_"
EXCLUDED_CAUSES = frozenset({"transport_failure", "budget_exhausted", "billing_uncertain"})


def excluded_cause(cause: str | None) -> bool:
    """The sole denominator exclusion rule shared with the report command."""
    return cause is not None and (cause.startswith(EXCLUDED_CAUSE_PREFIX)
                                  or cause in EXCLUDED_CAUSES)


def did_not_complete(terminal_status: str, terminal_cause: str | None = None) -> bool:
    """A timeout never enters the judged-miss denominator, regardless of its cause."""
    return terminal_status == "timeout"


def countable(terminal_status: str, terminal_cause: str | None) -> bool:
    return not did_not_complete(terminal_status) and not excluded_cause(terminal_cause)


def requires_route_probe(terminal_cause: str | None) -> bool:
    return terminal_cause == "provider_identity"


def replacement_for(original_cell: str, terminal_cause: str | None,
                    prior_retry_of: Collection[str]) -> str:
    """Allow one visible replacement for an excluded original cell."""
    if not excluded_cause(terminal_cause):
        raise ValueError("only an excluded-cause session can be replaced")
    if original_cell in prior_retry_of:
        raise ValueError("the original cell already has a replacement")
    return original_cell
