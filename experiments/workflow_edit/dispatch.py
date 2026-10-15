"""One durable Smithers submission key per cell.

Each agent turn is its own Smithers job keyed ``<cell key>:t<turn>``
(``workflow_edit.bridge``), so a re-dispatch after a lost response is the same
job, and no two cells or runs can share one.
"""

from __future__ import annotations

import hashlib

from assay.canonical import canonical_json
from assay.models import CellCoordinate


def cell_idempotency_key(run_id: str, coordinate: CellCoordinate) -> str:
    """Stable across transport retries; distinct across runs and coordinates."""
    if not run_id:
        raise ValueError("run_id must be nonempty")
    material = canonical_json({"run_id": run_id, "cell_id": coordinate.id})
    return f"assay-workflow-edit:{hashlib.sha256(material).hexdigest()}"
