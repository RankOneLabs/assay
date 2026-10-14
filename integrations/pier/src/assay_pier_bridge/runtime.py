"""Trial lifecycle: exactly one ``Trial.create`` per cell, teardown always runs.

Never installs a package, resolves a dependency, or mutates a pricing map:
this module only orchestrates an already-created, already-locked
``PierTrialClient``. See ``tests/test_trial_lifecycle.py`` for the spy that
proves it.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import cast

from assay_pier_bridge.paths import ArtifactCollectionRejected, safe_relative_path
from assay_pier_bridge.protocol import (
    MANIFEST_PATH,
    MAX_AGGREGATE_ARTIFACT_BYTES,
    MAX_ARTIFACT_BYTES,
    MAX_ARTIFACT_COUNT,
    CandidateCause,
    CandidateFailure,
    EffectiveEnforcement,
    InfrastructureCause,
    InfrastructureFailure,
    PierTrialClient,
    TrialHandle,
    TrialRequest,
    TrialResult,
)


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
                retained = data[:min(MAX_ARTIFACT_BYTES, remaining)]
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
                    path: data for path, data in partial_artifacts.items()
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
