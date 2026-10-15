"""Every cell, and every turn within it, has one stable Smithers submission key."""

from assay.models import CellCoordinate
from workflow_edit.bridge import turn_idempotency_key
from workflow_edit.dispatch import cell_idempotency_key


def _coordinate(repeat: int = 0) -> CellCoordinate:
    return CellCoordinate(
        subject_id="subject", arm_id="mess-low", worker_repeat=repeat,
        realization_ref="sha256:" + "a" * 64,
    )


def test_cell_key_is_stable_and_scoped_to_run_and_cell() -> None:
    key = cell_idempotency_key("run-1", _coordinate())
    assert key == cell_idempotency_key("run-1", _coordinate())
    assert key != cell_idempotency_key("run-2", _coordinate())
    assert key != cell_idempotency_key("run-1", _coordinate(1))


def test_turn_keys_are_distinct_and_fit_smithers() -> None:
    key = cell_idempotency_key("run-1", _coordinate())
    turns = {turn_idempotency_key(key, turn) for turn in range(1, 21)}
    assert len(turns) == 20
    assert max(len(item) for item in turns) <= 255
