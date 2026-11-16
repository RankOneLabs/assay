"""Typed routes and pilot allocation; spending caps are operator inputs."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from code_extension.config import ModelRoute
from code_extension.settings import BoundEnvelope

type StudyModelName = Literal["sol", "argon", "midtier"]
type FactShape = Literal[
    "type-enforced", "reference", "name-only", "sibling-only", "outside-the-code", "existing-state",
]

STUDY_ENVELOPE: BoundEnvelope = "fact-shapes-v1"
FACT_SHAPES: tuple[FactShape, ...] = (
    "type-enforced", "reference", "name-only", "sibling-only", "outside-the-code", "existing-state",
)


@dataclass(frozen=True)
class StudyModel:
    name: StudyModelName
    route: ModelRoute


STUDY_MODELS: tuple[StudyModel, ...] = (
    StudyModel("sol", ModelRoute(endpoint="https://openrouter.ai/api/v1",
                                model="openai/gpt-6.1-sol", provider="azure/us")),
    StudyModel("argon", ModelRoute(endpoint="https://openrouter.ai/api/v1",
                                  model="google/gemini-4-argon", provider="google-vertex/global")),
    StudyModel("midtier", ModelRoute(endpoint="https://openrouter.ai/api/v1",
                                    model="openai/gpt-6-luna", provider="azure")),
)


class PerAttemptCaps(BaseModel):
    """USD spending decisions supplied by the operator, separate from model identity."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    sol: Decimal = Field(gt=0)
    argon: Decimal = Field(gt=0)
    midtier: Decimal = Field(gt=0)


@dataclass(frozen=True)
class PilotAllocation:
    model: StudyModelName
    shape: FactShape
    attempts: int
    task_type: Literal["additive"] = "additive"


PILOT_ALLOCATION: tuple[PilotAllocation, ...] = tuple(
    PilotAllocation(model.name, shape, 2 if model.name == "sol" else 1)
    for model in STUDY_MODELS for shape in FACT_SHAPES
)
