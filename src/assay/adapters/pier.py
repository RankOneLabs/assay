"""The core-side Pier adapter: one authorized cell, one bridge exchange.

``PierAdapter`` implements ``execution.CoordinateAwareWorker``. It never talks
to Docker or the Pier bridge process directly -- it is handed a
``PierBridgeClient`` (a narrow local protocol mirroring
``integrations/pier``'s ``PierTrialClient`` without importing it, since that
project is deliberately isolated from this one) and does three things around
that boundary:

1. binds the request to the authorized ``CellCoordinate`` plus the exact
   runtime/image/configuration/package identity (``pier_protocol``), and
   rejects any mismatch as a terminal failure;
2. accepts a success only when the raw trajectory, verbatim candidate,
   result, resolved configuration, and manifest evidence are all present and
   byte-valid, and neither Pier's ``exception_info`` nor mini's
   ``exit_status`` indicates failure;
3. on cancellation, tears the bridge handle down within a bounded window and
   still publishes whatever partial evidence exists, with uncertain
   accounting -- never a bare/unbounded hang, never silently zero cost.
"""

from __future__ import annotations

import asyncio
import contextlib
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

from assay.canonical import canonical_json
from assay.execution import Accounting, WorkerFailure, WorkerResult, WorkerSuccess
from assay.models import CellCoordinate
from assay.pier_packaging import build_package, gate_package
from assay.pier_protocol import (
    ArtifactManifest,
    ManifestRejected,
    PierExchange,
    RuntimeBinding,
    bind_exchange,
    bridge_reports_failure,
    verify_artifact_bytes,
)
from assay.store import ObjectStore

CLEANUP_TIMEOUT = 5.0


@dataclass(frozen=True, slots=True)
class BridgeTrialResult:
    """The bridge's response to one ``PierExchange``; ``artifacts`` is path -> bytes."""

    exchange: PierExchange
    status: Literal["succeeded", "failed", "timeout", "cancelled"]
    exception_info: str | None
    exit_status: str | None
    usage: dict[str, float] | None
    artifacts: Mapping[str, bytes]


class PierBridgeHandle(Protocol):
    def run(self) -> BridgeTrialResult: ...

    def teardown(self) -> None: ...


class PierBridgeClient(Protocol):
    """Creates exactly one handle per authorized exchange (mirrors ``PierTrialClient``)."""

    def create(self, *, exchange: PierExchange, package: Mapping[str, str]) -> PierBridgeHandle: ...


class PierAdapterError(Exception):
    pass


def _repository_dir(stack: contextlib.ExitStack, repository: Mapping[str, str]) -> Path:
    root = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="assay-pier-")))
    for path, content in repository.items():
        full = root / path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content, encoding="utf-8")
    return root


def _publish_available_artifacts(
    store: ObjectStore, artifacts: Mapping[str, bytes]
) -> dict[str, str]:
    """Publish every artifact byte blob independently, regardless of manifest validity.

    A blob that fails manifest binding is still durable, content-addressed
    evidence -- this is what keeps a partial, independently-valid artifact
    reachable via ``assay_object_refs`` even when the overall run fails.
    """
    return {path: str(store.publish_bytes(data)) for path, data in artifacts.items()}


def _trace(
    exchange: PierExchange, *, refs: dict[str, str], reason: str | None = None
) -> dict[str, Any]:
    trace: dict[str, Any] = {
        "coordinate": exchange.coordinate.model_dump(mode="json"),
        "binding": exchange.binding.model_dump(mode="json"),
        "artifact_refs": refs,
        "assay_object_refs": sorted(set(refs.values())),
    }
    if reason is not None:
        trace["rejection_reason"] = reason
    return trace


def worker_configuration(
    *,
    binding: RuntimeBinding,
    model_route: Mapping[str, str],
    trial_limits: Mapping[str, float | int],
    worker_id: str = "pier",
) -> dict[str, Any]:
    """The arm-level configuration a plan pins -- shared by ``PierAdapter`` and
    the investigation profiles that need it before any adapter is constructed."""
    return {
        "id": worker_id,
        "version": binding.runtime_version,
        "runtime_id": binding.runtime_id,
        "image_digest": binding.image_digest,
        "configuration_ref": binding.configuration_ref,
        "model_route": dict(model_route),
        "trial_limits": dict(trial_limits),
    }


@dataclass(frozen=True, slots=True)
class PierAdapter:
    """A worker bound to one qualified Pier runtime; construction never dials out."""

    store: ObjectStore
    bridge: PierBridgeClient
    binding: RuntimeBinding
    model_route: Mapping[str, str]
    trial_limits: Mapping[str, float | int]
    worker_id: str = "pier"
    supports_cell_coordinates: bool = True

    def configuration(self, arm_id: str) -> dict[str, Any]:
        return worker_configuration(
            binding=self.binding,
            model_route=self.model_route,
            trial_limits=self.trial_limits,
            worker_id=self.worker_id,
        )

    async def _bounded_teardown(self, handle: PierBridgeHandle) -> None:
        with contextlib.suppress(Exception):
            await asyncio.wait_for(asyncio.to_thread(handle.teardown), timeout=CLEANUP_TIMEOUT)

    async def run_cell(self, *, input_value: Any, coordinate: CellCoordinate) -> WorkerResult:
        if not isinstance(input_value, dict) or not isinstance(
            input_value.get("repository"), dict
        ):
            return WorkerFailure("InvalidInput", "Pier realization must be a task/repository pair")
        task = input_value.get("task")
        if not isinstance(task, str) or not task.strip():
            return WorkerFailure("InvalidInput", "Pier realization requires a nonblank task")

        try:
            with contextlib.ExitStack() as stack:
                repository_root = _repository_dir(stack, input_value["repository"])
                package = build_package(
                    cell_id=coordinate.id, task=task, repository_root=repository_root
                )
            gate_package(package, expected_digest=package.manifest_digest)
        except Exception as error:
            return WorkerFailure(type(error).__name__, str(error), accounting=Accounting())

        binding = RuntimeBinding(
            runtime_version=self.binding.runtime_version,
            image_digest=self.binding.image_digest,
            configuration_ref=self.binding.configuration_ref,
            package_digest=package.manifest_digest,
        )
        exchange = bind_exchange(coordinate=coordinate, binding=binding)

        try:
            handle = self.bridge.create(exchange=exchange, package=package.as_mapping())
        except Exception as error:
            return WorkerFailure(type(error).__name__, str(error), accounting=Accounting())

        try:
            bridge_result = await asyncio.to_thread(handle.run)
        except asyncio.CancelledError:
            await self._bounded_teardown(handle)
            raise
        except Exception as error:
            await self._bounded_teardown(handle)
            return WorkerFailure(
                type(error).__name__, str(error), accounting=Accounting(coverage="uncertain")
            )

        await self._bounded_teardown(handle)
        return self._settle(exchange, bridge_result)

    def _settle(self, exchange: PierExchange, bridge_result: BridgeTrialResult) -> WorkerResult:
        refs = _publish_available_artifacts(self.store, bridge_result.artifacts)
        dispatched_accounting = _accounting_from_usage(bridge_result.usage)

        if bridge_result.exchange != exchange:
            return WorkerFailure(
                "IdentityMismatch",
                "bridge response is bound to a different cell/runtime/package than authorized",
                trace=_trace(exchange, refs=refs, reason="exchange_mismatch"),
                accounting=dispatched_accounting,
            )

        manifest_bytes = bridge_result.artifacts.get("manifest.json")
        if manifest_bytes is None:
            return WorkerFailure(
                "MissingManifest",
                "bridge response is missing the artifact manifest",
                trace=_trace(exchange, refs=refs, reason="missing_manifest"),
                accounting=dispatched_accounting,
            )
        try:
            manifest = ArtifactManifest.model_validate_json(manifest_bytes)
            if manifest.exchange != exchange:
                raise ManifestRejected("manifest is bound to a different exchange")
            verify_artifact_bytes(manifest, artifact_bytes=dict(bridge_result.artifacts))
        except Exception as error:
            return WorkerFailure(
                type(error).__name__,
                str(error),
                trace=_trace(exchange, refs=refs, reason="manifest_rejected"),
                accounting=dispatched_accounting,
            )

        failed = bridge_reports_failure(
            exception_info=bridge_result.exception_info, exit_status=bridge_result.exit_status
        )
        if failed:
            return WorkerFailure(
                "BridgeReportedFailure",
                bridge_result.exception_info
                or f"mini-swe-agent exit_status={bridge_result.exit_status!r}",
                trace=_trace(exchange, refs=refs, reason="bridge_reported_failure"),
                accounting=dispatched_accounting,
            )

        if not manifest.has_required_success_evidence():
            return WorkerFailure(
                "IncompleteEvidence",
                "manifest is missing required raw trajectory/candidate/result/"
                "configuration/manifest evidence",
                trace=_trace(exchange, refs=refs, reason="incomplete_evidence"),
                accounting=dispatched_accounting,
            )

        def _ref_for(kind: str) -> str | None:
            path = _path_for(manifest, kind)
            return refs.get(path) if path is not None else None

        output = {
            "cell_id": exchange.coordinate.id,
            "candidate_ref": _ref_for("candidate"),
            "result_ref": _ref_for("result"),
            "raw_trajectory_ref": _ref_for("raw_trajectory"),
            "configuration_ref": _ref_for("configuration"),
            "manifest_ref": _ref_for("manifest"),
            "transcript_ref": _ref_for("transcript"),
        }
        canonical_json(output)  # fail fast rather than surface a bad output at publish time
        return WorkerSuccess(
            output=output,
            trace=_trace(exchange, refs=refs),
            accounting=dispatched_accounting,
        )


def _path_for(manifest: ArtifactManifest, kind: str) -> str | None:
    entry = manifest.entry(kind)  # type: ignore[arg-type]
    return entry.path if entry is not None else None


def _accounting_from_usage(usage: dict[str, float] | None) -> Accounting:
    if usage is None:
        return Accounting(coverage="uncertain")
    cost = usage.get("cost_usd")
    if cost is None:
        return Accounting(usage=dict(usage), coverage="uncertain")
    return Accounting(
        usage={key: value for key, value in usage.items() if key != "cost_usd"} or None,
        amount=float(cost),
        currency="USD",
        coverage="measured",
        basis="Pier bridge trial usage (guarded OpenRouter route, inline cost)",
    )


__all__ = [
    "BridgeTrialResult",
    "PierAdapter",
    "PierAdapterError",
    "PierBridgeClient",
    "PierBridgeHandle",
    "worker_configuration",
]
