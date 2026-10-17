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
   byte-valid, and both the discriminated bridge outcome and mini's embedded
   ``exit_status`` indicate success;
3. on cancellation, tears the bridge handle down within a bounded window,
   verifies (rather than assumes) that cleanup actually completed, and still
   publishes whatever partial evidence exists, with uncertain accounting --
   never a bare/unbounded hang, never silently zero cost, and never treating
   an unverified cleanup the same as a confirmed one.

The bridge seals observed evidence before teardown. This adapter verifies
the exchange-bound manifest before settling a success.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import tempfile
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

from assay.canonical import canonical_json, digest_bytes
from assay.execution import Accounting, WorkerFailure, WorkerResult, WorkerSuccess
from assay.models import CellCoordinate
from assay.pier_packaging import (
    FORBIDDEN_SENTINELS,
    PackageLayout,
    build_package,
    gate_package,
)
from assay.pier_protocol import (
    MANIFEST_PATH,
    MAX_AGGREGATE_ARTIFACT_BYTES,
    MAX_ARTIFACT_BYTES,
    MAX_ARTIFACT_COUNT,
    REQUIRED_SUCCESS_KINDS,
    SUCCEEDED_EXIT_STATUS,
    ArtifactManifest,
    CandidateFailure,
    CandidateSubmission,
    InfrastructureFailure,
    ManifestRejected,
    ModelRoute,
    PierExchange,
    RuntimeBinding,
    bind_exchange,
    candidate_tree_digest,
    mini_exit_status_from_result_bytes,
    verify_artifact_bytes,
)
from assay.repository import DEFAULT_MAX_REPOSITORY_BYTES, DEFAULT_MAX_REPOSITORY_FILES
from assay.store import ObjectStore

CLEANUP_TIMEOUT = 5.0
def _thread_future[T](function: Callable[[], T]) -> asyncio.Future[T]:
    """Run a bridge call in a daemon thread without tying loop shutdown to it."""
    loop = asyncio.get_running_loop()
    future: asyncio.Future[T] = loop.create_future()

    def resolve(value: T) -> None:
        if not future.done():
            future.set_result(value)

    def reject(error: BaseException) -> None:
        if not future.done():
            future.set_exception(error)

    def run() -> None:
        try:
            value = function()
        except BaseException as error:
            with contextlib.suppress(RuntimeError):
                loop.call_soon_threadsafe(reject, error)
        else:
            with contextlib.suppress(RuntimeError):
                loop.call_soon_threadsafe(resolve, value)

    threading.Thread(target=run, daemon=True).start()
    return future


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
    """Mirrors ``assay_pier_bridge.protocol.TrialResult``'s discriminated
    outcome, usage, and evidence, plus this adapter's exchange binding.

    ``artifacts`` (path -> bytes) mirrors the real contract's own
    ``TrialResult.artifacts``: both of ``integrations/pier``'s handles read
    their submission mount back before ``teardown`` destroys it and carry
    the bytes out on the result.

    A successful bridge result includes an ``ArtifactManifest`` at
    ``MANIFEST_PATH`` binding observed bytes to this exchange.
    """

    exchange: PierExchange
    outcome: CandidateSubmission | CandidateFailure | InfrastructureFailure
    usage: Mapping[str, float | None] | None
    artifacts: Mapping[str, bytes]


class PierBridgeHandle(Protocol):
    """Mirrors ``assay_pier_bridge.protocol.TrialHandle``'s ``run``/``teardown``."""

    def run(self) -> BridgeTrialResult: ...

    def cancel(self) -> None: ...

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
        parts = PurePosixPath(path).parts
        if PurePosixPath(path).is_absolute() or any(part in {"", ".", ".."} for part in parts):
            raise ValueError(f"repository entry has an unsafe path: {path}")
        full = root / path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content, encoding="utf-8")
    return root


def _publish_available_artifacts(
    store: ObjectStore, artifacts: Mapping[str, bytes], *, priority: frozenset[str] = frozenset()
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

    A hostile or malfunctioning bridge can return an unbounded number of
    artifacts, or artifacts far larger than any manifest would ever declare,
    long before ``manifest.json`` itself is parsed and its own per-entry
    limits checked. Both the per-artifact and aggregate byte ceilings
    (``MAX_ARTIFACT_BYTES``/``MAX_AGGREGATE_ARTIFACT_BYTES``, the same
    ceilings the manifest's own entries are bound by) are therefore enforced
    here too, before anything is written to the store: an oversized artifact,
    or one that would push the running total over the aggregate ceiling, is
    never published.

    Which artifacts lose that race is not the bridge's choice. ``priority``
    -- the manifest plus the entries it declares -- is published first, and
    both groups are published in sorted path order, so a bridge cannot crowd
    the evidence a success is gated on out of the store by returning one
    large undeclared extra under an earlier key. A skipped artifact simply
    has no ref, and ``_settle`` refuses to settle a success whose required
    evidence went unpublished rather than reporting a null ref for it.

    ``manifest.json`` is bounded by the per-artifact ceiling but deliberately
    excluded from the aggregate one. ``MAX_AGGREGATE_ARTIFACT_BYTES`` bounds
    what a manifest may *declare*, and the manifest is never one of its own
    entries; charging it to that same budget would make a manifest declaring
    the maximum permitted aggregate impossible to publish in full, evicting
    a declared entry to make room for the document declaring it. The total
    a hostile bridge can put in the store is still bounded, just by
    ``MAX_AGGREGATE_ARTIFACT_BYTES + MAX_ARTIFACT_BYTES``.

    ``verify_artifact_bytes`` cannot stand in for that check. It is handed
    the raw bytes that crossed the boundary, where a skipped entry is present
    either way; publication is a separate step, and ``_settle``'s missing-ref
    check is the only thing that observes whether it happened.
    """
    refs: dict[str, str] = {}
    artifact_count = sum(path != MANIFEST_PATH for path in artifacts)
    if artifact_count > MAX_ARTIFACT_COUNT:
        return refs
    aggregate_bytes = 0
    ordered = sorted(artifacts, key=lambda path: (path not in priority, path))
    for path in ordered:
        data = artifacts[path]
        if len(data) > MAX_ARTIFACT_BYTES:
            continue
        if path != MANIFEST_PATH:
            if aggregate_bytes + len(data) > MAX_AGGREGATE_ARTIFACT_BYTES:
                continue
            aggregate_bytes += len(data)
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
    max_repository_files: int = DEFAULT_MAX_REPOSITORY_FILES,
    max_repository_bytes: int = DEFAULT_MAX_REPOSITORY_BYTES,
    forbidden_substrings: tuple[tuple[str, str], ...] = FORBIDDEN_SENTINELS,
    worker_id: str = "pier",
    package_layout: PackageLayout = "submission-worktree",
) -> dict[str, Any]:
    """The arm-level configuration a plan pins -- shared by ``PierAdapter`` and
    the investigation profiles that need it before any adapter is constructed.

    The default layout is left out so configurations pinned before it existed
    keep their exact bytes."""
    configuration: dict[str, Any] = {
        "id": worker_id,
        "version": binding.runtime_version,
        "runtime_id": binding.runtime_id,
        "image_digest": binding.image_digest,
        "configuration_ref": binding.configuration_ref,
        "model_route": dict(model_route),
        "trial_limits": dict(trial_limits),
        "max_repository_files": max_repository_files,
        "max_repository_bytes": max_repository_bytes,
        "forbidden_substrings": dict(forbidden_substrings),
    }
    if package_layout != "submission-worktree":
        configuration["package_layout"] = package_layout
    return configuration


@dataclass(frozen=True, slots=True)
class PierAdapter:
    """A worker bound to one qualified Pier runtime; construction never dials out."""

    store: ObjectStore
    bridge: PierBridgeClient
    binding: RuntimeBinding
    model_route: Mapping[str, str]
    trial_limits: Mapping[str, float | int]
    max_repository_files: int = DEFAULT_MAX_REPOSITORY_FILES
    max_repository_bytes: int = DEFAULT_MAX_REPOSITORY_BYTES
    forbidden_substrings: tuple[tuple[str, str], ...] = FORBIDDEN_SENTINELS
    worker_id: str = "pier"
    package_layout: PackageLayout = "submission-worktree"
    supports_cell_coordinates: bool = True

    def configuration(self, arm_id: str) -> dict[str, Any]:
        return worker_configuration(
            binding=self.binding,
            model_route=self.model_route,
            trial_limits=self.trial_limits,
            max_repository_files=self.max_repository_files,
            max_repository_bytes=self.max_repository_bytes,
            forbidden_substrings=self.forbidden_substrings,
            worker_id=self.worker_id,
            package_layout=self.package_layout,
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
                asyncio.shield(_thread_future(handle.teardown)), timeout=CLEANUP_TIMEOUT
            )
        except Exception:
            return None

    @staticmethod
    def _recover_partial_artifacts(
        handle: PierBridgeHandle, error: Exception | None = None
    ) -> Mapping[str, bytes]:
        """Best-effort recovery of whatever artifact bytes exist at cancellation time.

        Typed rejections carry their retained bytes directly. A handle may
        also expose ``partial_artifacts()`` for bytes observed before an
        infrastructure interruption; the typed rejection takes precedence
        when both report the same path.
        """
        retained = getattr(error, "artifacts", None)
        retained_bytes: dict[str, bytes] = (
            {
                key: value
                for key, value in retained.items()
                if isinstance(key, str) and isinstance(value, bytes)
            }
            if isinstance(retained, Mapping)
            else {}
        )
        if getattr(error, "origin", None) == "working_copy":
            retained_bytes = {
                f"rejected_worktree/{path}": data for path, data in retained_bytes.items()
            }
        getter = getattr(handle, "partial_artifacts", None)
        if not callable(getter):
            return retained_bytes
        try:
            artifacts = getter()
        except Exception:
            return retained_bytes
        observed_bytes = (
            {
                key: value
                for key, value in artifacts.items()
                if isinstance(key, str) and isinstance(value, bytes)
            }
            if isinstance(artifacts, Mapping)
            else {}
        )
        if getattr(error, "origin", None) == "working_copy":
            observed_bytes = {
                path: data
                for path, data in observed_bytes.items()
                if not path.startswith("rejected_worktree/")
            }
        return {**observed_bytes, **retained_bytes}

    async def run_cell(self, *, input_value: Any, coordinate: CellCoordinate) -> WorkerResult:
        if not isinstance(input_value, dict) or not isinstance(input_value.get("repository"), dict):
            return WorkerFailure("InvalidInput", "Pier realization must be a task/repository pair")
        task = _instruction_from_task_field(input_value.get("task"))
        if not task:
            return WorkerFailure("InvalidInput", "Pier realization requires a nonblank task")

        try:
            with contextlib.ExitStack() as stack:
                repository_root = _repository_dir(stack, input_value["repository"])
                package = build_package(
                    cell_id=coordinate.id,
                    task=task,
                    repository_root=repository_root,
                    max_repository_files=self.max_repository_files,
                    max_repository_bytes=self.max_repository_bytes,
                    layout=self.package_layout,
                )
            gate_package(
                package,
                expected_digest=package.manifest_digest,
                forbidden_substrings=dict(self.forbidden_substrings),
            )
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

        run_task = _thread_future(handle.run)
        try:
            bridge_result = await asyncio.shield(run_task)
        except asyncio.CancelledError:
            completed_result: BridgeTrialResult | None = None
            with contextlib.suppress(Exception, asyncio.CancelledError):
                await asyncio.wait_for(
                    asyncio.shield(_thread_future(handle.cancel)), timeout=CLEANUP_TIMEOUT
                )
            with contextlib.suppress(Exception, asyncio.CancelledError):
                completed_result = await asyncio.wait_for(
                    asyncio.shield(run_task), timeout=CLEANUP_TIMEOUT
                )
            effective = await self._bounded_teardown(handle)
            partial = self._recover_partial_artifacts(handle)
            if completed_result is not None:
                partial = {**partial, **completed_result.artifacts}
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
            partial = self._recover_partial_artifacts(handle, error)
            refs = _publish_available_artifacts(self.store, partial) if partial else {}
            effective = await self._bounded_teardown(handle)
            return WorkerFailure(
                type(error).__name__,
                str(error),
                trace=_trace(exchange, refs=refs, reason="bridge_exception")
                | {"cleanup_incomplete": _cleanup_incomplete(effective)},
                accounting=Accounting(coverage="uncertain"),
            )

        effective = await self._bounded_teardown(handle)
        return self._settle(
            exchange, bridge_result, cleanup_incomplete=_cleanup_incomplete(effective)
        )

    def _settle(
        self, exchange: PierExchange, bridge_result: BridgeTrialResult, *, cleanup_incomplete: bool
    ) -> WorkerResult:
        refs = _publish_available_artifacts(
            self.store,
            bridge_result.artifacts,
            priority=_declared_paths(bridge_result.artifacts.get(MANIFEST_PATH)),
        )
        dispatched_accounting = _accounting_from_usage(
            bridge_result.usage,
            paid_route=ModelRoute.model_validate(self.model_route).paid_route_reachable,
        )

        if bridge_result.exchange != exchange:
            return WorkerFailure(
                "IdentityMismatch",
                "bridge response is bound to a different cell/runtime/package than authorized",
                trace=_trace(exchange, refs=refs, reason="exchange_mismatch"),
                accounting=dispatched_accounting,
            )

        if isinstance(bridge_result.outcome, (CandidateFailure, InfrastructureFailure)):
            outcome = bridge_result.outcome
            trace = _trace(exchange, refs=refs, reason="bridge_reported_failure")
            trace["bridge_outcome"] = outcome.model_dump(mode="json")
            trace["cleanup_incomplete"] = cleanup_incomplete
            return WorkerFailure(
                type(outcome).__name__,
                outcome.detail or outcome.cause,
                trace=trace,
                accounting=dispatched_accounting,
            )

        manifest_bytes = bridge_result.artifacts.get(MANIFEST_PATH)
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
                "ManifestRejected",
                str(error),
                trace=_trace(exchange, refs=refs, reason="manifest_rejected"),
                accounting=dispatched_accounting,
            )

        result_bytes = _bytes_for(manifest, bridge_result.artifacts, "result")
        mini_exit_status = mini_exit_status_from_result_bytes(result_bytes)
        if mini_exit_status != SUCCEEDED_EXIT_STATUS:
            return WorkerFailure(
                "BridgeReportedFailure",
                f"Pier outcome={bridge_result.outcome.kind!r} "
                f"mini exit_status={mini_exit_status!r}",
                trace=_trace(exchange, refs=refs, reason="bridge_reported_failure"),
                accounting=dispatched_accounting,
            )

        if not manifest.has_required_success_evidence():
            return WorkerFailure(
                "IncompleteEvidence",
                "manifest is missing required raw trajectory/candidate/patch/tree digest/"
                "result/configuration evidence",
                trace=_trace(exchange, refs=refs, reason="incomplete_evidence"),
                accounting=dispatched_accounting,
            )

        # Bind both the patch and the full candidate tree to the observed result.
        patch_bytes = _bytes_for(manifest, bridge_result.artifacts, "patch")
        tree_bytes = _bytes_for(manifest, bridge_result.artifacts, "tree_digest")
        assert isinstance(bridge_result.outcome, CandidateSubmission)
        try:
            observed_tree = candidate_tree_digest(
                manifest, artifact_bytes=dict(bridge_result.artifacts)
            )
        except ManifestRejected as error:
            return WorkerFailure(
                "ManifestRejected",
                str(error),
                trace=_trace(exchange, refs=refs, reason="manifest_rejected"),
                accounting=dispatched_accounting,
            )
        if (
            patch_bytes is None
            or digest_bytes(patch_bytes) != bridge_result.outcome.patch_ref
            or tree_bytes is None
            or tree_bytes != observed_tree.encode("ascii")
            or observed_tree != bridge_result.outcome.tree_digest
        ):
            return WorkerFailure(
                "SubmissionMismatch",
                "bridge patch or tree digest does not match the declared candidate",
                trace=_trace(exchange, refs=refs, reason="submission_mismatch"),
                accounting=dispatched_accounting,
            )

        def _ref_for(kind: str) -> str | None:
            path = _path_for(manifest, kind)
            return refs.get(path) if path is not None else None

        # Declaring evidence and publishing it are separate steps, and only
        # this check observes the difference. ``_publish_available_artifacts``
        # skips anything that would breach the byte ceilings, so a manifest
        # can verify perfectly against the bytes that crossed the boundary
        # while the bytes backing a required kind never reached the store. A
        # success whose ``result_ref``/``candidate_ref``/... is null is not a
        # success: downstream evaluation would read a missing reference as an
        # absent result rather than as evidence that was dropped in transit.
        # ``manifest.json`` is the binding document and is never one of the
        # manifest's own entries, so its ref is resolved by reserved path.
        manifest_ref = refs.get(MANIFEST_PATH)
        unpublished = sorted(kind for kind in REQUIRED_SUCCESS_KINDS if _ref_for(kind) is None)
        unpublished.extend(entry.path for entry in manifest.entries if refs.get(entry.path) is None)
        if manifest_ref is None:
            unpublished = [*unpublished, "manifest"]
        if unpublished:
            return WorkerFailure(
                "UnpublishedEvidence",
                "required evidence was declared but never published: " + ", ".join(unpublished),
                trace=_trace(exchange, refs=refs, reason="unpublished_evidence"),
                accounting=dispatched_accounting,
            )

        transcript_ref = _ref_for("transcript")
        output = {
            "cell_id": exchange.coordinate.id,
            "candidate_ref": _ref_for("candidate"),
            "patch_ref": _ref_for("patch"),
            "tree_digest_ref": _ref_for("tree_digest"),
            "result_ref": _ref_for("result"),
            "raw_trajectory_ref": _ref_for("raw_trajectory"),
            "configuration_ref": _ref_for("configuration"),
            "manifest_ref": manifest_ref,
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


def _declared_paths(manifest_bytes: bytes | None) -> frozenset[str]:
    """The paths a returned manifest declares, for publication priority only.

    This runs before the manifest is validated or bound to the exchange --
    its answer decides only *ordering* under the byte ceilings, never
    whether anything is trusted. A manifest that is absent, unparseable, or
    outright hostile therefore costs nothing here: priority falls back to
    sorted path order, and every real check still happens below. The
    manifest's own path is always included, since it is the one artifact
    that is never a declared entry and is still required to be reachable.
    """
    paths = {MANIFEST_PATH}
    if manifest_bytes is not None:
        with contextlib.suppress(Exception):
            declared = ArtifactManifest.model_validate_json(manifest_bytes).entries
            paths.update(entry.path for entry in declared)
    return frozenset(paths)


def _path_for(manifest: ArtifactManifest, kind: str) -> str | None:
    entry = manifest.entry(kind)  # type: ignore[arg-type]
    return entry.path if entry is not None else None


def _bytes_for(
    manifest: ArtifactManifest, artifacts: Mapping[str, bytes], kind: str
) -> bytes | None:
    path = _path_for(manifest, kind)
    return artifacts.get(path) if path is not None else None


def _accounting_from_usage(
    usage: Mapping[str, float | None] | None, *, paid_route: bool = False
) -> Accounting:
    """Convert a bridge-reported usage mapping into ``Accounting``.

    ``BridgeTrialResult`` is a local dataclass with no runtime validation of
    its ``usage`` field (unlike the real bridge's ``TrialUsage`` model), so a
    malformed ``cost_usd`` -- present but not numeric -- must not raise out
    of this local-adapter boundary. It is reported as uncertain coverage
    rather than letting a conversion error escape ``_settle``/``run_cell``.
    """
    if usage is None:
        return Accounting(coverage="uncertain")
    cost = usage.get("cost_usd")
    if cost is None:
        return Accounting(
            usage={key: value for key, value in usage.items() if key != "cost_usd"} or None,
            coverage="uncertain" if paid_route or "cost_usd" not in usage else "unavailable",
        )
    try:
        amount = float(cost)
    except (TypeError, ValueError):
        # ``Accounting`` itself requires every usage quantity to be a finite
        # nonnegative number or null; a malformed cost_usd is dropped from
        # the recorded usage rather than passed through and rejected there.
        remaining: dict[str, float | None] = {
            key: value for key, value in usage.items() if key != "cost_usd"
        }
        return Accounting(usage=remaining or None, coverage="uncertain")
    return Accounting(
        usage={key: value for key, value in usage.items() if key != "cost_usd"} or None,
        amount=amount,
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
