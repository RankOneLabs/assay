"""Every committed extension scenario stays bounded, private, and qualified."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from code_extension import qualify
from code_extension.fixture import (
    ADDED_SCENARIOS,
    CHECKPOINT_SHA,
    PILOT,
    SUBJECT_ID,
    load_committed_scenario,
    load_fixture,
    materialize,
    read_tree,
)
from code_extension.qualify import CHECKS, read_evidence
from code_extension.settings import SMOKE_SUBJECT_IDS

from assay.canonical import canonical_json, digest_bytes
from assay.fixture_manifest import FixtureManifestV3
from assay.investigations.workflow_correctness import workflow_tree_digest
from assay.repository import DEFAULT_MAX_REPOSITORY_BYTES, DEFAULT_MAX_REPOSITORY_FILES


@pytest.mark.parametrize("name", ("pilot", *ADDED_SCENARIOS))
def test_committed_scenario_has_private_checks_and_bounded_trees(name: str, tmp_path: Path) -> None:
    if name == "pilot":
        fixture = load_fixture()
        subject_id = SUBJECT_ID
        task = fixture.task
        groups = fixture.groups
        arms = ((fixture.repository, fixture.arms[0].reference_patch,
                 fixture.arms[0].negative_patches[0]),)
        root = PILOT
    else:
        committed = load_committed_scenario(name)
        subject_id = committed.subject_id
        task = committed.task
        groups = committed.groups
        arms = tuple(
            (arm.repository, arm.reference_patch, arm.negative_patch) for arm in committed.arms
        )
        root = PILOT.parent / name
    assert subject_id not in SMOKE_SUBJECT_IDS
    assert "bun test ./tests/visible" in task
    assert "tsc --noEmit -p tsconfig.json" in task
    assert "hidden" not in task.lower() and "reference" not in task.lower()
    assert groups[0].restores and all(group.files for group in groups)
    readme = (root / "README.md").read_text()
    assert CHECKPOINT_SHA in readme
    assert "Excluded" in readme and "Adaptations" in readme

    for index, (repository, reference, negative) in enumerate(arms):
        assert 1 <= len(repository) <= DEFAULT_MAX_REPOSITORY_FILES
        total_bytes = sum(len(source.encode()) for source in repository.values())
        assert total_bytes <= DEFAULT_MAX_REPOSITORY_BYTES
        assert not any(
            path.startswith(("tests/hidden/", "hidden/", "patches/"))
            or path.endswith(".patch")
            for path in repository
        )
        assert all(repository[path] == source for path, source in groups[0].files.items())
        assert all(not set(group.files) & set(repository) for group in groups[1:])
        assert {path: source for path, source in repository.items()
                if path.startswith("tests/visible/")} == groups[0].files
        for label, patch in (("reference", reference), ("negative", negative)):
            assert patch
            candidate = tmp_path / f"{index}-{label}"
            materialize(candidate, repository, patch)
            assert read_tree(candidate) != repository


@pytest.mark.parametrize("name", ADDED_SCENARIOS)
def test_added_scenario_qualification_records(name: str) -> None:
    fixture = load_committed_scenario(name)
    root = PILOT.parent / name
    group_names = {group.name for group in fixture.groups}
    tree_digests = {workflow_tree_digest(arm.repository) for arm in fixture.arms}
    assert len(tree_digests) == len(fixture.arms)
    group_digests = {
        group.name: digest_bytes(canonical_json(group.model_dump(mode="json")))
        for group in fixture.groups
    }
    for arm in fixture.arms:
        record = json.loads((root / "qualification" / f"{arm.arm_id}.json").read_text())
        assert record["subject_id"] == fixture.subject_id
        assert record["arm_id"] == arm.arm_id
        assert record["image_digest"].startswith("sha256:")
        assert record["tree_digest"] == workflow_tree_digest(arm.repository)
        assert record["group_digests"] == group_digests
        assert record["patch_digests"] == {
            "baseline": digest_bytes(b""),
            "reference": digest_bytes(arm.reference_patch.encode()),
            "negative": digest_bytes(arm.negative_patch.encode()),
        }
        assert record["baseline"]["groups"] == {
            "visible_regression": "passed",
            "hidden_regression": "passed",
            "new_behavior": "failed",
        }
        assert record["reference"]["groups"] == {group: "passed" for group in group_names}
        assert record["negative"]["groups"]["new_behavior"] == "failed"
        assert record["reference"]["verdict"] == "correct"


def test_stage_arms_share_every_file_outside_the_compiler() -> None:
    scenario = load_committed_scenario("stage-pass-through")
    assert tuple(arm.arm_id for arm in scenario.arms) == ADDED_SCENARIOS[
        "stage-pass-through"
    ].arm_ids
    common = {
        path: source
        for path, source in scenario.arms[0].repository.items()
        if not path.startswith("src/compiler/")
    }
    for arm in scenario.arms[1:]:
        assert {
            path: source
            for path, source in arm.repository.items()
            if not path.startswith("src/compiler/")
        } == common


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ADDED_SCENARIOS)
async def test_added_scenario_image_reproduces_qualification_records(
    name: str, tmp_path: Path
) -> None:
    if shutil.which("docker") is None or subprocess.run(
        ("docker", "info"), capture_output=True, check=False, timeout=30
    ).returncode != 0:
        if os.environ.get("ASSAY_REQUIRE_DOCKER"):
            pytest.fail("Docker is unavailable")
        pytest.skip("Docker is unavailable")
    if subprocess.run(
        ("docker", "image", "inspect", qualify.IMAGE_TAG),
        capture_output=True,
        check=False,
        timeout=30,
    ).returncode != 0:
        pytest.skip("pinned Docker image is not provisioned")

    scenario = load_committed_scenario(name)
    root = PILOT.parent / name
    manifest = FixtureManifestV3.model_validate_json(
        (root / "qualification" / "manifest.json").read_bytes()
    )
    image_digest = qualify.observed_image_digest(qualify.IMAGE_TAG)
    assert image_digest == manifest.observed_runtime_image_digest
    runner = qualify.make_runner(image_digest)
    for arm in scenario.arms:
        baseline_digest = workflow_tree_digest(arm.repository)
        baseline = await runner.run(
            baseline=arm.repository,
            baseline_tree_digest=baseline_digest,
            expected_tree_digest=baseline_digest,
            patch="",
            groups=scenario.groups,
        )
        patched = tmp_path / arm.arm_id
        materialize(patched, arm.repository, arm.reference_patch)
        reference = await runner.run(
            baseline=arm.repository,
            baseline_tree_digest=baseline_digest,
            expected_tree_digest=workflow_tree_digest(read_tree(patched)),
            patch=arm.reference_patch,
            groups=scenario.groups,
        )
        negative_tree = tmp_path / f"{arm.arm_id}-negative"
        materialize(negative_tree, arm.repository, arm.negative_patch)
        negative = await runner.run(
            baseline=arm.repository,
            baseline_tree_digest=baseline_digest,
            expected_tree_digest=workflow_tree_digest(read_tree(negative_tree)),
            patch=arm.negative_patch,
            groups=scenario.groups,
        )
        summary = json.loads((root / "qualification" / f"{arm.arm_id}.json").read_text())
        for label, result in (
            ("baseline", baseline),
            ("reference", reference),
            ("negative", negative),
        ):
            assert summary[label] == {
                "cause": result.cause,
                "groups": {group.name: group.status for group in result.groups},
                "verdict": result.verdict,
            }
        for check, result in (
            ("baseline_passes", baseline),
            ("feature_fails", baseline),
            ("reference_passes", reference),
        ):
            record, _ = read_evidence(root / "qualification" / "checks", arm.arm_id, check)
            assert record["image_digest"] == image_digest
            assert record["cause"] == result.cause
            assert record["groups"] == {
                group.name: {"status": group.status, "cause": group.cause}
                for group in result.groups
            }
            assert record["outcome"] == (
                "failed" if check == "feature_fails" else "passed"
            )
        statuses = {group.name: group.status for group in baseline.groups}
        assert statuses == {
            "visible_regression": "passed",
            "hidden_regression": "passed",
            "new_behavior": "failed",
        }
        assert baseline.cause == "group_failure"
        assert reference.verdict == "correct"
        assert all(group.status == "passed" for group in reference.groups)


@pytest.mark.parametrize("name", ADDED_SCENARIOS)
def test_added_manifest_binds_every_arm_and_check(name: str) -> None:
    fixture = load_committed_scenario(name)
    root = PILOT.parent / name
    manifest = FixtureManifestV3.model_validate_json(
        (root / "qualification" / "manifest.json").read_bytes()
    )
    manifest.require_qualified()
    scenario = manifest.scenario(fixture.subject_id)
    assert scenario is not None
    assert scenario.checkpoint_sha == CHECKPOINT_SHA
    assert manifest.arm_set.factor == ("code_shape" if name == "stage-pass-through" else "baseline")
    frozen_groups = {
        group.name: group.digest for group in (*scenario.visible_tests, *scenario.hidden_tests)
    }
    assert frozen_groups == {
        group.name: digest_bytes(canonical_json(group.model_dump(mode="json")))
        for group in fixture.groups
    }
    for arm in fixture.arms:
        realization = next(item for item in scenario.arms if item.arm_id == arm.arm_id)
        assert realization.tree_digest == workflow_tree_digest(arm.repository)
        assert realization.reference_patch == digest_bytes(arm.reference_patch.encode())
        assert realization.negative_patches == (digest_bytes(arm.negative_patch.encode()),)
        for check in CHECKS:
            record, digest = read_evidence(root / "qualification" / "checks", arm.arm_id, check)
            result = getattr(realization.qualification, check)
            assert result.evidence == digest
            assert record["subject_id"] == fixture.subject_id
            assert record["image_digest"] == manifest.observed_runtime_image_digest
            assert record["tree_digest"] == realization.tree_digest
            assert record["outcome"] == result.outcome
            expected_patch = arm.reference_patch if check == "reference_passes" else ""
            assert record["patch_digest"] == digest_bytes(expected_patch.encode())
