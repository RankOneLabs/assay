"""Backend-neutral OpenRouter policy: settings and the pinned model catalogue.

Unlike ``assay.adapters.openrouter``, this module never imports Jig. Callers
that only need to declare or validate an OpenRouter profile (e.g. the DRY
experiment's governed Haiku check) can depend on it without pulling in the
legacy Jig/OpenRouter client stack.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from assay.models import WireModel

ENDPOINT = "https://openrouter.ai/api/v1"


class OpenRouterSettings(WireModel):
    """One explicit model/route. Price limits are USD per million tokens."""

    model: str = Field(pattern=r"^[a-z0-9-]+/[a-z0-9._-]+$")
    provider: str = Field(pattern=r"^[a-z0-9-]+(?:/[a-z0-9._-]+)?$")
    provider_name: str = Field(min_length=1, pattern=r"^\S(?:.*\S)?$")
    max_prompt_price: float = Field(gt=0, le=100, allow_inf_nan=False)
    max_completion_price: float = Field(gt=0, le=1000, allow_inf_nan=False)
    max_request_body_bytes: int = Field(default=65_536, ge=1, le=1_000_000, strict=True)
    max_output_tokens: int = Field(default=2048, ge=1, le=32_768, strict=True)
    timeout_s: float = Field(default=30, gt=0, le=600, allow_inf_nan=False)

    def routing(self) -> dict[str, Any]:
        return {
            "data_collection": "deny",
            "zdr": True,
            "only": [self.provider],
            "order": [self.provider],
            "allow_fallbacks": False,
            "require_parameters": True,
            "max_price": {
                "prompt": self.max_prompt_price,
                "completion": self.max_completion_price,
                "request": 0,
            },
        }


# Catalogue checked 2026-09-11. These are explicit rate caps, not live discovery
# or a promise that this remote model/route will remain available or unchanged.
QWEN_NOVITA = OpenRouterSettings(
    model="qwen/qwen3-coder-30b-a3b-instruct",
    provider="novita/fp8",
    provider_name="Novita",
    max_prompt_price=0.07,
    max_completion_price=0.27,
)


# Catalogue checked 2026-09-11. CoreWeave advertises required/function tool
# choice for this fixed route; the governed request still requires ZDR and
# rejects fallback providers.
GPT_OSS_120B_COREWEAVE = OpenRouterSettings(
    model="openai/gpt-oss-120b",
    provider="coreweave/fp4",
    provider_name="CoreWeave",
    max_prompt_price=0.03,
    max_completion_price=0.17,
)


# Catalogue checked 2026-09-11. The fixed model slug avoids the moving
# `~anthropic/claude-haiku-latest` alias; this remains a remote service boundary.
HAIKU_BEDROCK = OpenRouterSettings(
    model="anthropic/claude-3-haiku",
    provider="amazon-bedrock",
    provider_name="Amazon Bedrock",
    max_prompt_price=0.25,
    max_completion_price=1.25,
)
