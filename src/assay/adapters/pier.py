"""The core-side Pier adapter: one authorized cell, one bridge exchange.

``PierAdapter`` implements ``execution.CoordinateAwareWorker``. It never talks
to Docker or the Pier bridge process directly -- it is handed a
``PierBridgeClient`` (a narrow local protocol mirroring
``integrations/pier``'s ``PierTrialClient``/``TrialHandle`` without importing
them, since that project is deliberately isolated from this one) and does
three things around that boundary:

1. binds the request to the authorized ``CellCoordinate`` plus the exact
   runtime/image/configuration/package identity (``pier_protocol``), and
   rejects any mismatch as a terminal failure;
2. accepts a success only when the raw trajectory, verbatim candidate,
   result, resolved configuration, and manifest evidence are all present and
   byte-valid, and neither Pier's own trial ``status``/``error_type`` nor
   mini's embedded ``exit_status`` indicates failure;
3. on cancellation, tears the bridge handle down within a bounded window,
   verifies (rather than assumes) that cleanup actually completed, and still
   publishes whatever partial evidence exists, with uncertain accounting --
   never a bare/unbounded hang, never silently zero cost, and never treating
   an unverified cleanup the same as a confirmed one.

Known gap (see the module's ``BridgeTrialResult`` docstring): the real bridge
integration as it exists today (``assay_pier_bridge.protocol.TrialResult``,
``host_driver.GuardedCompletionTrialHandle``) has no mechanism to return raw
trajectory/candidate/configuration/manifest bytes at all -- only a bare
``submission_ref`` digest. This adapter's ``artifacts`` field on
``BridgeTrialResult`` is therefore a documented, flagged extension beyond the
real wire contract, not something grounded in a real API a bridge client
implements today.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

from assay.canonical import canonical_json, digest_bytes
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
    mini_exit_status_from_result_bytes,
    verify_artifact_bytes,
)
from assay.store import ObjectStore

CLEANUP_TIMEOUT = 5.0

BridgeTrialStatus = Literal["succeeded", "failed", "timeout", "cancelled"]


@dataclass(frozen=True, slots=True)
class BridgeEffectiveEnforcement:
    """Local mirror of the cleanup-relevant fields of
    ``assay_pier_bridge.protocol.EffectiveEnforcement``.

    Only the fields this adapter actually inspects (whether teardown
    genuinely completed) are mirrored; the real type additionally reports
    mount/uid/resource-limit observations this adapter has no use for.
    """

    containers_remaining: int
    child_processes_remaining: int
    teardown_completed: bool


@dataclass(frozen=True, slots=True)
class BridgeTrialResult:
    """Mirrors ``assay_pier_bridge.protocol.TrialResult``'s real fields
    (``status``/``submission_ref``/``usage``/``error_type``/``error_message``),
    plus this adapter's own exchange binding.

    ``artifacts`` (path -> bytes) is NOT part of the real wire contract: as
    of this writing, ``integrations/pier``'s ``TrialHandle``/``TrialResult``
    expose no way at all to retrieve raw trajectory/candidate/configuration/
    manifest bytes -- only a bare ``submission_ref`` digest (see
    ``assay_pier_bridge.protocol.TrialResult`` and
    ``host_driver.GuardedCompletionTrialHandle``, which writes the submitted
    source only to a host-local temp file, never returned to the caller).
    This is a documented, flagged extension this adapter requires; a real
    ``PierBridgeClient`` implementation will need to grow a way to surface
    these bytes before this adapter can run against it for real -- recorded
    as a known gap, not invented as if it already existed.
    """

    exchange: PierExchange
    status: BridgeTrialStatus
    submission_ref: str | None
    usage: Mapping[str, float] | None
    error_type: str | None
    error_message: str | None
    artifacts: Mapping[str, bytes]


class PierBridgeHandle(Protocol):
    """Mirrors ``assay_pier_bridge.protocol.TrialHandle``'s ``run``/``teardown``."""

    def run(self) -> BridgeTrialResult: ...

    def teardown(self) -> BridgeEffectiveEnforcement: ...


class PierBridgeClient(Protocol):
    """Creates exactly one handle per authorized exchange (mirrors ``PierTrialClient``)."""

    def create(self, *, exchange: PierExchange, package: Mapping[str, str]) -> PierBridgeHandle: ...


class PierAdapterError(Exception):
    pass


def _instruction_from_task_field(task_field: Any) -> str | None:
    """The realization's ``task`` field is either a plain instruction string
    (the lower-level adapter contract) or a full task dict carrying its own
    ``instruction`` field (what investigation profiles that also need the
    task's other fields -- for structural/functional evaluation -- publish
    instead). Either shape is accepted; anything else, or a blank result, is
    rejected by the caller.
    """
    if isinstance(task_field, str):
        instruction = task_field
    elif isinstance(task_field, Mapping) and isinstance(task_field.get("instruction"), str):
        instruction = task_field["instruction"]
    else:
        return None
    return instruction if instruction.strip() else None


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

    Each blob is wrapped in a canonical JSON envelope rather than published as
    raw bytes: a real bridge's trajectory/result/configuration JSON is
    produced by an external tool with its own formatting, almost certainly
    not Assay's canonical form, and ``references.walk_closure`` requires
    every object it walks to be canonical JSON if it parses as JSON at all
    (rejecting a parseable-but-noncanonical value, rather than treating it as
    an opaque leaf, is deliberate -- see ``test_reference_canonicality.py``).
    The envelope preserves the exact original bytes losslessly via base64 and
    records their own checksum for audit, without ever publishing content
    that could itself be mistaken for a noncanonical governed document.
    """
    refs: dict[str, str] = {}
    for path, data in artifacts.items():
        envelope = {
            "schema_version": "assay-pier-raw-artifact/0.1.0",
            "path": path,
            "byte_length": len(data),
            "checksum": digest_bytes(data),
            "content_base64": base64.b64encode(data).decode("ascii"),
        }
        refs[path] = str(store.publish_json(envelope))
    return refs


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


def _cleanup_incomplete(effective: BridgeEffectiveEnforcement | None) -> bool:
    """``True`` unless teardown's own report confirms a clean, complete cleanup."""
    if effective is None:
        return True
    return (
        not effective.teardown_completed
        or effective.containers_remaining != 0
        or effective.child_processes_remaining != 0
    )


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

    async def _bounded_teardown(
        self, handle: PierBridgeHandle
    ) -> BridgeEffectiveEnforcement | None:
        """Tear the handle down within ``CLEANUP_TIMEOUT``; ``None`` means unverified.

        A timeout or an exception from ``teardown`` itself is not silently
        treated as success -- the caller must see ``None`` and account for it
        as an unverified (never "clean") cleanup.
        """
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(handle.teardown), timeout=CLEANUP_TIMEOUT
            )
        except Exception:
            return None

    @staticmethod
    def _recover_partial_artifacts(handle: PierBridgeHandle) -> Mapping[str, bytes]:
        """Best-effort recovery of whatever artifact bytes exist at cancellation time.

        Not part of the real ``assay_pier_bridge.protocol.TrialHandle``
        contract -- that protocol exposes no way to read partial evidence
        before ``run()`` returns or ``teardown()`` is called. A handle *may*
        optionally implement ``partial_artifacts()`` (checked via ``getattr``,
        the same explicit-capability style ``execution.CoordinateAwareWorker``
        uses); a handle that does not is not treated as an error, it simply
        has no partial evidence to recover.
        """
        getter = getattr(handle, "partial_artifacts", None)
        if not callable(getter):
            return {}
        try:
            artifacts = getter()
        except Exception:
            return {}
        return artifacts if isinstance(artifacts, Mapping) else {}

    async def run_cell(self, *, input_value: Any, coordinate: CellCoordinate) -> WorkerResult:
        if not isinstance(input_value, dict) or not isinstance(
            input_value.get("repository"), dict
        ):
            return WorkerFailure("InvalidInput", "Pier realization must be a task/repository pair")
        task = _instruction_from_task_field(input_value.get("task"))
        if not task:
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
            partial = self._recover_partial_artifacts(handle)
            effective = await self._bounded_teardown(handle)
            # No WorkerResult survives a cancellation (the task itself is
            # cancelled), but whatever partial evidence existed, and whether
            # cleanup actually completed, must still be durable and
            # forensically reachable -- never silently dropped.
            refs = _publish_available_artifacts(self.store, partial) if partial else {}
            self.store.publish_json(
                {
                    "schema_version": "assay-pier-cancellation-trace/0.1.0",
                    "coordinate": exchange.coordinate.model_dump(mode="json"),
                    "cleanup_incomplete": _cleanup_incomplete(effective),
                    "partial_artifact_refs": refs,
                }
            )
            raise
        except Exception as error:
            effective = await self._bounded_teardown(handle)
            return WorkerFailure(
                type(error).__name__,
                str(error),
                trace={"cleanup_incomplete": _cleanup_incomplete(effective)},
                accounting=Accounting(coverage="uncertain"),
            )

        effective = await self._bounded_teardown(handle)
        return self._settle(
            exchange, bridge_result, cleanup_incomplete=_cleanup_incomplete(effective)
        )

    def _settle(
        self, exchange: PierExchange, bridge_result: BridgeTrialResult, *, cleanup_incomplete: bool
    ) -> WorkerResult:
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

        result_bytes = _bytes_for(manifest, bridge_result.artifacts, "result")
        mini_exit_status = mini_exit_status_from_result_bytes(result_bytes)
        failed = bridge_reports_failure(
            status=bridge_result.status,
            submission_ref=bridge_result.submission_ref,
            error_type=bridge_result.error_type,
            mini_exit_status=mini_exit_status,
        )
        if failed:
            return WorkerFailure(
                "BridgeReportedFailure",
                bridge_result.error_message
                or f"Pier status={bridge_result.status!r} mini exit_status={mini_exit_status!r}",
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

        transcript_ref = _ref_for("transcript")
        output = {
            "cell_id": exchange.coordinate.id,
            "candidate_ref": _ref_for("candidate"),
            "result_ref": _ref_for("result"),
            "raw_trajectory_ref": _ref_for("raw_trajectory"),
            "configuration_ref": _ref_for("configuration"),
            "manifest_ref": _ref_for("manifest"),
            "transcript_ref": transcript_ref,
            "transcript_status": "available" if transcript_ref is not None else "unavailable",
        }
        canonical_json(output)  # fail fast rather than surface a bad output at publish time
        trace = _trace(exchange, refs=refs)
        trace["cleanup_incomplete"] = cleanup_incomplete
        return WorkerSuccess(
            output=output,
            trace=trace,
            accounting=dispatched_accounting,
        )


def _path_for(manifest: ArtifactManifest, kind: str) -> str | None:
    entry = manifest.entry(kind)  # type: ignore[arg-type]
    return entry.path if entry is not None else None


def _bytes_for(
    manifest: ArtifactManifest, artifacts: Mapping[str, bytes], kind: str
) -> bytes | None:
    path = _path_for(manifest, kind)
    return artifacts.get(path) if path is not None else None


def _accounting_from_usage(usage: Mapping[str, float] | None) -> Accounting:
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
    "BridgeEffectiveEnforcement",
    "BridgeTrialResult",
    "PierAdapter",
    "PierAdapterError",
    "PierBridgeClient",
    "PierBridgeHandle",
    "worker_configuration",
]
