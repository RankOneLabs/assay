"""Reject malformed pilot execution grids before authorization."""

from collections.abc import Sequence

from assay.models import CellCoordinate
from verification_pilot.arms import ALL_ARMS, TIER_1_ARMS
from verification_pilot.settings import PILOT_SUBJECT_IDS


def validate_worker_grid(*, subject_ids: Sequence[str], arm_ids: Sequence[str],
                         cells: Sequence[CellCoordinate], worker_repeats: int,
                         active_arms: Sequence[str] = TIER_1_ARMS,
                         active_subject_ids: Sequence[str] | None = None) -> None:
    if len(subject_ids) != 48 or len(set(subject_ids)) != 48:
        raise ValueError("pilot requires 48 unique rotated subjects")
    if PILOT_SUBJECT_IDS.intersection(subject_ids):
        raise ValueError("qualification smoke subject cannot enter the pilot grid")
    if len(arm_ids) != len(ALL_ARMS) or set(arm_ids) != set(ALL_ARMS):
        raise ValueError("pilot requires every declared tier arm")
    if not active_arms or not set(active_arms) <= set(ALL_ARMS):
        raise ValueError("invalid active pilot arms")
    if worker_repeats != 1:
        raise ValueError("pilot rotation is a subject attribute; worker_repeats must be 1")
    active_subject_ids = subject_ids if active_subject_ids is None else active_subject_ids
    if not active_subject_ids or not set(active_subject_ids) <= set(subject_ids):
        raise ValueError("invalid active pilot subjects")
    expected = {(subject, arm, 0) for subject in active_subject_ids for arm in active_arms}
    actual = [(cell.subject_id, cell.arm_id, cell.worker_repeat) for cell in cells]
    if len(actual) != len(expected) or set(actual) != expected:
        raise ValueError("pilot worker grid must cover each active coordinate exactly once")
