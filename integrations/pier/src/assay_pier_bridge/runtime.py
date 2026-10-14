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

from assay_pier_bridge.paths import ArtifactCollectionRejected
from assay_pier_bridge.protocol import (
    CandidateCause,
    CandidateFailure,
    EffectiveEnforcement,
    InfrastructureCause,
    InfrastructureFailure,
    PierTrialClient,
    TrialHandle,
    TrialRequest,
    TrialResult,
    TrialStatus,
)


class TrialAlreadyRequestedError(Exception):
    """A ``BridgeRuntime`` is single-use: one authorized cell, one trial."""


class TrialTimeoutError(Exception):
    """Raised by a ``TrialHandle.run()`` implementation on a deadline breach."""


class TrialCancelledError(Exception):
    """Raised by a ``TrialHandle.run()`` implementation on operator cancellation."""


class CandidateTrialError(RuntimeError):
    """A candidate-caused rejection with a stable, typed reason."""

    def __init__(self, cause: CandidateCause, message: str) -> None:
        super().__init__(message)
        self.cause = cause


class CandidateTestTimeoutError(CandidateTrialError):
    def __init__(self, message: str = "candidate test exceeded its deadline") -> None:
        super().__init__("candidate_test_timeout", message)


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
            return self._failure(handle, request, status="timeout", error=error)
        except TrialCancelledError as error:
            return self._failure(handle, request, status="cancelled", error=error)
        except asyncio.CancelledError:
            # BaseException, not Exception: an async client's own
            # cancellation must still tear the trial down before propagating.
            handle.teardown()
            raise
        except Exception as error:  # noqa: BLE001 - converted to a typed failure result
            return self._failure(handle, request, status="failed", error=error)
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
        status: TrialStatus,
        error: Exception,
    ) -> TrialResult:
        artifacts: dict[str, bytes] = {}
        outcome: CandidateFailure | InfrastructureFailure
        if isinstance(error, ArtifactCollectionRejected):
            artifacts.update(error.artifacts)
        partial = getattr(handle, "partial_artifacts", None)
        if callable(partial):
            try:
                observed = partial()
                if isinstance(observed, Mapping):
                    artifacts.update(observed)
            except ArtifactCollectionRejected as rejection:
                artifacts.update(rejection.artifacts)
            except Exception:
                pass
        effective: EffectiveEnforcement = handle.teardown()
        if isinstance(error, ArtifactCollectionRejected):
            outcome = CandidateFailure(cause=cast(CandidateCause, error.cause), detail=str(error))
        elif isinstance(error, CandidateTrialError):
            outcome = CandidateFailure(cause=error.cause, detail=str(error))
        else:
            cause: InfrastructureCause = (
                "harness_deadline"
                if status == "timeout"
                else "cancelled"
                if status == "cancelled"
                else "unexpected_exception"
            )
            outcome = InfrastructureFailure(
                cause=cause,
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
