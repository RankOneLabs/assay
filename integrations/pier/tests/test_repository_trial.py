from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from assay_pier_bridge.agent_loop import (
    PILOT_TOOL_SCHEMAS,
    LoopBounds,
    ModelTurn,
    RepositoryAgentClient,
    SandboxLimits,
)
from assay_pier_bridge.identity import canonical_json, digest_bytes, package_digest
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
from assay_pier_bridge.repository_trial import RepositoryAgentTrialClient, agent_configuration
from assay_pier_bridge.runtime import BridgeRuntime
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
        model_route=LOCAL, pilot_mode=True, next_user_turns=turns,
        max_tool_calls_per_turn=agent.max_tool_calls_per_turn,
        max_tool_calls_per_cell=agent.max_tool_calls_per_cell,
    )
    assert configuration["tools_sha256"] == digest_bytes(canonical_json(PILOT_TOOL_SCHEMAS))
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
    assert all(turn["workspace_diff"] == "" for turn in trajectory["turns"])


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
    assert result.effective.teardown_completed


def test_stopping_without_submission_is_a_typed_candidate_failure(tmp_path: Path) -> None:
    completion = Scripted([_call("write_file", {"path": "src/a.ts", "content": "half"}, 1)])
    result = _runtime(tmp_path, completion).run_cell(_request())
    assert isinstance(result.outcome, CandidateFailure)
    assert result.outcome.cause == "no_submission"
    assert "turn_limit" in result.outcome.detail
    assert "trajectory.json" in result.artifacts
    assert b"+half" in result.artifacts["stopped/candidate.patch"]


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
    assert result.effective.teardown_completed


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
