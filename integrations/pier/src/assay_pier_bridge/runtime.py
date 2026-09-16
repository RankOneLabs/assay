"""Trial lifecycle: exactly one ``Trial.create`` per cell, teardown always runs.

Never installs a package, resolves a dependency, or mutates a pricing map:
this module only orchestrates an already-created, already-locked
``PierTrialClient``. See ``tests/test_trial_lifecycle.py`` for the spy that
proves it.
"""

from __future__ import annotations

from assay_pier_bridge.protocol import (
    EffectiveEnforcement,
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
        except Exception as error:  # noqa: BLE001 - converted to a typed failure result
            return self._failure(handle, request, status="failed", error=error)
        effective = handle.teardown()
        return result.model_copy(update={"effective": effective})

    @staticmethod
    def _failure(
        handle: TrialHandle,
        request: TrialRequest,
        *,
        status: TrialStatus,
        error: Exception,
    ) -> TrialResult:
        effective: EffectiveEnforcement = handle.teardown()
        return TrialResult(
            cell_id=request.cell_id,
            status=status,
            submission_ref=None,
            usage=None,
            error_type=type(error).__name__,
            error_message=str(error)[:2000] or type(error).__name__,
            effective=effective,
        )
