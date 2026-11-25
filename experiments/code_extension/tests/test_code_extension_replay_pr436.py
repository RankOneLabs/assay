"""The artifact-release replay fixture: committed shape, groups, task and held patches."""

from __future__ import annotations

import json

from code_extension.fixture import COLOCATED_VISIBLE, PILOT, read_tree
from code_extension.fixtures import load_scenario
from code_extension.replay_kbbl import relocate
from code_extension.replay_pr436 import (
    BUILD_ENTRY,
    DEV_FLOW,
    EDITABLE_TESTS,
    EXECUTOR,
    HIDDEN_TEST,
    NAME,
    PATCHES,
    PRODUCTION,
    REGRESSION_TESTS,
    START_SHA,
    SUBJECT_ID,
    manifest_scope,
)

from assay.canonical import canonical_json, digest_bytes
from assay.fixture_manifest import FixtureManifestV3
from assay.repository import validate_repository

ROOT = PILOT.parent / NAME


def test_start_tree_fits_the_repository_bounds() -> None:
    fixture = load_scenario(NAME)
    tree = validate_repository(fixture.repository)
    assert len(tree) <= 200 and sum(len(text.encode()) for text in tree.values()) <= 1_000_000
    assert BUILD_ENTRY in tree and DEV_FLOW in tree
    assert all(path.startswith(("oakridge-dbos/", "oakridge-core/", "src/")) or "/" not in path
               for path in tree)
    # The start is #417's parent: no wait after the executor ends, and a closed session
    # still fails a satisfied unit.
    assert "shouldAwaitArtifactRelease" not in tree[EXECUTOR]
    assert '"cancelled") return { kind: "cancelled"' in tree[PRODUCTION]


def test_build_entry_does_not_bundle_the_dbos_sdk() -> None:
    exports = [line for line in load_scenario(NAME).repository[BUILD_ENTRY].splitlines()
               if line.startswith("export")]
    assert exports and not any("/workflows/" in line or "/runtime/" in line for line in exports)


def test_groups() -> None:
    fixture = load_scenario(NAME)
    visible, regression, behavior = fixture.groups
    assert visible.restores and visible.name == "visible_regression"
    assert set(visible.files) == set(COLOCATED_VISIBLE[NAME].select(fixture.repository))
    assert not set(EDITABLE_TESTS) & set(visible.files)
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
    assert kinds == sorted(kind for kind, _ in PATCHES.values())
    assert [item.patch_name for item in fixture.sidecar.negative_expectations] == [
        "negative.patch", "wait-only.patch", "eager-wait.patch",
    ]
    for name in PATCHES:
        assert (ROOT / "patches" / name).read_text(encoding="utf-8")


def test_task_states_the_behaviour_without_the_mechanism() -> None:
    task = load_scenario(NAME).task
    assert "after its agent's session" in task and "required_output_missing" in task
    for hint in ("cancelled", "terminalFailure", "shouldAwaitArtifactRelease", "fence", "parked"):
        assert hint not in task


def test_manifest_scope_names_the_pin() -> None:
    fixture = load_scenario(NAME)
    scope = manifest_scope(SUBJECT_ID, fixture.repository)
    assert scope is not None and scope[0] == START_SHA
    assert BUILD_ENTRY not in scope[1] and DEV_FLOW in scope[1]
    assert manifest_scope("oakridge-kbbl-build-guard-replay", fixture.repository) is None


def test_qualified_manifest_binds_the_replay() -> None:
    fixture = load_scenario(NAME)
    records = ROOT / "qualification"
    manifest = FixtureManifestV3.model_validate_json((records / "manifest.json").read_bytes())
    manifest.require_qualified()
    scenario = manifest.scenario(fixture.subject_id)
    assert scenario is not None and scenario.checkpoint_sha == START_SHA
    assert scenario.excluded_paths == ()
    assert set(scenario.included_paths) == set(fixture.repository) - {BUILD_ENTRY}
    assert scenario.feature_request == fixture.task.splitlines()[0].removeprefix("# ")
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
