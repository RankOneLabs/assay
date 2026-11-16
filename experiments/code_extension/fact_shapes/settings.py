"""Typed routes and pilot allocation; spending caps are operator inputs."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field

from code_extension.config import ModelRoute
from code_extension.fact_shapes.cells import Shape as FactShape
from code_extension.settings import BoundEnvelope

type StudyModelName = Literal["sol", "argon", "midtier"]
STUDY_ENVELOPE: BoundEnvelope = "fact-shapes-v1"
FACT_SHAPES: tuple[FactShape, ...] = get_args(FactShape)


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


PER_ATTEMPT_CAPS = PerAttemptCaps(sol=Decimal("2.00"), argon=Decimal("4.00"),
                                  midtier=Decimal("1.00"))
PILOT_TOTAL_CAP_USD = Decimal("15.00")
LIBRARY_RERUN_TOTAL_CAP_USD = Decimal("5.00")
# Original 30–45 s observation was supplied in the Oakridge cohort brief.
# Its receipt has not been located; the related retained rerun below measures
# about 31 s mean request reservation-to-settlement time (not a 30–45 s range).
QWEN_OBSERVATION_CITATION = (
    "Oakridge run run-ac759ddfd75b759f, routes-and-envelope cohort brief, "
    "decision operator_mid_tier_pick (2026-11-15); original receipt unavailable. "
    "Related retained evidence: ~/studies/assay-code-extension/scenario-library-2026-11/"
    "plans/d5b866a43310adbedbc29cbc2c067d999387120fbaf4da4f2b304821988527c6/attempts.jsonl"
)


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
