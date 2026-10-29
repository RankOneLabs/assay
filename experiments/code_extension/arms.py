"""Settled factor tags and first-run baseline arm identifier."""

from typing import Literal

from pydantic import TypeAdapter

from assay.models import Identifier

ArmSetFactor = Literal[
    "code_shape", "handoff_detail", "model_profile", "code_intelligence_mode", "baseline"
]
ARM_SET_FACTORS: tuple[ArmSetFactor, ...] = (
    "code_shape",
    "handoff_detail",
    "model_profile",
    "code_intelligence_mode",
    "baseline",
)

BASELINE_ARM_ID: str = TypeAdapter(Identifier).validate_python("baseline")
BASELINE_ARM_IDS: tuple[str, ...] = (BASELINE_ARM_ID,)
