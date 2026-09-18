from __future__ import annotations

import pytest
from assay_pier_bridge.protocol import (
    EffectiveEnforcement,
    ModelRoute,
    TrialLimits,
    TrialRequest,
    TrialResult,
    TrialUsage,
)
from pydantic import ValidationError

ROUTE = ModelRoute(
    endpoint="https://openrouter.ai/api/v1",
    model="anthropic/claude-3-haiku",
    provider="amazon-bedrock",
)
LIMITS = TrialLimits(cpu=1, memory_mb=512, pids=32, timeout_s=120, storage_mb=64)


def effective(**overrides: object) -> EffectiveEnforcement:
    base = dict(
        uid=1000,
        gid=1000,
        workspace_read_only=True,
        submission_mount="/submission",
        scratch_mount="/scratch",
        network_policy="egress-openrouter-only",
        cpu_limit=1.0,
        memory_limit_mb=512,
        pids_limit=32,
        storage_limit_mb=64,
        containers_remaining=0,
        child_processes_remaining=0,
        teardown_completed=True,
    )
    base.update(overrides)
    return EffectiveEnforcement.model_validate(base)


def test_trial_request_disables_verification_by_default() -> None:
    request = TrialRequest(
        cell_id="s1:a1:w0",
        package_digest="sha256:" + "0" * 64,
        model_route=ROUTE,
        limits=LIMITS,
    )
    assert request.verify is False


def test_trial_request_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        TrialRequest.model_validate(
            {
                "cell_id": "s1:a1:w0",
                "package_digest": "sha256:" + "0" * 64,
                "model_route": ROUTE.model_dump(),
                "limits": LIMITS.model_dump(),
                "extra_upstream_field": "not allowed",
            }
        )


def test_trial_request_rejects_verify_true() -> None:
    with pytest.raises(ValidationError):
        TrialRequest.model_validate(
            {
                "cell_id": "s1:a1:w0",
                "package_digest": "sha256:" + "0" * 64,
                "model_route": ROUTE.model_dump(),
                "limits": LIMITS.model_dump(),
                "verify": True,
            }
        )


def test_succeeded_result_requires_submission_and_no_error() -> None:
    with pytest.raises(ValidationError):
        TrialResult(
            cell_id="s1:a1:w0",
            status="succeeded",
            submission_ref=None,
            effective=effective(),
        )


def test_failed_result_requires_error_and_no_submission() -> None:
    with pytest.raises(ValidationError):
        TrialResult(
            cell_id="s1:a1:w0",
            status="failed",
            submission_ref="sha256:" + "1" * 64,
            error_type="Boom",
            error_message="boom",
            effective=effective(),
        )


def test_succeeded_result_is_valid() -> None:
    result = TrialResult(
        cell_id="s1:a1:w0",
        status="succeeded",
        submission_ref="sha256:" + "1" * 64,
        usage=TrialUsage(prompt_tokens=10, completion_tokens=5, cost_usd=0.001, requests=1),
        effective=effective(),
    )
    assert result.status == "succeeded"


def test_effective_enforcement_rejects_dirty_teardown() -> None:
    with pytest.raises(ValidationError):
        effective(teardown_completed=True, containers_remaining=1)


def test_effective_enforcement_allows_incomplete_teardown_with_residue() -> None:
    residual = effective(teardown_completed=False, containers_remaining=1)
    assert residual.containers_remaining == 1
