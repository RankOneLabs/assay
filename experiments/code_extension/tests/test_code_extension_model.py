"""The extension arm vocabulary and pre-dispatch grid gate."""

from collections.abc import Sequence

import pytest
from code_extension.arms import ARM_SET_FACTORS, BASELINE_ARM_ID, BASELINE_ARM_IDS
from code_extension.settings import SMOKE_SUBJECT_IDS
from code_extension.shape import validate_worker_grid
from pydantic import ValidationError

from assay.fixture_manifest import BaselineArmSet, CodeShapeArmSet, ModelProfileArmSet
from assay.models import CellCoordinate


def _cells(
    subject_ids: Sequence[str], arm_ids: Sequence[str], repeats: int
) -> list[CellCoordinate]:
    return [
        CellCoordinate(
            subject_id=subject_id,
            arm_id=arm_id,
            worker_repeat=repeat,
            realization_ref="sha256:" + "a" * 64,
        )
        for subject_id in subject_ids
        for arm_id in arm_ids
        for repeat in range(repeats)
    ]


def test_factor_vocabulary_and_baseline_arm() -> None:
    assert set(ARM_SET_FACTORS) == {
        "code_shape",
        "handoff_detail",
        "model_profile",
        "code_intelligence_mode",
        "baseline",
    }
    assert BASELINE_ARM_ID == "baseline"
    assert BASELINE_ARM_IDS == ("baseline",)
    assert BaselineArmSet(factor="baseline", arm_ids=("baseline",)).arm_ids == BASELINE_ARM_IDS
    with pytest.raises(ValidationError):
        BaselineArmSet.model_validate({"factor": "baseline", "arm_ids": ["baseline", "extra"]})


def test_grid_requires_every_coordinate_exactly_once() -> None:
    arm_set = CodeShapeArmSet(factor="code_shape", arm_ids=("shape-a", "shape-b"))
    cells = _cells(("subject-a", "subject-b"), arm_set.arm_ids, 2)
    validate_worker_grid(
        subject_ids=("subject-a", "subject-b"), arm_ids=arm_set, cells=cells, worker_repeats=2
    )
    for bad in (cells[:-1], [*cells, cells[0]]):
        with pytest.raises(ValueError, match="exactly once"):
            validate_worker_grid(
                subject_ids=("subject-a", "subject-b"), arm_ids=arm_set, cells=bad, worker_repeats=2
            )


def test_grid_refuses_smoke_subjects_duplicate_subjects_and_invalid_repeats() -> None:
    arm_set = ModelProfileArmSet(factor="model_profile", arm_ids=("model-a", "model-b"))
    for smoke in SMOKE_SUBJECT_IDS:
        with pytest.raises(ValueError, match="qualification smoke"):
            validate_worker_grid(
                subject_ids=(smoke,),
                arm_ids=arm_set,
                cells=_cells((smoke,), arm_set.arm_ids, 1),
                worker_repeats=1,
            )
    with pytest.raises(ValueError, match="unique"):
        validate_worker_grid(
            subject_ids=("subject-a", "subject-a"), arm_ids=arm_set, cells=[], worker_repeats=1
        )
    with pytest.raises(ValueError, match="positive"):
        validate_worker_grid(
            subject_ids=("subject-a",), arm_ids=arm_set, cells=[], worker_repeats=0
        )


def test_arm_set_refuses_duplicate_ids_and_mixed_factor_tag() -> None:
    with pytest.raises(ValidationError, match="unique"):
        CodeShapeArmSet(factor="code_shape", arm_ids=("same", "same"))
    with pytest.raises(ValidationError):
        CodeShapeArmSet.model_validate(
            {"factor": ["code_shape", "model_profile"], "arm_ids": ["shape", "model"]}
        )
