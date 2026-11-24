"""The kbbl build-guard replay fixture: committed shape, groups, task and held patches."""

from __future__ import annotations

import json

import pytest
from code_extension.fixture import COLOCATED_VISIBLE, PILOT, read_tree
from code_extension.fixtures import load_scenario
from code_extension.replay_kbbl82 import (
    AGENT_FILES,
    ALL_ARMS,
    ARMS,
    BUILD_ENTRY,
    DISPATCHER,
    FRAMING,
    HIDDEN_TEST,
    LIVE,
    NAME,
    REGRESSION_TESTS,
    STAGE_RUNS,
    STAGE_RUNS_ARM,
    START_SHA,
    SUBJECT_ID,
    TASK_EDIT,
    relocate,
    scenario_name,
)

from assay.canonical import canonical_json, digest_bytes
from assay.fixture_manifest import FixtureManifestV3
from assay.repository import validate_repository

ROOT = PILOT.parent / NAME


def test_start_tree_fits_the_repository_bounds() -> None:
    fixture = load_scenario(NAME)
    tree = validate_repository(fixture.repository)
    assert len(tree) <= 200 and sum(len(text.encode()) for text in tree.values()) <= 1_000_000
    assert "bun.lock" not in tree and BUILD_ENTRY in tree
    assert "kbbl/core/server/handlers/builds.ts" not in tree
    assert all(path in tree for path in AGENT_FILES if not path.endswith("builds.ts"))


def test_groups() -> None:
    fixture = load_scenario(NAME)
    visible, regression, behavior = fixture.groups
    assert visible.restores and visible.name == "visible_regression"
    assert set(visible.files) == set(COLOCATED_VISIBLE[NAME].select(fixture.repository))
    assert "kbbl/core/db/briefs.test.ts" in visible.files
    assert all(not path.startswith("kbbl/core/pwa/") for path in visible.files)
    assert set(regression.files) == {"tests/hidden/regression/" + p for p in REGRESSION_TESTS}
    assert set(behavior.files) == {f"tests/hidden/new-behavior/{HIDDEN_TEST}"}
    hidden = read_tree(ROOT / "hidden" / "regression")
    tree = read_tree(ROOT / "repository")
    for path in REGRESSION_TESTS:
        target = "tests/hidden/regression/" + path
        assert hidden[target] == relocate(tree[path], path, target)


def test_held_patches_and_expectations() -> None:
    fixture = load_scenario(NAME)
    kinds = sorted(item.kind for item in fixture.sidecar.patch_inventory)
    assert kinds == ["incomplete", "incomplete", "reference", "reference", "reference"]
    assert [item.patch_name for item in fixture.sidecar.negative_expectations] == [
        "negative.patch", "no-guard.patch",
    ]
    assert len(fixture.arms[0].negative_patches) == 2


def test_task_is_the_brief_with_the_guard_stated_as_intent() -> None:
    task = load_scenario(NAME).task
    assert task.startswith(FRAMING)
    assert TASK_EDIT[0] not in task and task.count(LIVE) == 1
    # The brief as the agent had it: no deviations, and planner2's write is still stated.
    assert "Deviations from plan" not in task
    assert "cohorts for planner2 and build" in task


@pytest.mark.parametrize("arm", ["", *sorted(ALL_ARMS)])
def test_qualified_manifest_binds_the_replay(arm: str) -> None:
    fixture = load_scenario(scenario_name(arm))
    records = PILOT.parent / scenario_name(arm) / "qualification"
    manifest = FixtureManifestV3.model_validate_json((records / "manifest.json").read_bytes())
    manifest.require_qualified()
    scenario = manifest.scenario(fixture.subject_id)
    assert scenario is not None
    assert scenario.checkpoint_sha == START_SHA
    assert scenario.excluded_paths == ()
    assert set(scenario.included_paths) == set(fixture.repository) - {BUILD_ENTRY}
    assert scenario.feature_request == fixture.task.splitlines()[0]
    assert {
        group.name: group.digest for group in (*scenario.visible_tests, *scenario.hidden_tests)
    } == {
        group.name: digest_bytes(canonical_json(group.model_dump(mode="json")))
        for group in fixture.groups
    }
    (arm,) = scenario.arms
    assert arm.tree_digest == fixture.tree_digest and arm.task_prompt == fixture.task
    assert arm.reference_patch == digest_bytes(fixture.arms[0].reference_patch.encode())
    for check, outcome in (
        ("baseline_passes", "passed"), ("feature_fails", "failed"), ("reference_passes", "passed"),
    ):
        result = getattr(arm.qualification, check)
        evidence = (records / "evidence" / "baseline" / f"{check}.json").read_bytes()
        assert result.outcome == outcome and result.evidence == digest_bytes(evidence)
        assert json.loads(evidence)["image_digest"] == manifest.observed_runtime_image_digest
    sidecar = json.loads((records / "sidecar.json").read_text())
    for gate, digest in sidecar["evidence"].items():
        record = (records / "gates" / f"{gate.replace('_', '-')}.json").read_bytes()
        assert digest == digest_bytes(record), gate


@pytest.mark.parametrize("arm", sorted(ARMS))
def test_fact_shape_arm_differs_from_the_replay_by_its_one_statement(arm: str) -> None:
    base, variant = load_scenario(NAME), load_scenario(scenario_name(arm))
    assert variant.subject_id == f"{SUBJECT_ID}-{arm}"
    assert variant.groups == base.groups
    changed = {
        path for path in {*base.repository, *variant.repository}
        if base.repository.get(path) != variant.repository.get(path)
    }
    if arm in ("near-ask", "lifetime"):
        assert changed == set()
        assert variant.task.count("planner2 as well as for build") == 1
        lifetime = variant.task.count("ends only when the operator ends it")
        assert lifetime == (arm == "lifetime")
        assert len(variant.task.splitlines()) == len(base.task.splitlines()) + 1 + lifetime
    else:
        assert variant.task == base.task
        assert changed == {DISPATCHER}
        before = base.repository[DISPATCHER].splitlines()
        after = variant.repository[DISPATCHER].splitlines()
        assert len({*after} - {*before}) == 1 and "planner2" in "\n".join(after)
    assert [item.kind for item in variant.sidecar.patch_inventory] == [
        item.kind for item in base.sidecar.patch_inventory
    ]


def test_stage_runs_arm_replaces_the_shared_ref_and_keeps_the_hidden_checks() -> None:
    base, variant = load_scenario(NAME), load_scenario(scenario_name(STAGE_RUNS_ARM))
    assert variant.subject_id == f"{SUBJECT_ID}-{STAGE_RUNS_ARM}"
    assert variant.groups == base.groups
    changed = {
        path for path in {*base.repository, *variant.repository}
        if base.repository.get(path) != variant.repository.get(path)
    }
    assert changed == {
        DISPATCHER,
        STAGE_RUNS,
        "kbbl/core/db/migrations/007_stages_and_refs.sql",
        "kbbl/core/types/task-tracker.ts",
    }
    assert not any("current_session_ref" in text for text in variant.repository.values())
    assert "current_session_ref" not in variant.task
    assert variant.task.count("stage_runs") >= 3
    hidden = read_tree(PILOT.parent / scenario_name(STAGE_RUNS_ARM) / "hidden")
    assert hidden == read_tree(PILOT.parent / NAME / "hidden")
    kinds = {item.intent: item.kind for item in variant.sidecar.patch_inventory}
    assert sorted(kinds.values()) == ["incomplete", "incomplete", "reference", "reference"]
