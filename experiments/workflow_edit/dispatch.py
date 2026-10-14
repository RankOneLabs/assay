"""Bind Smithers routing identity and one durable submission key to each cell."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Protocol

from assay.adapters.smithers import SmithersClient, SmithersFactory
from assay.canonical import canonical_json
from assay.execution import WorkerResult
from assay.models import CellCoordinate


def cell_idempotency_key(run_id: str, coordinate: CellCoordinate) -> str:
    """Stable across transport retries; distinct across runs and coordinates."""
    if not run_id:
        raise ValueError("run_id must be nonempty")
    material = canonical_json({"run_id": run_id, "cell_id": coordinate.id})
    return f"assay-workflow-edit:{hashlib.sha256(material).hexdigest()}"


class SmithersCellDelegate(Protocol):
    def configuration(self, arm_id: str) -> dict[str, Any]: ...

    async def run_cell(
        self, *, input_value: Any, coordinate: CellCoordinate, client: SmithersClient
    ) -> WorkerResult: ...


@dataclass(frozen=True)
class SmithersBoundWorker:
    """Expose the Smithers identity inside the arm's authorized worker bytes."""

    delegate: SmithersCellDelegate
    client_factory: SmithersFactory
    run_id: str
    supports_cell_coordinates: bool = True

    def configuration(self, arm_id: str) -> dict[str, Any]:
        configuration = self.delegate.configuration(arm_id)
        return {**configuration, "smithers": self.client_factory.configuration()}

    def client_for_cell(self, run_id: str, coordinate: CellCoordinate) -> SmithersClient:
        """Bind the cell key only when a concrete dispatch is created."""
        return self.client_factory.create(
            idempotency_key=cell_idempotency_key(run_id, coordinate)
        )

    async def run_cell(self, *, input_value: Any, coordinate: CellCoordinate) -> WorkerResult:
        client = self.client_for_cell(self.run_id, coordinate)
        try:
            return await self.delegate.run_cell(
                input_value=input_value, coordinate=coordinate, client=client
            )
        finally:
            await client.aclose()
