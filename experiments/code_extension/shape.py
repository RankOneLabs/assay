"""Validate a declared extension worker grid before dispatch."""

from collections.abc import Sequence

from assay.fixture_manifest import ExtensionArmSet
from assay.models import CellCoordinate
from code_extension.arms import ARM_SET_FACTORS
from code_extension.settings import SMOKE_SUBJECT_IDS


def validate_worker_grid(
    *,
    subject_ids: Sequence[str],
    arm_ids: ExtensionArmSet,
    cells: Sequence[CellCoordinate],
    worker_repeats: int,
) -> None:
    """Require one cell per declared subject, arm and repeat of one factor."""
    if not isinstance(arm_ids.factor, str) or arm_ids.factor not in ARM_SET_FACTORS:
        raise ValueError("extension grid requires exactly one declared arm-set factor")
    if not subject_ids or len(subject_ids) != len(set(subject_ids)):
        raise ValueError("extension subject ids must be nonempty and unique")
    if SMOKE_SUBJECT_IDS.intersection(subject_ids):
        raise ValueError("qualification smoke subjects cannot enter a study population")
    if worker_repeats < 1:
        raise ValueError("worker_repeats must be positive")

    actual = [(cell.subject_id, cell.arm_id, cell.worker_repeat) for cell in cells]
    expected = {
        (subject_id, arm_id, repeat)
        for subject_id in subject_ids
        for arm_id in arm_ids.arm_ids
        for repeat in range(worker_repeats)
    }
    if len(actual) != len(expected) or set(actual) != expected:
        raise ValueError("extension worker grid must cover each coordinate exactly once")
