"""Narrow extension boundaries; core planning never receives these objects."""

from __future__ import annotations

from typing import Any, Protocol

from assay.execution import EvaluationResult, WorkerResult
from assay.models import Arm, EvaluationCoordinate, PriceEstimate, Realization, Subject


class SubjectMaterializer(Protocol):
    async def materialize_subjects(self) -> tuple[Subject, ...]: ...


class RealizationMaterializer(Protocol):
    async def materialize(self, *, subject: Subject, arm: Arm) -> Realization: ...


class WorkerPreparer(Protocol):
    async def prepare(self, *, arm: Arm, authorization: str) -> str: ...


class WorkerExecutor(Protocol):
    def configuration(self, arm_id: str) -> dict[str, Any]: ...

    async def run(self, *, input_value: Any, arm_id: str) -> WorkerResult: ...


class EvaluatorExecutor(Protocol):
    def configuration(self) -> dict[str, Any]: ...

    async def evaluate(
        self, *, input_value: Any, output: Any, coordinate: EvaluationCoordinate
    ) -> EvaluationResult: ...


class PriceEstimator(Protocol):
    def estimate(
        self, *, subjects: int, arms: tuple[Arm, ...], worker_repeats: int
    ) -> PriceEstimate: ...
