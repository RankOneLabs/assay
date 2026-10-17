from __future__ import annotations

import ast
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from assay.models import CellCoordinate, Identifier
from workflow_edit.arms import ARM_IDS, MESS_00, MESS_HIGH, MESS_LOW, MESS_MID
from workflow_edit.shape import validate_worker_grid

_REF = "sha256:" + "0" * 64


def _cells(arm_ids: tuple[str, ...] = ARM_IDS) -> list[CellCoordinate]:
    return [
        CellCoordinate(
            subject_id=subject_id,
            arm_id=arm_id,
            worker_repeat=repeat,
            realization_ref=_REF,
        )
        for subject_id in ("subject-a", "subject-b")
        for arm_id in arm_ids
        for repeat in range(2)
    ]


def test_fixed_arm_ids_satisfy_assay_identifier() -> None:
    assert ARM_IDS == (MESS_00, MESS_LOW, MESS_MID, MESS_HIGH)
    adapter = TypeAdapter(Identifier)
    assert tuple(adapter.validate_python(arm_id) for arm_id in ARM_IDS) == ARM_IDS


def test_complete_grid_is_accepted() -> None:
    validate_worker_grid(
        subject_ids=("subject-a", "subject-b"),
        arm_ids=ARM_IDS,
        cells=_cells(),
        worker_repeats=2,
    )


@pytest.mark.parametrize(
    "arm_ids",
    [
        (MESS_00, MESS_LOW, MESS_MID),
        (MESS_00, MESS_LOW, MESS_MID, MESS_MID),
        (MESS_00, MESS_LOW, MESS_MID, "other"),
    ],
)
def test_grid_rejects_missing_duplicate_or_unknown_arm(arm_ids: tuple[str, ...]) -> None:
    with pytest.raises(ValueError, match="exactly the four declared ids"):
        validate_worker_grid(
            subject_ids=("subject-a", "subject-b"),
            arm_ids=arm_ids,
            cells=_cells(arm_ids),
            worker_repeats=2,
        )


def test_grid_rejects_missing_or_duplicate_cell() -> None:
    cells = _cells()
    for invalid_cells in (cells[:-1], [*cells, cells[0]]):
        with pytest.raises(ValueError, match="cover each coordinate exactly once"):
            validate_worker_grid(
                subject_ids=("subject-a", "subject-b"),
                arm_ids=ARM_IDS,
                cells=invalid_cells,
                worker_repeats=2,
            )


def test_package_does_not_import_dry_common() -> None:
    package = Path(__file__).resolve().parents[1]
    for path in package.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert "dry_common" not in (node.module or ""), path
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                assert all("dry_common" not in alias.name for alias in node.names), path
