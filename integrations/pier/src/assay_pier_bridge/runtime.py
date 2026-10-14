"""Trial lifecycle: exactly one ``Trial.create`` per cell, teardown always runs.

Never installs a package, resolves a dependency, or mutates a pricing map:
this module only orchestrates an already-created, already-locked
``PierTrialClient``. See ``tests/test_trial_lifecycle.py`` for the spy that
proves it.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from typing import cast

from assay_pier_bridge.identity import canonical_json, digest_bytes
from assay_pier_bridge.paths import ArtifactCollectionRejected, safe_relative_path
from assay_pier_bridge.paths import tree_digest as digest_tree
from assay_pier_bridge.protocol import (
    MANIFEST_PATH,
    MAX_AGGREGATE_ARTIFACT_BYTES,
    MAX_ARTIFACT_BYTES,
    MAX_ARTIFACT_COUNT,
    ArtifactEntry,
    ArtifactKind,
    ArtifactManifest,
    CandidateCause,
    CandidateFailure,
    EffectiveEnforcement,
    InfrastructureCause,
    InfrastructureFailure,
    PierExchange,
    PierTrialClient,
    TrialHandle,
    TrialRequest,
    TrialResult,
)


def seal_observed_artifacts(
    exchange: PierExchange,
    artifacts: Mapping[str, bytes],
    candidate_files: Mapping[str, bytes],
    tree_digest: str,
) -> dict[str, bytes]:
    """Bind the host's collected bytes and final file tree before teardown."""
    if MANIFEST_PATH in artifacts:
        raise ArtifactCollectionRejected(
            "tampering",
            "candidate attempted to supply the artifact manifest",
            artifacts=dict(artifacts),
            rejected_path=MANIFEST_PATH,
        )
    if any(
        path in {"candidate-index.json", "tree-digest.txt"} or path.startswith("candidate_files/")
        for path in artifacts
    ):
        raise ArtifactCollectionRejected(
            "tampering",
            "candidate attempted to replace host candidate evidence",
            artifacts=dict(artifacts),
        )
    required = {"trajectory.json", "candidate.patch", "result.json", "configuration.json"}
    if not artifacts.keys() >= required:
        raise ValueError("successful trial lacks required evidence")
    sealed = dict(artifacts)
    names = sorted(candidate_files, key=lambda path: path.encode("utf-8"))
    if digest_tree(candidate_files) != tree_digest:
        raise ValueError("the observed candidate files do not match the final tree digest")
    sealed["candidate-index.json"] = canonical_json(names)
    sealed["tree-digest.txt"] = tree_digest.encode("ascii")
    for path in names:
        safe_relative_path(path)
        sealed[f"candidate_files/{path}"] = candidate_files[path]
    kinds: dict[str, ArtifactKind] = {
        "trajectory.json": "raw_trajectory",
        "candidate.patch": "patch",
        "result.json": "result",
        "configuration.json": "configuration",
        "candidate-index.json": "candidate",
        "tree-digest.txt": "tree_digest",
    }
    if "transcript.json" in sealed:
        kinds["transcript.json"] = "transcript"
    for path in names:
        kinds[f"candidate_files/{path}"] = "candidate"
    if (
        len(sealed) > MAX_ARTIFACT_COUNT
        or sum(map(len, sealed.values())) > MAX_AGGREGATE_ARTIFACT_BYTES
    ):
        raise ArtifactCollectionRejected(
            "aggregate_artifact_limit",
            "observed artifacts exceed the manifest budget",
            artifacts=dict(artifacts),
        )
    entries = []
    for path, kind in sorted(kinds.items()):
        data = sealed[path]
        if len(data) > MAX_ARTIFACT_BYTES:
            raise ArtifactCollectionRejected(
                "oversized_artifact",
                f"artifact exceeds the byte limit: {path}",
                artifacts=dict(artifacts),
                rejected_path=path,
            )
        try:
            decoded = data.decode("utf-8")
        except UnicodeDecodeError:
            decoded = None
        if kind in {"raw_trajectory", "result", "configuration"}:
            if decoded is None:
                raise ArtifactCollectionRejected(
                    "binary_payload",
                    f"structured artifact is not UTF-8: {path}",
                    artifacts=dict(artifacts),
                    rejected_path=path,
                )
            try:
                json.loads(decoded)
            except ValueError as error:
                raise ArtifactCollectionRejected(
                    "tampering",
                    f"structured artifact is not JSON: {path}",
                    artifacts=dict(artifacts),
                    rejected_path=path,
                ) from error
        entries.append(
            ArtifactEntry(
                path=path,
                kind=kind,
                size_bytes=len(data),
                checksum=digest_bytes(data),
                utf8=decoded is not None,
            )
        )
    manifest = ArtifactManifest(
        exchange=exchange,
        entries=tuple(entries),
        aggregate_bytes=sum(entry.size_bytes for entry in entries),
    )
    sealed[MANIFEST_PATH] = canonical_json(manifest.model_dump(mode="json"))
    return sealed


class TrialAlreadyRequestedError(Exception):
    """A ``BridgeRuntime`` is single-use: one authorized cell, one trial."""


class TrialTimeoutError(Exception):
    """Raised by a ``TrialHandle.run()`` implementation on a deadline breach."""


class TrialCancelledError(Exception):
    """Raised by a ``TrialHandle.run()`` implementation on operator cancellation."""


class CandidateTrialError(RuntimeError):
    """A candidate-caused rejection with a stable, typed reason."""

    def __init__(
        self, cause: CandidateCause, message: str, *, artifacts: Mapping[str, bytes] | None = None
    ) -> None:
        super().__init__(message)
        self.cause = cause
        self.artifacts = dict(artifacts or {})


class InfrastructureTrialError(RuntimeError):
    def __init__(self, cause: InfrastructureCause, message: str) -> None:
        super().__init__(message)
        self.cause = cause


class CandidateTestTimeoutError(CandidateTrialError):
    def __init__(self, message: str = "candidate test exceeded its deadline") -> None:
        super().__init__("candidate_test_timeout", message)


def _bounded_failure_artifacts(
    primary: Mapping[str, bytes], partial: Mapping[str, bytes]
) -> dict[str, bytes]:
    """Retain rejected bytes first, then partials, within the result wire budget."""
    bounded: dict[str, bytes] = {}
    aggregate_bytes = 0
    artifact_count = 0
    for source in (primary, partial):
        for path in sorted(source):
            data = source[path]
            if not isinstance(path, str) or not isinstance(data, bytes) or path in bounded:
                continue
            try:
                safe_relative_path(path)
            except ValueError:
                continue
            if path != MANIFEST_PATH and artifact_count >= MAX_ARTIFACT_COUNT:
                continue
            if path == MANIFEST_PATH:
                retained = data[:MAX_ARTIFACT_BYTES]
            else:
                remaining = MAX_AGGREGATE_ARTIFACT_BYTES - aggregate_bytes
                if remaining == 0 and data:
                    continue
                retained = data[: min(MAX_ARTIFACT_BYTES, remaining)]
                aggregate_bytes += len(retained)
                artifact_count += 1
            bounded[path] = retained
    return bounded


class BridgeRuntime:
    """Wraps one ``PierTrialClient`` and serves exactly one ``TrialRequest``."""

    def __init__(self, client: PierTrialClient) -> None:
        self._client = client
        self._created = False

    def run_cell(self, request: TrialRequest) -> TrialResult:
        if self._created:
            raise TrialAlreadyRequestedError("this runtime has already created a trial")
        self._created = True
        handle = self._client.create(request)
        try:
            result = handle.run()
        except TrialTimeoutError as error:
            return self._failure(handle, request, cause="harness_deadline", error=error)
        except TrialCancelledError as error:
            return self._failure(handle, request, cause="cancelled", error=error)
        except asyncio.CancelledError:
            # BaseException, not Exception: an async client's own
            # cancellation must still tear the trial down before propagating.
            handle.teardown()
            raise
        except Exception as error:  # noqa: BLE001 - converted to a typed failure result
            return self._failure(handle, request, cause="unexpected_exception", error=error)
        effective = handle.teardown()
        if result.cell_id != request.cell_id:
            return TrialResult(
                cell_id=request.cell_id,
                outcome=InfrastructureFailure(
                    cause="mismatched_cell",
                    detail=(
                        f"trial handle returned a result for {result.cell_id!r}, "
                        f"not the requested {request.cell_id!r}"
                    ),
                    exception_type="MismatchedCellIdError",
                ),
                effective=effective,
                artifacts=result.artifacts,
            )
        return result.model_copy(update={"effective": effective})

    @staticmethod
    def _failure(
        handle: TrialHandle,
        request: TrialRequest,
        *,
        cause: InfrastructureCause,
        error: Exception,
    ) -> TrialResult:
        partial_artifacts: dict[str, bytes] = {}
        rejected_artifacts: dict[str, bytes] = {}
        outcome: CandidateFailure | InfrastructureFailure
        partial = getattr(handle, "partial_artifacts", None)
        if callable(partial):
            try:
                observed = partial()
                if isinstance(observed, Mapping):
                    partial_artifacts.update(observed)
            except ArtifactCollectionRejected as rejection:
                partial_artifacts.update(rejection.artifacts)
            except Exception:
                pass
        if isinstance(error, ArtifactCollectionRejected):
            if error.origin == "working_copy":
                # This prefix is bridge-owned. A candidate may create a file
                # with the same name in /submission, but cannot replace the
                # separately observed working-copy bytes in the result.
                partial_artifacts = {
                    path: data
                    for path, data in partial_artifacts.items()
                    if not path.startswith("rejected_worktree/")
                }
                rejected_artifacts.update(
                    {f"rejected_worktree/{path}": data for path, data in error.artifacts.items()}
                )
            else:
                rejected_artifacts.update(error.artifacts)
        elif isinstance(error, CandidateTrialError):
            rejected_artifacts.update(error.artifacts)
        artifacts = _bounded_failure_artifacts(rejected_artifacts, partial_artifacts)
        effective: EffectiveEnforcement = handle.teardown()
        if isinstance(error, ArtifactCollectionRejected):
            outcome = CandidateFailure(cause=cast(CandidateCause, error.cause), detail=str(error))
        elif isinstance(error, CandidateTrialError):
            outcome = CandidateFailure(cause=error.cause, detail=str(error))
        else:
            outcome = InfrastructureFailure(
                cause=error.cause if isinstance(error, InfrastructureTrialError) else cause,
                detail=str(error)[:2000] or type(error).__name__,
                exception_type=type(error).__name__,
            )
        return TrialResult(
            cell_id=request.cell_id,
            outcome=outcome,
            usage=None,
            effective=effective,
            artifacts=artifacts,
        )
