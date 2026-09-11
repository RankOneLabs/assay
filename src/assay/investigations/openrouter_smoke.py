"""Proposed Qwen smoke policy. Constructing this policy does not authorize spend."""

from decimal import Decimal

from assay.adapters.consistency import PilotSettings


def qwen_smoke_settings() -> PilotSettings:
    """Twelve executions, at most 24 requests, $0.48 admission ceiling per run."""
    return PilotSettings(
        mode="paid",
        max_total_requests=24,
        max_spend_usd=Decimal("0.48"),
        request_cost_bound_usd=Decimal("0.02"),
        pricing_basis=(
            "OpenRouter inline usage.cost (USD credits), Qwen3 Coder 30B via Novita FP8; "
            "2026-09-11 rate caps $0.07/$0.27 per million input/output tokens; "
            "no per-request fee; bound assumes <=160000 input and <=2048 output tokens, "
            "no BYOK, paid plugins, or additional charges; operator must validate before execution"
        ),
    )
