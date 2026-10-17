"""Stable model-dispatch keys for pilot cells and turns."""

import hashlib

from assay.canonical import canonical_json
from assay.models import CellCoordinate


def cell_idempotency_key(run_id: str, coordinate: CellCoordinate) -> str:
    if not run_id:
        raise ValueError("run_id must be nonempty")
    material = canonical_json({"run_id": run_id, "cell_id": coordinate.id})
    return f"assay-verification-pilot:{hashlib.sha256(material).hexdigest()}"


def turn_idempotency_key(cell_key: str, turn: int) -> str:
    if not cell_key or turn < 1:
        raise ValueError("cell key and positive turn are required")
    return f"{cell_key}:t{turn}"
