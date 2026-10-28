from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import assay_pier_bridge.repository_trial as repository_trial
import httpx
import pytest
from assay_pier_bridge.agent_loop import (
    PILOT_TOOL_SCHEMAS,
    SYSTEM_PROMPT,
    AgentLoopError,
    DockerTmpfsStagingStorage,
    DockerTmpfsToolSandbox,
    LoopBounds,
    ModelTurn,
    RepositoryAgentClient,
    SandboxLimits,
    ToolOutput,
)
from assay_pier_bridge.identity import canonical_json, digest_bytes, package_digest
from assay_pier_bridge.paths import ArtifactCollectionRejected
from assay_pier_bridge.protocol import (
    REQUIRED_SUCCESS_KINDS,
    ArtifactManifest,
    CandidateFailure,
    CandidateSubmission,
    InfrastructureFailure,
    ModelRoute,
    TrialLimits,
    TrialRequest,
)
from assay_pier_bridge.repository_trial import (
    RepositoryAgentTrialClient,
    RepositoryAgentTrialHandle,
    _container_count,
    agent_configuration,
)
from assay_pier_bridge.runtime import BridgeRuntime, InfrastructureTrialError
from test_agent_loop import FakeSandbox, FakeStorage, _call
from test_support import exchange_for

LOCAL = ModelRoute(endpoint="http://willie:8900", model="qwen-coder-32b", provider="smithers-local")
LIMITS = SandboxLimits()
PACKAGE = {"instruction.md": "Edit", "workspace/src/a.ts": "one", "workspace/package.json": "{}"}


class Scripted:
    def __init__(self, *turns: list[dict[str, Any]]) -> None:
        self.turns = turns

    def __call__(self, *, turn: int, **kwargs: Any) -> ModelTurn:
        calls = self.turns[min(turn, len(self.turns)) - 1]
        return ModelTurn(
            message={"role": "assistant", "content": None, "tool_calls": calls},
            finish_reason="tool_calls", prompt_tokens=7, completion_tokens=3, cost_usd=None,
        )


@pytest.fixture(autouse=True)
def _reset() -> None:
    FakeSandbox.created.clear()
    FakeSandbox.peaks = {}
    FakeSandbox.oom_kill_count = FakeSandbox.late_oom_kills = 0


def _request(package: dict[str, str] = PACKAGE, **overrides: Any) -> TrialRequest:
    digest = package_digest(package)
    values: dict[str, Any] = dict(
        cell_id="s1:mess-00:w0",
        package_digest=digest,
        exchange=exchange_for("s1:mess-00:w0", digest),
        model_route=LOCAL,
        limits=TrialLimits(
            cpu=LIMITS.cpus, memory_mb=LIMITS.memory_mb, pids=LIMITS.pids, timeout_s=60,
            storage_mb=LIMITS.storage_mb,
        ),
        network_policy="toolchain-only",
    )
    values.update(overrides)
    return TrialRequest(**values)


def _runtime(tmp_path: Path, completion: Scripted, package: dict[str, str] = PACKAGE) -> Any:
    agent = RepositoryAgentClient(
        api_key=None, image="img", runs_root=tmp_path, model_route=LOCAL,
        completion=completion, writable_prefixes=("src/", "tests/visible/"),
        sandbox_factory=FakeSandbox, storage_factory=FakeStorage,
    )
    configuration = agent_configuration(
        bounds=LoopBounds(), limits=LIMITS, writable_prefixes=agent.writable_prefixes,
        model_route=LOCAL,
    )
    client = RepositoryAgentTrialClient(
        agent=agent, package=package, limits=LIMITS, configuration=configuration
    )
    return BridgeRuntime(client)


def test_enforcement_is_unverified_without_a_sandbox_observation(tmp_path: Path) -> None:
    agent = RepositoryAgentClient(
        api_key=None, image="img", runs_root=tmp_path, model_route=LOCAL,
        completion=Scripted([]), sandbox_factory=FakeSandbox, storage_factory=FakeStorage,
    )
    handle = RepositoryAgentTrialHandle(
        request=_request(), agent=agent, package=PACKAGE, limits=LIMITS, configuration={},
    )
    assert handle.effective_enforcement(remaining=0).teardown_completed is False
    handle._trajectory = {"events": [{
        "kind": "sandbox_created", "container": "container-1", "observed": {
            "user": "1234:5678", "tmpfs": {
                "/workspace": "size=40m", "/cache": "size=24m"
            }, "network_mode": "none", "nano_cpus": 2_000_000_000,
            "memory_bytes": 512 * 1024 * 1024, "pids_limit": 32,
        },
    }]}
    enforced = handle.effective_enforcement(remaining=0)
    assert (enforced.uid, enforced.gid) == (1234, 5678)
    assert (enforced.cpu_limit, enforced.memory_limit_mb, enforced.pids_limit) == (2, 512, 32)
    assert enforced.storage_limit_mb == 64
    assert enforced.teardown_completed is True


def test_tmpfs_defaults_and_authorized_quota_match(tmp_path: Path) -> None:
    agent = RepositoryAgentClient(
        api_key=None, image="img", runs_root=tmp_path, model_route=LOCAL,
        completion=Scripted([]),
    )
    assert agent.sandbox_factory is DockerTmpfsToolSandbox
    assert agent.storage_factory is DockerTmpfsStagingStorage
    with pytest.raises(ValueError, match="authorized trial storage_mb"):
        RepositoryAgentTrialClient(
            agent=agent, package=PACKAGE,
            limits=SandboxLimits(workspace_mb=128, cache_mb=128), configuration={},
        )


def test_rejected_overlapping_cell_does_not_cancel_the_active_cell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent = RepositoryAgentClient(
        api_key=None, image="img", runs_root=tmp_path, model_route=LOCAL,
        completion=Scripted([]), sandbox_factory=FakeSandbox, storage_factory=FakeStorage,
    )
    active = FakeSandbox(tmp_path, tmp_path, "img", "s1:first:w0")
    agent._active_sandbox = active
    agent._active_cell_id = "s1:first:w0"
    client = RepositoryAgentTrialClient(
        agent=agent, package=PACKAGE, limits=LIMITS, configuration={},
    )
    monkeypatch.setattr(repository_trial, "_container_count", lambda cell_id: 0)
    digest = package_digest(PACKAGE)
    rejected = _request(
        cell_id="s1:second:w0", exchange=exchange_for("s1:second:w0", digest)
    )
    agent._lock.acquire()
    try:
        result = BridgeRuntime(client).run_cell(rejected)
    finally:
        agent._lock.release()
    assert isinstance(result.outcome, InfrastructureFailure)
    assert "concurrency_limit" in result.outcome.detail
    assert not active.closed

    first = client.create(_request(
        cell_id="s1:first:w0", exchange=exchange_for("s1:first:w0", digest)
    ))
    first.cancel()
    assert active.closed


def test_lone_surrogate_tool_output_is_a_typed_candidate_failure(tmp_path: Path) -> None:
    class SurrogateSandbox(FakeSandbox):
        def execute(self, argv: list[str], **kwargs: Any) -> ToolOutput:
            return ToolOutput("exit=0\n\ud800", 10, False)

    agent = RepositoryAgentClient(
        api_key=None, image="img", runs_root=tmp_path, model_route=LOCAL,
        completion=Scripted([_call("run_command", {"command": "echo hi"}, 1)]),
        sandbox_factory=SurrogateSandbox, storage_factory=FakeStorage,
    )
    result = BridgeRuntime(RepositoryAgentTrialClient(
        agent=agent, package=PACKAGE, limits=LIMITS, configuration={},
    )).run_cell(_request())
    assert isinstance(result.outcome, CandidateFailure)
    assert result.outcome.cause == "invalid_tool_output_encoding"
    json.loads(result.artifacts["trajectory.json"])


def test_invalid_trajectory_unicode_does_not_mask_original_candidate_cause(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent = RepositoryAgentClient(
        api_key=None, image="img", runs_root=tmp_path, model_route=LOCAL,
        completion=Scripted([]), sandbox_factory=FakeSandbox, storage_factory=FakeStorage,
    )

    def broken_run(**kwargs: Any) -> Any:
        raise AgentLoopError(
            "invalid_tool_output_encoding",
            {"events": [], "messages": [{"content": "\ud800"}], "turns": []},
            rejection=ArtifactCollectionRejected(
                "invalid_tool_output_encoding", "bad output", origin="working_copy"
            ),
        )

    monkeypatch.setattr(agent, "run_cell", broken_run)
    result = BridgeRuntime(RepositoryAgentTrialClient(
        agent=agent, package=PACKAGE, limits=LIMITS, configuration={},
    )).run_cell(_request())
    assert isinstance(result.outcome, CandidateFailure)
    assert result.outcome.cause == "invalid_tool_output_encoding"
    assert b"\\ud800" in result.artifacts["trajectory.json"]


def test_billed_shape_failure_reaches_failed_trial_usage(tmp_path: Path) -> None:
    response = {
        "model": "anthropic/claude-3-haiku", "provider": "Amazon Bedrock",
        "choices": [],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.001},
    }
    agent = RepositoryAgentClient(
        api_key="test", image="img", runs_root=tmp_path,
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=response)),
        sandbox_factory=FakeSandbox, storage_factory=FakeStorage,
    )
    result = BridgeRuntime(RepositoryAgentTrialClient(
        agent=agent, package=PACKAGE, limits=LIMITS, configuration={},
    )).run_cell(_request(model_route=ModelRoute()))
    assert isinstance(result.outcome, InfrastructureFailure)
    assert result.usage is not None, result.outcome
    assert (result.usage.prompt_tokens, result.usage.completion_tokens,
            result.usage.requests, result.usage.cost_usd) == (10, 5, 1, 0.001)


def test_billed_unknown_token_count_reaches_failed_trial_usage(tmp_path: Path) -> None:
    response = {
        "model": "anthropic/claude-3-haiku", "provider": "Amazon Bedrock",
        "choices": [],
        "usage": {"prompt_tokens": 10, "cost": 0.001},
    }
    agent = RepositoryAgentClient(
        api_key="test", image="img", runs_root=tmp_path,
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=response)),
        sandbox_factory=FakeSandbox, storage_factory=FakeStorage,
    )
    result = BridgeRuntime(RepositoryAgentTrialClient(
        agent=agent, package=PACKAGE, limits=LIMITS, configuration={},
    )).run_cell(_request(model_route=ModelRoute()))
    assert isinstance(result.outcome, InfrastructureFailure)
    assert result.usage is not None
    assert (result.usage.prompt_tokens, result.usage.completion_tokens,
            result.usage.requests, result.usage.cost_usd) == (10, None, 1, 0.001)


def test_read_failure_after_dispatch_has_unknown_failed_trial_cost(tmp_path: Path) -> None:
    def fail_read(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadError("response read failed", request=request)

    agent = RepositoryAgentClient(
        api_key="test", image="img", runs_root=tmp_path,
        transport=httpx.MockTransport(fail_read),
        sandbox_factory=FakeSandbox, storage_factory=FakeStorage,
    )
    result = BridgeRuntime(RepositoryAgentTrialClient(
        agent=agent, package=PACKAGE, limits=LIMITS, configuration={},
    )).run_cell(_request(model_route=ModelRoute()))
    assert isinstance(result.outcome, InfrastructureFailure)
    assert result.usage is not None
    assert (result.usage.prompt_tokens, result.usage.completion_tokens,
            result.usage.requests, result.usage.cost_usd) == (0, 0, 1, None)


def test_teardown_counts_cell_label_and_refuses_failed_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []

    def listed(argv: list[str], **kwargs: Any) -> Any:
        calls.append(argv)
        return type("Result", (), {"returncode": 0, "stdout": ""})()

    monkeypatch.setattr("assay_pier_bridge.repository_trial.subprocess.run", listed)
    assert _container_count("s1:mess-00:w0") == 0
    assert calls[0][-1] == "label=assay-cell=s1:mess-00:w0"
    agent = RepositoryAgentClient(
        api_key=None, image="img", runs_root=tmp_path, model_route=LOCAL,
        completion=Scripted([]), sandbox_factory=FakeSandbox, storage_factory=FakeStorage,
    )
    handle = RepositoryAgentTrialHandle(
        request=_request(), agent=agent, package=PACKAGE, limits=LIMITS, configuration={},
    )
    handle._trajectory = {"events": [
        {"kind": "sandbox_created", "container": "any", "observed": {
            "user": "1000:1000", "tmpfs": {"/workspace": "size=256m"},
        }},
        {"kind": "cleanup_failed", "cause": "container_cleanup"},
    ]}
    assert not handle.teardown().teardown_completed
    monkeypatch.setattr("assay_pier_bridge.repository_trial.subprocess.run", lambda *a, **k: (
        type("Result", (), {"returncode": 1, "stdout": ""})()
    ))
    second = RepositoryAgentTrialHandle(
        request=_request(), agent=agent, package=PACKAGE, limits=LIMITS, configuration={},
    )
    second._trajectory = {"events": handle._trajectory["events"][:1]}
    assert not second.teardown().teardown_completed


def test_custom_agent_configuration_digests_tools_prompt_and_prefix(tmp_path: Path) -> None:
    tools = [{"type": "function", "function": {"name": "submit_output"}}]
    prefix = ({"role": "user", "content": "Pinned pilot session"},)
    agent = RepositoryAgentClient(
        api_key=None, image="img", runs_root=tmp_path, model_route=LOCAL,
        completion=Scripted([_call("submit_output", {"summary": "done"}, 1)]),
        tools=tools, system_prompt="Pilot prompt", message_prefix=prefix,
        sandbox_factory=FakeSandbox, storage_factory=FakeStorage,
    )
    configuration = agent_configuration(
        bounds=agent.bounds, limits=LIMITS, writable_prefixes=agent.writable_prefixes,
        model_route=agent.model_route, tools=agent.tools, system_prompt=agent.system_prompt,
        message_prefix=agent.message_prefix,
    )
    assert configuration["tools_sha256"] == digest_bytes(canonical_json(tools))
    assert configuration["system_prompt_sha256"] == digest_bytes(b"Pilot prompt")
    assert configuration["message_prefix_sha256"] == digest_bytes(canonical_json(prefix))


def test_pilot_configuration_and_sealed_per_turn_submissions(tmp_path: Path) -> None:
    turns = ("Review the first change", "Check all remaining work")
    completion = Scripted(
        [_call("submit_output", {"title": "Change", "body": "Body"}, 1)],
        [_call("submit_output", {"verdict": "incomplete", "remaining_v1": "one",
                                  "checks_performed": "read"}, 2)],
        [_call("submit_output", {"verdict": "complete", "remaining_v1": "",
                                  "checks_performed": "test"}, 3)],
    )
    agent = RepositoryAgentClient(
        api_key=None, image="img", runs_root=tmp_path, model_route=LOCAL,
        completion=completion, pilot_mode=True, next_user_turns=turns,
        writable_prefixes=("src/", "tests/"),
        max_tool_calls_per_turn=15, max_tool_calls_per_cell=40,
        sandbox_factory=FakeSandbox, storage_factory=FakeStorage,
    )
    configuration = agent_configuration(
        bounds=agent.bounds, limits=LIMITS, writable_prefixes=agent.writable_prefixes,
        model_route=LOCAL, pilot_mode=True, pilot_tools_by_turn=agent.pilot_tools_by_turn,
        next_user_turns=turns,
        max_tool_calls_per_turn=agent.max_tool_calls_per_turn,
        max_tool_calls_per_cell=agent.max_tool_calls_per_cell,
    )
    assert configuration["tools_sha256"] == digest_bytes(canonical_json(PILOT_TOOL_SCHEMAS))
    assert configuration["tools_t1_sha256"] == digest_bytes(
        canonical_json(agent.pilot_tools_by_turn["T1"]))
    assert configuration["tools_t2_t3_sha256"] == digest_bytes(
        canonical_json(agent.pilot_tools_by_turn["T2_T3"]))
    assert configuration["turn_prompts_sha256"] == digest_bytes(canonical_json(turns))
    result = BridgeRuntime(RepositoryAgentTrialClient(
        agent=agent, package=PACKAGE, limits=LIMITS, configuration=configuration,
    )).run_cell(_request())
    assert isinstance(result.outcome, CandidateSubmission)
    sealed = json.loads(result.artifacts["result.json"])
    assert sealed["summary"] == "Change"
    assert [entry["verdict"] for entry in sealed["submissions"][1:]] == [
        "incomplete", "complete"
    ]
    trajectory = json.loads(result.artifacts["trajectory.json"])
    assert len(trajectory["turns"]) == 3
    assert [turn["tools_sha256"] for turn in trajectory["turns"]] == [
        configuration["tools_t1_sha256"], configuration["tools_t2_t3_sha256"],
        configuration["tools_t2_t3_sha256"],
    ]
    assert all(turn["workspace_diff"] == "" for turn in trajectory["turns"])


@pytest.mark.parametrize("changed_field", ("tools_t1_sha256", "tools_t2_t3_sha256", "surface"))
def test_pilot_configuration_refuses_changed_tool_identity(
    tmp_path: Path, changed_field: str,
) -> None:
    agent = RepositoryAgentClient(
        api_key=None, image="img", runs_root=tmp_path, model_route=LOCAL,
        completion=Scripted([]), pilot_mode=True, next_user_turns=("Review", "Check"),
        writable_prefixes=("src/",), max_tool_calls_per_turn=15,
        max_tool_calls_per_cell=40, sandbox_factory=FakeSandbox,
        storage_factory=FakeStorage,
    )
    configuration = agent_configuration(
        bounds=agent.bounds, limits=LIMITS, writable_prefixes=agent.writable_prefixes,
        model_route=LOCAL, pilot_mode=True, pilot_tools_by_turn=agent.pilot_tools_by_turn,
        next_user_turns=agent.next_user_turns,
        max_tool_calls_per_turn=agent.max_tool_calls_per_turn,
        max_tool_calls_per_cell=agent.max_tool_calls_per_cell,
    )
    if changed_field == "surface":
        agent.pilot_tools_by_turn["T2_T3"].append(
            {"type": "function", "function": {"name": "extra"}})
    else:
        configuration[changed_field] = "sha256:changed"
    handle = RepositoryAgentTrialHandle(
        request=_request(), agent=agent, package=PACKAGE, limits=LIMITS,
        configuration=configuration,
    )
    with pytest.raises(InfrastructureTrialError) as failure:
        handle._check_request()
    assert failure.value.cause == "enforcement"


def test_timed_out_run_command_counts_as_unclassified(tmp_path: Path) -> None:
    completion = Scripted(
        [_call("run_command", {"command": "hang"}, 1)],
        [_call("submit_output", {"summary": "done"}, 2)],
    )
    result = _runtime(tmp_path, completion).run_cell(_request())
    assert isinstance(result.outcome, CandidateSubmission)
    sealed = json.loads(result.artifacts["result.json"])
    assert sealed["run_command_calls"] == 1
    assert sealed["run_command_scope_unclassified"] == 1
    assert sealed["run_command_scope_unclassified_rate"] == 1.0


def test_prefilled_conversation_limit_is_a_candidate_cause(tmp_path: Path) -> None:
    agent = RepositoryAgentClient(
        api_key=None, image="img", runs_root=tmp_path, model_route=LOCAL,
        completion=Scripted([_call("submit_output", {"summary": "done"}, 1)]),
        message_prefix=({"role": "user", "content": "Pinned pilot session"},),
        bounds=LoopBounds(max_conversation_bytes=1),
        sandbox_factory=FakeSandbox, storage_factory=FakeStorage,
    )
    configuration = agent_configuration(
        bounds=agent.bounds, limits=LIMITS, writable_prefixes=agent.writable_prefixes,
        model_route=agent.model_route, message_prefix=agent.message_prefix,
    )
    result = BridgeRuntime(RepositoryAgentTrialClient(
        agent=agent, package=PACKAGE, limits=LIMITS, configuration=configuration,
    )).run_cell(_request())
    assert isinstance(result.outcome, CandidateFailure)
    assert result.outcome.cause == "no_submission"
    assert "conversation_limit" in result.outcome.detail


def test_submission_is_sealed_against_the_exchange(tmp_path: Path) -> None:
    completion = Scripted(
        [_call("write_file", {"path": "src/a.ts", "content": "two"}, 1),
         _call("write_file", {"path": "src/b.ts", "content": "new"}, 2)],
        [_call("submit_output", {"summary": "done"}, 3)],
    )
    request = _request()
    result = _runtime(tmp_path, completion).run_cell(request)
    assert isinstance(result.outcome, CandidateSubmission)
    manifest = ArtifactManifest.model_validate_json(result.artifacts["manifest.json"])
    assert manifest.exchange == request.exchange
    assert {entry.kind for entry in manifest.entries} >= REQUIRED_SUCCESS_KINDS
    patch = result.artifacts["candidate.patch"]
    assert digest_bytes(patch) == result.outcome.patch_ref
    assert b"+two" in patch and b"+new" in patch
    assert result.artifacts["candidate_files/src/b.ts"] == b"new"
    assert json.loads(result.artifacts["result.json"])["exit_status"] == "Submitted"
    assert result.usage is not None and result.usage.requests == 2
    assert result.usage.cost_usd is None
    assert not result.effective.teardown_completed


def test_stopping_without_submission_is_a_typed_candidate_failure(tmp_path: Path) -> None:
    completion = Scripted([_call("write_file", {"path": "src/a.ts", "content": "half"}, 1)])
    result = _runtime(tmp_path, completion).run_cell(_request())
    assert isinstance(result.outcome, CandidateFailure)
    assert result.outcome.cause == "no_submission"
    assert "turn_limit" in result.outcome.detail
    assert "trajectory.json" in result.artifacts
    assert b"+half" in result.artifacts["stopped/candidate.patch"]


def test_pilot_configuration_records_the_prompt_it_was_given() -> None:
    """G14: pilot mode no longer substitutes a bridge prompt for the caller's.

    The deleted swap-in triggered on equality with ``SYSTEM_PROMPT``, so the
    recorded identity for that exact prompt is what proves the swap-in is gone.
    """
    configuration = agent_configuration(
        bounds=LoopBounds(), limits=LIMITS, writable_prefixes=("src/",), model_route=LOCAL,
        pilot_mode=True, next_user_turns=("Review", "Check"), system_prompt=SYSTEM_PROMPT,
        max_tool_calls_per_turn=7, max_tool_calls_per_cell=19,
    )
    assert configuration["system_prompt_sha256"] == digest_bytes(SYSTEM_PROMPT.encode("utf-8"))


def test_pilot_cell_cap_returns_partial_trace(tmp_path: Path) -> None:
    agent = RepositoryAgentClient(
        api_key=None, image="img", runs_root=tmp_path, model_route=LOCAL,
        completion=Scripted([_call("write_file", {"path": "src/a.ts", "content": "half"}, 1)]),
        pilot_mode=True, next_user_turns=("Review", "Check"),
        writable_prefixes=("src/", "tests/"),
        max_tool_calls_per_turn=2, max_tool_calls_per_cell=1,
        sandbox_factory=FakeSandbox, storage_factory=FakeStorage,
    )
    configuration = agent_configuration(
        bounds=agent.bounds, limits=LIMITS, writable_prefixes=agent.writable_prefixes,
        model_route=LOCAL, pilot_mode=True, next_user_turns=agent.next_user_turns,
        system_prompt=agent.system_prompt, max_tool_calls_per_turn=2,
        max_tool_calls_per_cell=1,
    )
    result = BridgeRuntime(RepositoryAgentTrialClient(
        agent=agent, package=PACKAGE, limits=LIMITS, configuration=configuration,
    )).run_cell(_request())
    assert isinstance(result.outcome, CandidateFailure)
    assert "cell_tool_call_limit" in result.outcome.detail
    trace = json.loads(result.artifacts["trajectory.json"])
    assert trace["turns"][0]["stop_cause"] == "cell_tool_call_limit"
    assert trace["turns"][0]["patch_ref"] == digest_bytes(
        result.artifacts["stopped/candidate.patch"]
    )


def test_spent_cell_budget_is_the_candidates_own_failure(tmp_path: Path) -> None:
    """``agent_deadline`` is a model failure, never the infrastructure harness deadline."""

    class OutOfTime(Scripted):
        def __call__(self, *, turn: int, **kwargs: Any) -> ModelTurn:
            if turn == 2:
                raise ValueError("agent_deadline")
            return super().__call__(turn=turn, **kwargs)

    completion = OutOfTime([_call("write_file", {"path": "src/a.ts", "content": "half"}, 1)])
    result = _runtime(tmp_path, completion).run_cell(_request())
    assert isinstance(result.outcome, CandidateFailure)
    assert result.outcome.cause == "agent_deadline"
    stopped = json.loads(result.artifacts["trajectory.json"])["events"][-1]
    assert stopped == {"kind": "stopped", "cause": "agent_deadline", "requests": 2}
    assert b"+half" in result.artifacts["stopped/candidate.patch"]
    assert not result.effective.teardown_completed


@pytest.mark.parametrize(
    ("stop_cause", "outcome_type", "trial_cause"),
    [
        ("provider_error", InfrastructureFailure, "enforcement"),
        ("empty_reply", CandidateFailure, "no_submission"),
        ("agent_deadline", CandidateFailure, "agent_deadline"),
    ],
)
def test_new_stop_causes_have_distinct_trial_types(
    tmp_path: Path, stop_cause: str,
    outcome_type: type[InfrastructureFailure] | type[CandidateFailure], trial_cause: str,
) -> None:
    class TerminalReply(Scripted):
        def __call__(self, *, turn: int, **kwargs: Any) -> ModelTurn:
            if stop_cause == "agent_deadline":
                raise ValueError("agent_deadline")
            return ModelTurn(
                message={"role": "assistant", "content": None},
                finish_reason="error" if stop_cause == "provider_error" else "stop",
                prompt_tokens=7, completion_tokens=3, cost_usd=None,
            )

    result = _runtime(tmp_path, TerminalReply()).run_cell(_request())
    assert isinstance(result.outcome, outcome_type)
    assert result.outcome.cause == trial_cause
    trajectory = json.loads(result.artifacts["trajectory.json"])
    assert trajectory["events"][-1]["cause"] == stop_cause


def test_scope_rejection_retains_the_rejected_worktree(tmp_path: Path) -> None:
    completion = Scripted(
        [_call("write_file", {"path": "package.json", "content": "{\"x\":1}"}, 1)],
        [_call("submit_output", {"summary": "s"}, 2)],
    )
    result = _runtime(tmp_path, completion).run_cell(_request())
    assert isinstance(result.outcome, CandidateFailure)
    assert result.outcome.cause == "tampering"
    assert result.artifacts["rejected_worktree/package.json"] == b"{\"x\":1}"


def test_storage_exhaustion_is_named(tmp_path: Path) -> None:
    FakeSandbox.peaks = {"oom_kills": 0, "workspace_free_kb": 0, "cache_free_kb": 9999}
    completion = Scripted([_call("submit_output", {"summary": "s"}, 1)])
    result = _runtime(tmp_path, completion).run_cell(_request())
    assert isinstance(result.outcome, CandidateFailure)
    assert result.outcome.cause == "storage_exhausted"


@pytest.mark.parametrize(
    "overrides",
    [
        {"limits": TrialLimits(cpu=1, memory_mb=4096, pids=128, timeout_s=60, storage_mb=512)},
        {"package_digest": "sha256:" + "9" * 64,
         "exchange": exchange_for("s1:mess-00:w0", "sha256:" + "9" * 64)},
    ],
)
def test_request_must_match_the_agent_it_runs(tmp_path: Path, overrides: dict[str, Any]) -> None:
    completion = Scripted([_call("submit_output", {"summary": "s"}, 1)])
    result = _runtime(tmp_path, completion).run_cell(_request(**overrides))
    assert isinstance(result.outcome, InfrastructureFailure)
    assert result.outcome.cause == "enforcement"
    assert not FakeSandbox.created
