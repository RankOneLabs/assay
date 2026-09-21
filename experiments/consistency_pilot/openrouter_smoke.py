"""Proposed Qwen smoke policy. Constructing this policy does not authorize spend.

The Jig worker stack this module's settings are shaped for requires the
``assay[legacy]`` extra. Importing this module never requires Jig; only calling
one of these functions does, and a missing extra fails with an actionable
error at that point rather than at import time.
"""

from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from assay.adapters.consistency import PilotSettings


def _pilot_settings() -> type["PilotSettings"]:
    try:
        from assay.adapters.consistency import PilotSettings
    except ModuleNotFoundError as error:
        from assay.adapters import missing_legacy_extra

        raise missing_legacy_extra("consistency_pilot.openrouter_smoke", error) from error
    return PilotSettings


def qwen_smoke_settings() -> "PilotSettings":
    """Twelve executions, at most 24 requests, $0.48 admission ceiling per run."""
    return _pilot_settings()(
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


def haiku_smoke_settings() -> "PilotSettings":
    """Twelve executions, at most 24 requests, $1.44 admission ceiling per run."""
    return _pilot_settings()(
        mode="paid",
        max_total_requests=24,
        max_spend_usd=Decimal("1.44"),
        request_cost_bound_usd=Decimal("0.06"),
        pricing_basis=(
            "OpenRouter inline usage.cost (USD credits), Claude 3 Haiku via "
            "Amazon Bedrock; 2026-09-11 rate caps $0.25/$1.25 per million "
            "input/output tokens; no per-request fee; bound assumes <=200000 "
            "input and <=2048 output tokens, no BYOK, paid plugins, or "
            "additional charges; operator must validate before execution"
        ),
    )
