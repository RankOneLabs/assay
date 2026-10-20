"""The plan uses 16 base subjects and 24 fixture-derived sessions."""

import pytest

from assay.models import CellCoordinate
from verification_pilot.arms import ALL_ARMS, TIER_1_ARMS
from verification_pilot.fixtures import base_subjects, pilot_sessions
from verification_pilot.shape import validate_worker_grid


def test_grid_matches_derived_sessions_once_each() -> None:
    subjects = base_subjects()
    sessions = pilot_sessions(subjects)
    subject_ids = [subject.id for subject in subjects]
    active_ids = tuple(dict.fromkeys(session.subject_id for session in sessions))
    cells = [CellCoordinate(subject_id=session.subject_id, arm_id=session.arm_id,
                            worker_repeat=0, realization_ref="sha256:" + "0" * 64)
             for session in sessions]
    validate_worker_grid(subject_ids=subject_ids, arm_ids=ALL_ARMS, cells=cells,
                         worker_repeats=1, active_arms=TIER_1_ARMS,
                         active_subject_ids=active_ids)
    with pytest.raises(ValueError, match="worker_repeats must be 1"):
        validate_worker_grid(subject_ids=subject_ids, arm_ids=ALL_ARMS, cells=cells,
                             worker_repeats=3, active_subject_ids=active_ids)
    with pytest.raises(ValueError, match="exactly once"):
        validate_worker_grid(subject_ids=subject_ids, arm_ids=ALL_ARMS, cells=cells[:-1],
                             worker_repeats=1, active_subject_ids=active_ids)
