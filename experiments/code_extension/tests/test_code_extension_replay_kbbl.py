"""The kbbl Run-build replay fixture: committed shape, groups and held patches."""

from __future__ import annotations

import json

from code_extension.fixture import COLOCATED_VISIBLE, PILOT, read_tree
from code_extension.fixtures import load_scenario
from code_extension.replay_kbbl import (
    BUILD_ENTRY,
    EDITABLE_TESTS,
    HIDDEN_TEST,
    NAME,
    REGRESSION_TESTS,
    LIVE,
    START_SHA,
    SUBJECT_ID,
    TASK_EDIT,
    adapt_tsconfig,
    relocate,
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
    assert {"package.json", "tsconfig.json", "README.md", "kbbl/README.md"} <= set(tree)
    assert all(path.startswith(("kbbl/", "src/")) or "/" not in path for path in tree)


def test_visible_suite_is_kbbls_colocated_bun_tests() -> None:
    fixture = load_scenario(NAME)
    visible, regression, behavior = fixture.groups
    assert visible.restores and visible.name == "visible_regression"
    assert set(visible.files) == set(COLOCATED_VISIBLE[NAME].select(fixture.repository))
    assert not set(visible.files) & set(EDITABLE_TESTS)
    assert all(not path.startswith("kbbl/core/pwa/") for path in visible.files)
    assert all(path in fixture.repository for path in EDITABLE_TESTS)
    assert set(regression.files) == {"tests/hidden/regression/" + p for p in REGRESSION_TESTS}
    assert set(behavior.files) == {f"tests/hidden/new-behavior/{HIDDEN_TEST}"}


def test_held_patches_and_expectations() -> None:
    fixture = load_scenario(NAME)
    inventory = {item.intent: item.kind for item in fixture.sidecar.patch_inventory}
    assert sorted(inventory.values()) == ["incomplete", "incomplete", "reference", "reference",
                                          "reference"]
    assert [item.patch_name for item in fixture.sidecar.negative_expectations] == [
        "negative.patch", "manual-only.patch",
    ]
    assert len(fixture.arms[0].negative_patches) == 2


def test_relocated_regression_imports_resolve() -> None:
    tree = read_tree(ROOT / "repository")
    hidden = read_tree(ROOT / "hidden" / "regression")
    for path in REGRESSION_TESTS:
        moved = hidden["tests/hidden/regression/" + path]
        assert moved == relocate(tree[path], path, "tests/hidden/regression/" + path)
    source = 'import { a } from "./app";\nimport { b } from "../db/test-db";\n'
    moved = relocate(source, "kbbl/core/server/x.test.ts", "tests/hidden/regression/x.test.ts")
    assert '"../../../kbbl/core/server/app"' in moved
    assert '"../../../kbbl/core/db/test-db"' in moved


def test_tsconfig_adaptation() -> None:
    upstream = json.dumps({
        "compilerOptions": {"typeRoots": ["./node_modules/@types"], "strict": True},
        "include": ["kbbl/core/**/*.ts"], "exclude": ["node_modules"],
    })
    adapted = json.loads(adapt_tsconfig(upstream))
    assert "typeRoots" not in adapted["compilerOptions"]
    assert "kbbl/core/pwa/vitest.config.ts" in adapted["exclude"]
    committed = json.loads((ROOT / "repository" / "tsconfig.json").read_text())
    assert "typeRoots" not in committed["compilerOptions"]


def test_qualified_manifest_binds_the_replay() -> None:
    fixture = load_scenario(NAME)
    records = ROOT / "qualification"
    manifest = FixtureManifestV3.model_validate_json((records / "manifest.json").read_bytes())
    manifest.require_qualified()
    scenario = manifest.scenario(SUBJECT_ID)
    assert scenario is not None
    # Provenance names the replay's own Oakridge pin, not the pilot's.
    assert scenario.checkpoint_sha == START_SHA
    assert scenario.excluded_paths == ()
    assert set(scenario.included_paths) == set(fixture.repository) - {BUILD_ENTRY}
    assert scenario.dependency_lock_digests == {}
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
    assert set(arm.negative_patches) == {
        digest_bytes(patch.encode()) for patch in fixture.arms[0].negative_patches
    }
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


def test_task_offers_only_the_route_the_agent_missed() -> None:
    task = load_scenario(NAME).task
    assert "exclusively manual" not in task and TASK_EDIT[0] not in task
    assert task.count(LIVE) == 1
