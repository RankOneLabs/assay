"""Bind Smithers routing identity and one durable submission key to each cell."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Any, Protocol

from jig.core.types import CompletionParams, Message, Role

from assay.adapters.smithers import SmithersClient, SmithersFactory
from assay.canonical import canonical_json
from assay.execution import Accounting, WorkerFailure, WorkerResult, WorkerSuccess
from assay.models import CellCoordinate
from assay.store import ObjectStore


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


class BridgeRuntimeLike(Protocol):
    def run_cell(self, request: Any, *, accepted_at: datetime) -> Any: ...


def _acceptance_anchor(
    diagnostics: Mapping[str, Any], poll_interval: float
) -> datetime | WorkerFailure:
    """Re-anchor Smithers' acceptance point on this host's clock.

    Smithers writes naive wall-clock timestamps from its own host, so its
    ``started_at`` is only an instant if that host runs on UTC — an
    assumption nothing on the wire states, and one that silently costs the
    cell a whole timezone offset when it is false. Only the *duration*
    ``completed_at - started_at`` is clock-independent, so the anchor is
    derived from it against this host's own clock instead.

    That duration ends when the job completed, but this host learns of it
    only at the next poll, so ``now - elapsed`` sits *later* than the real
    acceptance point and would hand the cell up to one extra poll interval
    of budget. The true completion lies between the last poll that saw the
    job running and this one, so the whole interval is charged: the error
    is bounded by ``poll_interval`` and always spends the cell's budget
    rather than extending it.
    """
    elapsed = diagnostics.get("time_from_acceptance_seconds")
    if not isinstance(elapsed, int | float) or isinstance(elapsed, bool) or elapsed < 0:
        return WorkerFailure("InvalidJobTiming", "Smithers job reported no time from acceptance")
    return datetime.now(UTC) - timedelta(seconds=float(elapsed) + max(poll_interval, 0.0))


def _bridge_accounting(usage: Any) -> Accounting:
    """Record what the bridge trial measured, never a zero for what it did not.

    Only the bridge leg is priced. Smithers reports no billing at all
    (``SmithersFactory.configuration`` pins ``billing: unavailable``), so a
    successful cell's cost is the guarded route's amount over an
    unmeasured remainder — ``mixed``, not ``measured``. An attempt that was
    dispatched but returned no usage is ``uncertain``: the cost is unknown,
    not nothing.
    """
    if usage is None:
        return Accounting(coverage="uncertain")
    counts: dict[str, float | None] = {}
    for name in ("prompt_tokens", "completion_tokens", "requests"):
        value = getattr(usage, name, None)
        if isinstance(value, int | float) and not isinstance(value, bool) and value >= 0:
            counts[name] = float(value)
    cost = getattr(usage, "cost_usd", None)
    if not isinstance(cost, int | float) or isinstance(cost, bool) or cost < 0:
        return Accounting(usage=counts or None, coverage="uncertain")
    return Accounting(
        usage=counts or None,
        amount=float(cost),
        currency="USD",
        coverage="mixed",
        basis="Pier bridge trial usage; Smithers dispatch leg is unpriced",
    )


@dataclass(frozen=True)
class SmithersBridgeCellDelegate:
    """Dispatch the cell's Smithers job, then run its bridge trial from acceptance.

    A new single-use BridgeRuntime is supplied for each cell. The request
    builder receives the Smithers completion when constructing that cell's
    TrialRequest; its stable configuration is part of the arm's authorized bytes.
    """

    store: ObjectStore
    runtime_factory: Callable[[], BridgeRuntimeLike]
    request_builder: Callable[[Any, CellCoordinate, str], Any]
    bridge_configuration: dict[str, Any]

    def configuration(self, arm_id: str) -> dict[str, Any]:
        return {
            "id": "workflow-edit-smithers-bridge",
            "version": "1",
            "delegate": "smithers-bridge-v1",
            "arm_id": arm_id,
            "bridge": self.bridge_configuration,
        }

    async def run_cell(
        self, *, input_value: Any, coordinate: CellCoordinate, client: SmithersClient
    ) -> WorkerResult:
        if not isinstance(input_value, dict) or not isinstance(input_value.get("prompt"), str):
            return WorkerFailure("InvalidInput", "workflow cell requires a prompt")
        completion = await client.complete_result(
            CompletionParams(messages=[Message(role=Role.USER, content=input_value["prompt"])])
        )
        if isinstance(completion, WorkerFailure):
            return completion
        diagnostics = client.diagnostics()
        accepted_at = _acceptance_anchor(diagnostics, client.configuration()["poll_interval"])
        if isinstance(accepted_at, WorkerFailure):
            return accepted_at
        try:
            request = self.request_builder(input_value, coordinate, completion.content)
            if request.cell_id != coordinate.id:
                return WorkerFailure("IdentityMismatch", "bridge request is for another cell")
            executor = ThreadPoolExecutor(max_workers=1)
            try:
                result = await asyncio.get_running_loop().run_in_executor(
                    executor,
                    partial(self.runtime_factory().run_cell, request, accepted_at=accepted_at),
                )
            finally:
                executor.shutdown(wait=False, cancel_futures=True)
        except Exception as error:
            # The bridge was entered, so any cost it incurred is unknown here
            # rather than known to be nothing.
            return WorkerFailure(
                type(error).__name__,
                str(error),
                trace={"smithers": diagnostics},
                accounting=Accounting(coverage="uncertain"),
            )
        accounting = _bridge_accounting(getattr(result, "usage", None))
        if result.cell_id != coordinate.id:
            return WorkerFailure(
                "IdentityMismatch", "bridge result is for another cell", accounting=accounting
            )
        if result.outcome.kind == "candidate":
            required = {
                "manifest.json", "candidate-index.json", "candidate.patch",
                "tree-digest.txt", "result.json", "configuration.json", "trajectory.json",
            }
            missing = sorted(required - result.artifacts.keys())
            if missing:
                return WorkerFailure(
                    "IncompleteEvidence", "bridge omitted success evidence: " + ", ".join(missing),
                    trace={"smithers": diagnostics}, accounting=accounting,
                )
        artifact_refs = {
            path: str(self.store.publish_bytes(data)) for path, data in result.artifacts.items()
        }
        trace = {"smithers": diagnostics, "artifact_refs": artifact_refs}
        if result.outcome.kind != "candidate":
            return WorkerFailure(
                type(result.outcome).__name__, result.outcome.detail or result.outcome.cause,
                trace=trace, accounting=accounting,
            )
        return WorkerSuccess(
            output={
                "cell_id": coordinate.id,
                "candidate_ref": artifact_refs["candidate-index.json"],
                "patch_ref": artifact_refs["candidate.patch"],
                "tree_digest_ref": artifact_refs["tree-digest.txt"],
                "result_ref": artifact_refs["result.json"],
                "configuration_ref": artifact_refs["configuration.json"],
                "raw_trajectory_ref": artifact_refs["trajectory.json"],
                "manifest_ref": artifact_refs["manifest.json"],
                "artifact_refs": artifact_refs,
            },
            trace=trace,
            accounting=accounting,
        )


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
