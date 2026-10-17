"""The pilot grid refuses foreign subjects and repeat-based rotations."""

import pytest

from assay.models import CellCoordinate
from verification_pilot.arms import ALL_ARMS, TIER_1_ARMS
from verification_pilot.settings import PILOT_SUBJECT_IDS
from verification_pilot.shape import validate_worker_grid


def test_refused_subject_cannot_enter_grid() -> None:
    refused = next(iter(PILOT_SUBJECT_IDS))
    subjects = [f"subject-{index}" for index in range(47)] + [refused]
    cells = [CellCoordinate(subject_id=subject, arm_id=arm, worker_repeat=0,
                            realization_ref="sha256:" + "0" * 64)
             for subject in subjects for arm in TIER_1_ARMS]
    with pytest.raises(ValueError, match="qualification smoke subject"):
        validate_worker_grid(subject_ids=subjects, arm_ids=ALL_ARMS, cells=cells,
                             worker_repeats=1)
    with pytest.raises(ValueError, match="worker_repeats must be 1"):
        validate_worker_grid(subject_ids=[f"subject-{index}" for index in range(48)],
                             arm_ids=ALL_ARMS, cells=cells, worker_repeats=3)
