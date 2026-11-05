"""The added matched tasks stay matched, separate failure kinds, and prepare exactly."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from code_extension import authoring, diagnose, qualify
from code_extension.config import RunConfiguration
from code_extension.fixture import ADDED_SCENARIOS, AGENT_TEST_PREFIX, PILOT, materialize, read_tree
from code_extension.fixtures import load_scenario
from code_extension.probe import AGENT_PROBE_COMMAND
from code_extension.run import prepare

from assay.canonical import canonical_json, digest_bytes
from assay.investigations.workflow_correctness import workflow_tree_digest

pytestmark = pytest.mark.usefixtures("qualified_runner")

TASKS = ("stage-status-report", "stage-collect-artifacts")
ARMS = authoring.SHAPE_ARMS
EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
CONFIGS = ("hosted-matched-tasks-ministral.json", "hosted-matched-tasks-qwen.json")


def _feature_test_names(name: str) -> list[str]:
    root = PILOT.parent / name / "hidden" / "new_behavior"
    return [
        title for path in root.rglob("*.test.ts")
        for title in re.findall(r'^(?:test|\]\))\(?"([^"]+)"', path.read_text(), re.MULTILINE)
    ]


@pytest.mark.parametrize("name", TASKS)
@pytest.mark.parametrize("arm", ARMS)
def test_arm_start_tree_is_the_pass_through_arm_with_a_new_identity(name: str, arm: str) -> None:
    fixture = load_scenario(name, arm_id=arm)
    source = load_scenario("stage-pass-through", arm_id=arm)
    changed = {
        path for path in fixture.repository.keys() | source.repository.keys()
        if fixture.repository.get(path) != source.repository.get(path)
    }
    assert changed == {"package.json", "package-lock.json"}
    assert fixture.subject_id == ADDED_SCENARIOS[name].subject_id
    assert fixture.subject_id in fixture.repository["package.json"]
    assert not any(path.startswith(AGENT_TEST_PREFIX) for path in fixture.repository)


@pytest.mark.parametrize("name", TASKS)
def test_arms_share_the_task_and_every_frozen_group(name: str) -> None:
    fixtures = [load_scenario(name, arm_id=arm) for arm in ARMS]
    assert len({fixture.task for fixture in fixtures}) == 1
    assert len({fixture.tree_digest for fixture in fixtures}) == len(ARMS)
    for index in range(3):
        assert len({
            digest_bytes(canonical_json(fixture.groups[index].model_dump(mode="json")))
            for fixture in fixtures
        }) == 1


@pytest.mark.parametrize("name", TASKS)
@pytest.mark.parametrize("arm", ARMS)
def test_scope_permits_a_normal_solution_and_agent_tests(name: str, arm: str) -> None:
    fixture = load_scenario(name, arm_id=arm)
    assert fixture.sidecar.writable_implementation_scope == ("src/", AGENT_TEST_PREFIX)
    assert "tests/agent/" in fixture.task
    protected = set(fixture.sidecar.protected_assets.paths)
    assert {path for path in fixture.repository if path.startswith("tests/visible/")} <= protected
    assert {"package.json", "package-lock.json", "tsconfig.json"} <= protected


@pytest.mark.parametrize("name", TASKS)
def test_feature_checks_and_assertions_name_their_failure_kind(name: str) -> None:
    titles = _feature_test_names(name)
    assert titles and all(title.startswith(("reachability: ", "semantics: ")) for title in titles)
    assert sum(title.startswith("reachability: ") for title in titles) == 1
    sidecar = load_scenario(name, arm_id="modular").sidecar
    feature = [
        item.assertion_id for item in sidecar.test_assertions
        if item.group_name == "new_behavior"
    ]
    assert all(item.startswith(("reachability-", "semantics-")) for item in feature)
    assert sum(item.startswith("reachability-") for item in feature) == 1


@pytest.mark.parametrize("name", TASKS)
def test_authoring_reproduces_the_committed_assets(name: str, tmp_path: Path) -> None:
    committed = PILOT.parent / name
    shutil.copytree(PILOT.parent / authoring.SOURCE_SCENARIO, tmp_path / authoring.SOURCE_SCENARIO)
    (tmp_path / name).mkdir()
    authoring.author(authoring.TASKS[name], tmp_path)
    for arm in ARMS:
        assert read_tree(tmp_path / name / "repository" / arm) == read_tree(
            committed / "repository" / arm
        )
        sidecar = Path("qualification/arms") / arm / "sidecar.json"
        fresh = json.loads((tmp_path / name / sidecar).read_text())
        kept = json.loads((committed / sidecar).read_text())
        fresh.pop("evidence")
        kept.pop("evidence")
        assert fresh == kept
    assert read_tree(tmp_path / name / "patches") == read_tree(committed / "patches")
    assert read_tree(tmp_path / name / "hidden" / "regression") == read_tree(
        committed / "hidden" / "regression"
    )


@pytest.mark.parametrize("name", TASKS)
@pytest.mark.parametrize("arm", ARMS)
def test_retained_controls_fail_only_the_feature_group(name: str, arm: str) -> None:
    gates = PILOT.parent / name / "qualification/arms" / arm / "gates"
    controls = json.loads((gates / "double-reproduction.json").read_text())["controls"]
    assert set(controls) == {
        "start", "reference", f"{arm}.negative.patch", f"{arm}.wrong-semantics.patch",
    }
    for label, runs in controls.items():
        assert len(runs) == 2 and runs[0] == runs[1]
        statuses = {group: item["status"] for group, item in runs[0]["groups"].items()}
        assert statuses == {
            "visible_regression": "passed", "hidden_regression": "passed",
            "new_behavior": "passed" if label == "reference" else "failed",
        }


@pytest.mark.parametrize("name", TASKS)
@pytest.mark.parametrize("arm", ARMS)
def test_access_probe_covers_the_agent_test_namespace(name: str, arm: str) -> None:
    gate = json.loads(
        (PILOT.parent / name / "qualification/arms" / arm / "gates/access-probe.json").read_text()
    )
    replies = {(item["tool"], item["target"]): item["response"] for item in gate["attempts"]}
    assert replies[("run_command", AGENT_PROBE_COMMAND)] == "exit=0\nPASSED\n"
    assert replies[("read_file", "tests/agent/probe-link")].startswith("error:")
    assert gate["candidate_unchanged"] is True


def test_plugin_missing_integration_offers_the_compiler_but_never_enables_it() -> None:
    for name in TASKS:
        fixture = load_scenario(name, arm_id="plugin")
        patch = fixture.arms[0].negative_patches[0]
        stage = authoring.TASKS[name].stage_type
        assert f"{stage}: " in patch and authoring.PLUGIN_CONFIG not in patch


def _require_image() -> None:
    available = shutil.which("docker") is not None and subprocess.run(
        ("docker", "image", "inspect", qualify.IMAGE_TAG), capture_output=True, check=False,
        timeout=30,
    ).returncode == 0
    if not available:
        if os.environ.get("ASSAY_REQUIRE_EXTENSION_IMAGE"):
            pytest.fail("pinned extension image is not provisioned")
        pytest.skip("pinned extension image is not provisioned")


@pytest.mark.asyncio
@pytest.mark.parametrize("name", TASKS)
@pytest.mark.parametrize("arm", ARMS)
@pytest.mark.parametrize(("patch_index", "reachable"), [(0, False), (1, True)])
async def test_retained_group_output_separates_reachability_from_semantics(
    name: str, arm: str, patch_index: int, reachable: bool, tmp_path: Path,
) -> None:
    """Analysis reads this split from retained output, so the output must carry it."""
    _require_image()
    fixture = load_scenario(name, arm_id=arm)
    patch = fixture.arms[0].negative_patches[patch_index]
    materialize(tmp_path, fixture.repository, patch)
    runner = qualify.make_runner(qualify.observed_image_digest(qualify.IMAGE_TAG))
    result = await runner.run(
        baseline=fixture.repository, baseline_tree_digest=fixture.tree_digest,
        expected_tree_digest=workflow_tree_digest(read_tree(tmp_path)), patch=patch,
        groups=fixture.groups,
    )
    feature = next(group for group in result.groups if group.name == "new_behavior")
    failed = diagnose._FAIL.findall(f"{feature.stdout}\n{feature.stderr}")
    assert failed
    assert any(title.startswith("semantics: ") for title in failed)
    assert any(title.startswith("reachability: ") for title in failed) is not reachable


@pytest.mark.parametrize("config_name", CONFIGS)
def test_example_config_prepares_exactly_forty_cells_and_dispatches_nothing(
    config_name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = RunConfiguration.load(EXAMPLES / config_name)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("CODE_EXTENSION_ROUTING_CONFIG", raising=False)
    monkeypatch.setattr("code_extension.bridge.observed_image_digest",
                        lambda _: config.image_digest)
    summary = prepare(EXAMPLES / config_name, tmp_path / "store")
    assert summary["attempts"] == 40
    assert {
        (cell["subject_id"], cell["arm_id"], cell["worker_repeat"]) for cell in summary["tasks"]
    } == {
        (ADDED_SCENARIOS[name].subject_id, arm, repeat)
        for name in TASKS for arm in ARMS for repeat in range(5)
    }
    assert summary["route_probe_calls"] == 1
    assert summary["schedule"]["kind"] == "subject-rotated-v1"
    assert summary["expected_serial_duration"]["maximum_seconds"] == 40 * 900
    assert summary["billing_recovery"]["default"] == "halt_on_unknown_charge"
    assert summary["caps"]["per_plan_usd"] == str(config.total_cap_usd)
    arms = summary["identity"]["arms"]
    assert set(arms) == {ADDED_SCENARIOS[name].subject_id for name in TASKS}
    for subject in arms.values():
        assert set(subject) == set(ARMS)
        assert len({arm["task_prompt_digest"] for arm in subject.values()}) == 1
        assert all(arm["writable_scope"] == ["src/", AGENT_TEST_PREFIX] for arm in subject.values())
    assert not (Path(summary["plan"]).parent / "attempts.jsonl").exists()


def test_example_configs_differ_only_in_their_route_and_labels() -> None:
    ministral, qwen = (json.loads((EXAMPLES / name).read_text()) for name in CONFIGS)
    assert ministral["route"] == {
        "endpoint": "https://openrouter.ai/api/v1", "model": "mistralai/ministral-14b-2512",
        "provider": "mistral/zdr",
    }
    assert qwen["route"] == {
        "endpoint": "https://openrouter.ai/api/v1", "model": "qwen/qwen3.8-27b",
        "provider": "deepinfra/bf16",
    }
    labels = {"route", "cohort", "randomization_seed"}
    assert {key: value for key, value in ministral.items() if key not in labels} == {
        key: value for key, value in qwen.items() if key not in labels
    }
