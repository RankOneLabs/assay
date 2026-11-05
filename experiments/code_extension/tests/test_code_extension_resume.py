"""A billed interruption resumes untouched cells without changing prior evidence."""

from __future__ import annotations

import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest
from code_extension import run
from code_extension.budget import AttemptJournal
from code_extension.config import RunConfiguration
from code_extension.fixture import PILOT, materialize, read_tree
from code_extension.fixtures import load_scenario
from code_extension.probe import SUBMIT
from code_extension.resume import checkpoint, resume
from code_extension.tests.test_code_extension_hosted import hosted_configuration
from workflow_edit.tests.test_workflow_edit_bridge import FakeSandbox

from assay.canonical import digest_bytes
from assay.investigations.workflow_correctness import (
    GroupResult,
    PreflightResult,
    WorkflowCorrectnessResult,
)
from assay.models import ExecutionPlanV3, RunManifest
from assay.store import ObjectStore
from assay.verify import verify_manifest

pytestmark = pytest.mark.usefixtures("qualified_runner")


async def test_resume_unknown_bill_retains_prior_attempts_and_dispatches_only_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from assay_pier_bridge.agent_loop import InFlightDeadline

    manifest_path = PILOT.parent / "stage-pass-through/qualification/manifest.json"
    config = RunConfiguration.model_validate({
        **hosted_configuration().model_dump(mode="json"), "repeats": 2,
        "scenario_qualifications": [{"scenario": "stage-pass-through",
                                     "manifest_digest": digest_bytes(manifest_path.read_bytes())}],
        "image_digest": json.loads(manifest_path.read_bytes())["observed_runtime_image_digest"],
    })
    commands: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for arm in ("modular", "central", "cross_module", "plugin"):
        fixture = load_scenario("stage-pass-through", arm_id=arm)
        target = tmp_path / "reference" / arm
        materialize(target, fixture.repository, fixture.arms[0].reference_patch)
        patched = read_tree(target)
        changed = sorted(p for p in patched if patched[p] != fixture.repository.get(p))
        for repeat in range(2):
            coordinate = f"{fixture.subject_id}:{arm}:w{repeat}"
            commands[coordinate] = [
                *(("write_file", {"path": p, "content": patched[p]}) for p in changed),
                ("submit_output", SUBMIT),
            ]
    requests: Counter[str] = Counter()
    order: list[str] = []

    def http_client(agent: Any) -> httpx.Client:
        def respond(_request: httpx.Request) -> httpx.Response:
            coordinate = agent.coordinate
            requests[coordinate] += 1
            if coordinate == "__route_probe__":
                message: dict[str, Any] = {"role": "assistant", "content": "OK"}
                reason = "stop"
            else:
                if coordinate not in order:
                    order.append(coordinate)
                if len(order) == 2 and coordinate == order[1]:
                    raise InFlightDeadline(bytes_received=False)
                name, arguments = commands[coordinate].pop(0)
                message = {"role": "assistant", "content": None, "tool_calls": [{
                    "id": name, "type": "function", "function": {
                        "name": name, "arguments": json.dumps(arguments),
                    },
                }]}
                reason = "tool_calls"
            return httpx.Response(200, json={
                "model": config.route.model, "provider": "Azure",
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.001},
                "choices": [{"message": message, "finish_reason": reason}],
            })
        return httpx.Client(transport=httpx.MockTransport(respond))

    async def joined(function: Any, *args: Any, **kwargs: Any) -> Any:
        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(function, *args, **kwargs).result()

    async def grade(_self: Any, **kwargs: Any) -> WorkflowCorrectnessResult:
        return WorkflowCorrectnessResult(
            "correct", tuple(GroupResult(g.name, "passed") for g in kwargs["groups"]),
            preflight=PreflightResult("passed"),
        )

    def sandbox(*args: Any, **kwargs: Any) -> FakeSandbox:
        kwargs.pop("limits", None)
        return FakeSandbox(*args, **kwargs)

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.delenv("CODE_EXTENSION_ROUTING_CONFIG", raising=False)
    monkeypatch.setattr("code_extension.bridge.observed_image_digest",
                        lambda _: config.image_digest)
    monkeypatch.setattr("assay_pier_bridge.agent_loop.RepositoryAgentClient._http_client",
                        http_client)
    monkeypatch.setattr("code_extension.bridge.DockerTmpfsToolSandbox", sandbox)
    monkeypatch.setattr("code_extension.run.asyncio.to_thread", joined)
    monkeypatch.setattr("code_extension.run.DockerWorkflowRunner.run", grade)
    path = tmp_path / "config.json"
    path.write_bytes(config.canonical_bytes())
    store_path = tmp_path / "store"
    summary = run.prepare(path, store_path)
    plan_path = Path(summary["plan"])
    first = await run.execute(plan_path, summary["digest"], store_path)
    assert first["status"] == "RunFailed" and first["spend"]["halt"] == "billing_uncertain"
    index_path = Path(first["archive"]) / "index.json"
    original_index = json.loads(index_path.read_bytes())
    assert len(original_index) == 2 and len(order) == 2
    old_requests = dict(requests)
    original_ref = json.loads(Path(first["run_index"]).read_bytes())["manifest_ref"]
    store = ObjectStore(store_path)
    original = RunManifest.model_validate_json(store.read_bytes(original_ref))
    assert len(original.execution_records) == 3  # Includes an unclaimed spending refusal.
    with pytest.raises(run.LaunchRefused, match="resume halted: billing_uncertain"):
        await resume(plan_path, summary["digest"], store_path, original_ref)
    assert dict(requests) == old_requests
    result = await resume(
        plan_path, summary["digest"], store_path, original_ref,
        accept_unknown="Operator authorized bounded recovery of untouched cells",
    )
    assert result["status"] == "RunSucceeded"
    assert requests[order[0]] == old_requests[order[0]]
    assert requests[order[1]] == old_requests[order[1]] == 1
    assert requests["__route_probe__"] == 1
    assert len(order) == 8
    latest_index = json.loads(index_path.read_bytes())
    assert original_index.items() <= latest_index.items()
    latest_ref = json.loads(Path(str(result["run_index"])).read_bytes())["manifest_ref"]
    latest = RunManifest.model_validate_json(store.read_bytes(latest_ref))
    assert latest.run_id == original.run_id
    assert len(latest.execution_records) == len(latest.evaluation_records) == 8
    for cell in original_index:
        assert latest.execution_records[cell] == original.execution_records[cell]
        key = cell + ":correctness:e0"
        assert latest.evaluation_records[key] == original.evaluation_records[key]
    assert [f.code for f in verify_manifest(store, latest_ref)] == ["incomplete_run"]
    journal = [json.loads(line) for line in (plan_path.parent / "attempts.jsonl").read_bytes()
               .splitlines()]
    assert any(r["event"] == "uncertain_charge_accepted" for r in journal)
    assert any(r["event"] == "finished" and r["cost_usd"] is None for r in journal)
    audit = json.loads(store.read_bytes(str(result["resume_audit_ref"])))
    assert len(audit["remaining_coordinates"]) == 6


def test_checkpoint_refuses_a_claimed_attempt_without_a_terminal_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    digest = "sha256:" + "a" * 64
    store = ObjectStore(tmp_path / "store")
    ref = str(store.publish_json(RunManifest(
        run_id="run", plan_ref=digest, status="incomplete", execution_records={},
        evaluation_records={}, missing_coordinates=("cell",),
    ).model_dump(mode="json")))
    journal = AttemptJournal(tmp_path / "attempts.jsonl", digest, "sha256:" + "b" * 64)
    journal.claim_attempt("cell", "attempt")
    monkeypatch.setattr("code_extension.resume.verify_manifest", lambda *_: ())
    plan = cast(ExecutionPlanV3, SimpleNamespace(cells=(), evaluations=()))
    with pytest.raises(run.LaunchRefused, match="lacks a terminal outcome"):
        checkpoint(store, plan, ref, journal)
