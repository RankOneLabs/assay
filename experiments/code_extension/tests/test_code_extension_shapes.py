"""The operator path preserves every shape arm's fixture and scope contracts."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import httpx
import pytest
from code_extension.fixture import PILOT, materialize, read_tree
from code_extension.fixtures import load_scenario, qualification_directory, sidecar_for_subject
from code_extension.probe import SUBMIT, reference_submission
from code_extension.study import load_qualified_study_fixture
from code_extension.tests.test_code_extension_hosted import hosted_configuration
from workflow_edit.tests.test_workflow_edit_bridge import FakeSandbox

from assay.canonical import digest_bytes
from assay.fixture_manifest import FixtureManifestV3
from assay.investigations.workflow_correctness import GroupResult, WorkflowCorrectnessResult
from assay.store import ObjectStore

ROOT = PILOT.parent / "stage-pass-through"
ARMS = ("modular", "central", "cross_module", "plugin")


@pytest.mark.parametrize("arm_id", ARMS)
async def test_scripted_reference_uses_the_selected_arm_and_all_changed_files(
    arm_id: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from code_extension import probe

    fixture = load_scenario("stage-pass-through", arm_id=arm_id)
    manifest = FixtureManifestV3.model_validate_json(
        (ROOT / "qualification/manifest.json").read_bytes()
    )
    image = manifest.observed_runtime_image_digest
    monkeypatch.setattr("code_extension.bridge.observed_image_digest", lambda _: image)
    monkeypatch.setattr("code_extension.probe.observed_image_digest", lambda _: image)
    original = probe._scripted_client

    def scripted(*args: Any, **kwargs: Any) -> Any:
        client = original(*args, **kwargs)
        client.sandbox_factory = FakeSandbox
        return client

    async def evaluate(**kwargs: Any) -> WorkflowCorrectnessResult:
        assert kwargs["arm_id"] == arm_id
        assert kwargs["baseline"] == fixture.repository
        return WorkflowCorrectnessResult(
            "correct", tuple(GroupResult(group.name, "passed") for group in fixture.groups), None,
        )

    monkeypatch.setattr(probe, "_scripted_client", scripted)
    monkeypatch.setattr(probe, "evaluate_scenario_candidate", evaluate)
    monkeypatch.setattr(probe, "make_runner", lambda _: None)
    record = await reference_submission(fixture, manifest, image)
    assert record["reference_tree_matches"] is True
    assert record["writable_prefixes"] == ["src/compiler/"]
    assert sidecar_for_subject(fixture.subject_id, arm_id) == fixture.sidecar


def test_committed_shape_gates_load_and_prepare_twenty_hosted_cells(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from code_extension.config import RunConfiguration
    from code_extension.run import prepare

    path = ROOT / "qualification/manifest.json"
    manifest = FixtureManifestV3.model_validate_json(path.read_bytes())
    image = manifest.observed_runtime_image_digest
    store = ObjectStore(tmp_path / "qualification")
    fixture = load_qualified_study_fixture(
        store, {"stage-pass-through": digest_bytes(path.read_bytes())}, image=image,
    )
    assert set(fixture.scenarios[0].realizations) == set(ARMS)
    for arm_id in ARMS:
        gates = qualification_directory(ROOT, arm_id) / "gates"
        assert json.loads((gates / "access-probe.json").read_bytes())["candidate_unchanged"]
        assert json.loads((gates / "leak-scan.json").read_bytes())["hits"] == []
    config = RunConfiguration.model_validate({
        **hosted_configuration().model_dump(mode="json"),
        "scenario_qualifications": [{"scenario": "stage-pass-through",
                                     "manifest_digest": digest_bytes(path.read_bytes())}],
        "image_digest": image, "repeats": 5,
    })
    monkeypatch.delenv("CODE_EXTENSION_ROUTING_CONFIG", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr("code_extension.bridge.observed_image_digest", lambda _: image)
    config_path = tmp_path / "config.json"
    config_path.write_bytes(config.canonical_bytes())
    first = prepare(config_path, tmp_path / "store")
    second = prepare(config_path, tmp_path / "store")
    assert first == second and first["attempts"] == 20
    assert {cell["arm_id"] for cell in first["tasks"]} == set(ARMS)
    assert first["effective_limits"]["ceiling"]["max_wall_time_seconds"] == 20 * 900
    assert first["schedule"]["kind"] == "subject-rotated-v1"
    assert first["schedule"]["randomized"] is False
    assert first["unresolved_blockers"] == []


def test_shape_loader_rejects_cross_arm_contracts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from code_extension import study

    path = ROOT / "qualification/manifest.json"
    manifest = FixtureManifestV3.model_validate_json(path.read_bytes())
    wrong = load_scenario("stage-pass-through", arm_id="central").sidecar
    monkeypatch.setattr(study, "sidecar_for_subject", lambda *_: wrong)
    with pytest.raises(ValueError, match="arm tree differs"):
        load_qualified_study_fixture(
            ObjectStore(tmp_path), {"stage-pass-through": digest_bytes(path.read_bytes())},
            image=manifest.observed_runtime_image_digest,
        )


async def test_hosted_shape_grid_retains_each_arm_and_reproduces_reports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from code_extension import run
    from code_extension.config import RunConfiguration
    from code_extension.publish import render_archive
    from workflow_edit.metrics import install_toolchain

    from assay.investigations.workflow_correctness import PreflightResult
    from assay.verify import export_bundle, verify_bundle

    manifest_path = ROOT / "qualification/manifest.json"
    manifest = FixtureManifestV3.model_validate_json(manifest_path.read_bytes())
    image = manifest.observed_runtime_image_digest
    config = RunConfiguration.model_validate({
        **hosted_configuration().model_dump(mode="json"),
        "scenario_qualifications": [{"scenario": "stage-pass-through",
                                     "manifest_digest": digest_bytes(manifest_path.read_bytes())}],
        "image_digest": image,
    })
    commands: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    expected: dict[str, list[str]] = {}
    for arm_id in ARMS:
        fixture = load_scenario("stage-pass-through", arm_id=arm_id)
        target = tmp_path / "reference" / arm_id
        materialize(target, fixture.repository, fixture.arms[0].reference_patch)
        patched = read_tree(target)
        changed = sorted(p for p in patched if patched[p] != fixture.repository.get(p))
        commands[arm_id] = [
            *(('write_file', {'path': p, 'content': patched[p]}) for p in changed),
            ('submit_output', SUBMIT),
        ]
        expected[arm_id] = changed

    def http_client(agent: Any) -> httpx.Client:
        def respond(_request: httpx.Request) -> httpx.Response:
            if agent.coordinate == "__route_probe__":
                message = {"role": "assistant", "content": "OK"}
                reason = "stop"
            else:
                arm_id = agent.coordinate.split(":")[1]
                name, arguments = commands[arm_id].pop(0)
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

    async def joined_thread(function: Any, *args: Any, **kwargs: Any) -> Any:
        with ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(function, *args, **kwargs).result()

    async def grade(_self: Any, **kwargs: Any) -> WorkflowCorrectnessResult:
        assert kwargs["patch"] and kwargs["enforce_extension_scope"]
        return WorkflowCorrectnessResult(
            "correct", tuple(GroupResult(group.name, "passed") for group in kwargs["groups"]),
            preflight=PreflightResult("passed"),
        )

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.delenv("CODE_EXTENSION_ROUTING_CONFIG", raising=False)
    monkeypatch.setattr("code_extension.bridge.observed_image_digest", lambda _: image)
    monkeypatch.setattr("assay_pier_bridge.agent_loop.RepositoryAgentClient._http_client",
                        http_client)
    def sandbox(*args: Any, **kwargs: Any) -> FakeSandbox:
        kwargs.pop("limits", None)
        return FakeSandbox(*args, **kwargs)

    monkeypatch.setattr("code_extension.bridge.DockerTmpfsToolSandbox", sandbox)
    monkeypatch.setattr("code_extension.run.asyncio.to_thread", joined_thread)
    monkeypatch.setattr("code_extension.run.DockerWorkflowRunner.run", grade)
    path = tmp_path / "config.json"
    path.write_bytes(config.canonical_bytes())
    store_path = tmp_path / "store"
    summary = run.prepare(path, store_path)
    result = await run.execute(Path(summary["plan"]), summary["digest"], store_path)
    assert result["status"] == "RunSucceeded" and all(not calls for calls in commands.values())
    index = json.loads(Path(result["run_index"]).read_bytes())
    assert index["expected_change_paths_by_arm"] == {manifest.scenarios[0].subject_id: expected}
    assert len(json.loads((Path(result["archive"]) / "index.json").read_bytes())) == 4
    dependencies = install_toolchain(tmp_path / "dependencies", offline=True)
    monkeypatch.setattr("workflow_edit.metrics.dependencies_directory", lambda _: dependencies)
    output = render_archive(store_path / "archive", tmp_path / "report")
    first = [p.read_bytes() for p in output]
    second = render_archive(store_path / "archive", tmp_path / "report")
    assert first == [p.read_bytes() for p in second]
    rows = json.loads(output[2].read_bytes())
    assert len(rows) == 4 and {row["arm"] for row in rows} == set(ARMS)
    bundle = export_bundle(ObjectStore(Path(result["archive"])), index["manifest_ref"],
                           tmp_path / "bundle")
    assert verify_bundle(bundle, index["manifest_ref"]) == ()
