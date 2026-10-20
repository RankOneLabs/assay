"""Validate the workflow edit worker grid before dispatch."""

from collections.abc import Sequence

from assay.models import CellCoordinate
from workflow_edit.arms import ARM_IDS
from workflow_edit.settings import SMOKE_SUBJECT_IDS


def validate_worker_grid(
    *,
    subject_ids: Sequence[str],
    arm_ids: Sequence[str],
    cells: Sequence[CellCoordinate],
    worker_repeats: int,
) -> None:
    """Require one cell for each subject, fixed arm, and worker repeat.

    The subject population and repeat count are supplied by the caller; this
    scaffold fixes only the four arm identifiers.
    """
    if len(arm_ids) != len(ARM_IDS) or set(arm_ids) != set(ARM_IDS):
        raise ValueError("workflow edit arms must be exactly the four declared ids")
    if not subject_ids or len(subject_ids) != len(set(subject_ids)):
        raise ValueError("workflow edit subject ids must be nonempty and unique")
    if SMOKE_SUBJECT_IDS.intersection(subject_ids):
        raise ValueError("the qualification smoke subject cannot enter a study population")
    if worker_repeats < 1:
        raise ValueError("worker_repeats must be positive")

    actual = [(cell.subject_id, cell.arm_id, cell.worker_repeat) for cell in cells]
    expected = {
        (subject_id, arm_id, repeat)
        for subject_id in subject_ids
        for arm_id in ARM_IDS
        for repeat in range(worker_repeats)
    }
    if len(actual) != len(expected) or set(actual) != expected:
        raise ValueError("workflow edit worker grid must cover each coordinate exactly once")
