"""Stable Smithers submission identity for each extension cell and turn."""

from __future__ import annotations

from workflow_edit.dispatch import cell_idempotency_key as _bridge_cell_key

from assay.models import CellCoordinate


def cell_idempotency_key(run_id: str, coordinate: CellCoordinate) -> str:
    """Match the key the extension bridge submits, including run and coordinate."""
    return _bridge_cell_key(run_id, coordinate)
