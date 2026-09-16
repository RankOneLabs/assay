from __future__ import annotations

import subprocess
from dataclasses import dataclass, field

import pytest
from assay_pier_bridge.protocol import (
    EffectiveEnforcement,
    ModelRoute,
    TrialLimits,
    TrialRequest,
    TrialResult,
    TrialUsage,
)
from assay_pier_bridge.runtime import (
    BridgeRuntime,
    TrialAlreadyRequestedError,
    TrialCancelledError,
    TrialTimeoutError,
)

ROUTE = ModelRoute(
    endpoint="https://openrouter.ai/api/v1",
    model="anthropic/claude-3-haiku",
    provider="amazon-bedrock",
)
LIMITS = TrialLimits(cpu=1, memory_mb=512, pids=32, timeout_s=120)


def _request() -> TrialRequest:
    return TrialRequest(
        cell_id="s1:a1:w0",
        package_digest="sha256:" + "0" * 64,
        model_route=ROUTE,
        limits=LIMITS,
    )


def _clean_effective(**overrides: object) -> EffectiveEnforcement:
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
        containers_remaining=0,
        child_processes_remaining=0,
        teardown_completed=True,
    )
    base.update(overrides)
    return EffectiveEnforcement.model_validate(base)


@dataclass
class FakeTrialHandle:
    outcome: str  # "succeed", "fail", "timeout", "cancel"
    teardown_calls: list[str] = field(default_factory=list)

    def run(self) -> TrialResult:
        if self.outcome == "succeed":
            return TrialResult(
                cell_id="s1:a1:w0",
                status="succeeded",
                submission_ref="sha256:" + "1" * 64,
                usage=TrialUsage(prompt_tokens=1, completion_tokens=1, cost_usd=0.0001, requests=1),
                effective=_clean_effective(teardown_completed=False, containers_remaining=1),
            )
        if self.outcome == "fail":
            raise RuntimeError("agent crashed")
        if self.outcome == "timeout":
            raise TrialTimeoutError("deadline exceeded")
        if self.outcome == "cancel":
            raise TrialCancelledError("operator cancelled")
        raise AssertionError(self.outcome)

    def effective_enforcement(self) -> EffectiveEnforcement:
        return _clean_effective(teardown_completed=False, containers_remaining=1)

    def teardown(self) -> EffectiveEnforcement:
        self.teardown_calls.append("teardown")
        return _clean_effective()


@dataclass
class FakeTrialClient:
    outcome: str
    create_calls: list[TrialRequest] = field(default_factory=list)
    handle: FakeTrialHandle | None = None

    def create(self, request: TrialRequest) -> FakeTrialHandle:
        self.create_calls.append(request)
        self.handle = FakeTrialHandle(self.outcome)
        return self.handle


@pytest.fixture(autouse=True)
def forbid_subprocess_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    """No install, resolve, or pricing-mutation step may run a subprocess."""

    def _blocked(*args: object, **kwargs: object) -> None:
        raise AssertionError("BridgeRuntime must never spawn a subprocess while serving a trial")

    monkeypatch.setattr(subprocess, "run", _blocked)
    monkeypatch.setattr(subprocess, "Popen", _blocked)


@pytest.mark.parametrize(
    ("outcome", "expected_status"),
    [("succeed", "succeeded"), ("fail", "failed"), ("timeout", "timeout"), ("cancel", "cancelled")],
)
def test_lifecycle_always_tears_down_and_reports_status(outcome: str, expected_status: str) -> None:
    client = FakeTrialClient(outcome)
    runtime = BridgeRuntime(client)

    result = runtime.run_cell(_request())

    assert result.status == expected_status
    assert client.handle is not None
    assert client.handle.teardown_calls == ["teardown"]
    assert result.effective.teardown_completed is True
    assert result.effective.containers_remaining == 0
    assert result.effective.child_processes_remaining == 0


def test_create_is_called_exactly_once() -> None:
    client = FakeTrialClient("succeed")
    runtime = BridgeRuntime(client)

    runtime.run_cell(_request())

    assert len(client.create_calls) == 1


def test_verification_is_disabled_on_the_created_request() -> None:
    client = FakeTrialClient("succeed")
    runtime = BridgeRuntime(client)

    runtime.run_cell(_request())

    assert client.create_calls[0].verify is False


def test_a_second_run_cell_call_is_rejected() -> None:
    client = FakeTrialClient("succeed")
    runtime = BridgeRuntime(client)
    runtime.run_cell(_request())

    with pytest.raises(TrialAlreadyRequestedError):
        runtime.run_cell(_request())

    assert len(client.create_calls) == 1


def test_successful_result_effective_reflects_teardown_not_mid_run_snapshot() -> None:
    client = FakeTrialClient("succeed")
    runtime = BridgeRuntime(client)

    result = runtime.run_cell(_request())

    # FakeTrialHandle.run() returns a dirty mid-run snapshot; the runtime must
    # replace it with the post-teardown observation, never trust the earlier one.
    assert result.effective.containers_remaining == 0
    assert result.submission_ref is not None
