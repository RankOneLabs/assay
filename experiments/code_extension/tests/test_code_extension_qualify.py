"""The committed pilot qualifies from private checks and reproducible records."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from code_extension import diagnose, qualify
from code_extension.fixture import PILOT, SUBJECT_ID, load_fixture, materialize, read_tree
from code_extension.fixtures import load_scenario
from code_extension.settings import SMOKE_SUBJECT_IDS

from assay.canonical import digest_bytes
from assay.fixture_manifest import FixtureManifestV3
from assay.investigations.workflow_correctness import (
    GroupResult,
    WorkflowCorrectnessResult,
    workflow_tree_digest,
)

MANIFEST = PILOT / "qualification" / "manifest.json"
EVIDENCE = PILOT / "qualification" / "evidence"
DISPATCH = PILOT.parent / "dispatch-handler"


def _committed_manifest() -> FixtureManifestV3:
    return FixtureManifestV3.model_validate_json(MANIFEST.read_bytes())


def _docker_ready() -> bool:
    if shutil.which("docker") is None:
        return False
    return (
        subprocess.run(("docker", "info"), capture_output=True, check=False, timeout=30).returncode
        == 0
    )


def test_pilot_is_a_bounded_study_subject_and_private_assets_do_not_ship() -> None:
    fixture = load_fixture()
    assert SUBJECT_ID not in SMOKE_SUBJECT_IDS
    assert 40 <= len(fixture.repository) <= 200
    assert sum(len(text.encode()) for text in fixture.repository.values()) <= 1_000_000
    assert fixture.groups[0].restores
    for tree in (PILOT.parent).rglob("repository"):
        if not tree.is_dir():
            continue
        paths = [path.relative_to(tree).as_posix() for path in tree.rglob("*") if path.is_file()]
        assert not any(
            path.startswith("tests/hidden/")
            or path.startswith("hidden/")
            or path.startswith("patches/")
            or path.endswith(".patch")
            for path in paths
        )
    for group in fixture.groups[1:]:
        assert not set(group.files) & set(fixture.repository)


def test_committed_records_are_canonical_digest_bound_and_qualified() -> None:
    fixture = load_fixture()
    manifest = _committed_manifest()
    manifest.require_qualified()
    scenario = manifest.scenario(SUBJECT_ID)
    assert scenario is not None
    assert scenario.checkpoint_sha == "f3b3ffca43e43672ff2f58ab797d65c7532aaed8"
    assert scenario.arms[0].tree_digest == fixture.tree_digest
    arm = scenario.arms[0]
    for name, result in (
        ("baseline_passes", arm.qualification.baseline_passes),
        ("feature_fails", arm.qualification.feature_fails),
        ("reference_passes", arm.qualification.reference_passes),
    ):
        record, digest = qualify.read_evidence(EVIDENCE, arm.arm_id, name)
        assert result.evidence == digest
        assert record["outcome"] == result.outcome
        assert record["image_digest"] == manifest.observed_runtime_image_digest
    assert arm.qualification.feature_fails.outcome == "failed"
    assert arm.qualification.reference_passes.outcome == "passed"


def test_dispatch_committed_gate_evidence_is_content_addressed() -> None:
    fixture = load_scenario("dispatch-handler")
    manifest = FixtureManifestV3.model_validate_json(
        (DISPATCH / "qualification" / "manifest.json").read_bytes()
    )
    manifest.require_qualified()
    assert manifest.scenario(fixture.subject_id) is not None
    refs = fixture.sidecar.evidence.model_dump()
    for field, filename in (
        ("leak_scan", "leak-scan.json"),
        ("access_probe", "access-probe.json"),
        ("no_op", "no-op.json"),
        ("scripted_submission", "scripted-submission.json"),
        ("double_reproduction", "double-reproduction.json"),
    ):
        data = (DISPATCH / "qualification" / "gates" / filename).read_bytes()
        assert digest_bytes(data) == refs[field]
        assert data == qualify.canonical_json(json.loads(data)) + b"\n"
    no_op = json.loads((DISPATCH / "qualification" / "gates" / "no-op.json").read_bytes())
    assert {name: value["status"] for name, value in no_op["result"]["groups"].items()} == {
        "visible_regression": "passed",
        "hidden_regression": "passed",
        "new_behavior": "failed",
    }


@pytest.mark.asyncio
async def test_dispatch_full_gate_reproduces_committed_bytes() -> None:
    if not _docker_ready():
        if os.environ.get("ASSAY_REQUIRE_DOCKER"):
            pytest.fail("Docker is unavailable")
        pytest.skip("Docker is unavailable")
    image = "assay-code-extension:run-bfb5dd7d9189a983"
    if (
        subprocess.run(
            ("docker", "image", "inspect", image), capture_output=True, check=False, timeout=30
        ).returncode
        != 0
    ):
        if os.environ.get("ASSAY_REQUIRE_DOCKER"):
            pytest.fail("pinned Docker image is not provisioned")
        pytest.skip("pinned Docker image is not provisioned")
    manifest = FixtureManifestV3.model_validate_json(
        (DISPATCH / "qualification" / "manifest.json").read_bytes()
    )
    fresh = await qualify.qualify(
        image=image,
        routing_config=None,
        evidence_dir=DISPATCH / "qualification" / "evidence",
        fixture=load_scenario("dispatch-handler"),
        expected_manifest=manifest,
        verify_committed=True,
    )
    assert fresh == manifest


@pytest.mark.asyncio
async def test_scenario_controls_use_loaded_patches_with_custom_evidence_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = load_scenario("dispatch-handler")
    manifest = FixtureManifestV3.model_validate_json(
        (DISPATCH / "qualification" / "manifest.json").read_bytes()
    )

    class StopAfterNoOp:
        async def run(self, *, patch: str, **_kwargs: object) -> WorkflowCorrectnessResult:
            if patch:
                assert patch == fixture.arms[0].reference_patch
                raise RuntimeError("reference control reached")
            return WorkflowCorrectnessResult(
                "incorrect",
                (
                    GroupResult("visible_regression", "passed"),
                    GroupResult("hidden_regression", "passed"),
                    GroupResult("new_behavior", "failed", "nonzero_exit"),
                ),
                "group_failure",
            )

    monkeypatch.setattr(qualify, "make_runner", lambda _image: StopAfterNoOp())
    with pytest.raises(RuntimeError, match="reference control reached"):
        await qualify.run_scenario_gates(
            fixture,
            manifest,
            "image",
            tmp_path / "different-output-dir",
            verify=False,
        )


def test_assembly_refuses_a_dead_feature_group_and_image_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = load_fixture()
    manifest = _committed_manifest()
    copied = tmp_path / "evidence"
    shutil.copytree(EVIDENCE, copied)
    route = tmp_path / "routing.yaml"
    route.write_text("route: test\n")
    monkeypatch.setattr(
        qualify, "observed_image_digest", lambda _: manifest.observed_runtime_image_digest
    )
    assembled = qualify.assemble_manifest(fixture, copied, image="tag", routing_config=route)
    assert assembled.routing_config_digest == digest_bytes(route.read_bytes())
    record, _ = qualify.read_evidence(copied, "baseline", "feature_fails")
    record["outcome"] = "passed"
    groups = record["groups"]
    assert isinstance(groups, dict)
    groups["new_behavior"] = {"status": "passed", "cause": None}
    qualify.write_record(copied, "baseline", "feature_fails", record)
    with pytest.raises(ValueError, match="unqualified arm"):
        qualify.assemble_manifest(fixture, copied, image="tag", routing_config=route)
    monkeypatch.setattr(qualify, "observed_image_digest", lambda _: "sha256:" + "0" * 64)
    with pytest.raises(ValueError, match="image digest differs"):
        qualify.require_image(manifest, "tag")


def test_visible_reset_removes_candidate_edits_before_preflight(tmp_path: Path) -> None:
    fixture = load_fixture()
    materialize(tmp_path, fixture.repository)
    changed = next(iter(fixture.groups[0].files))
    (tmp_path / changed).write_text("candidate edit")
    addition = tmp_path / "tests/visible/added.test.ts"
    addition.write_text("invalid TypeScript")
    diagnose._reset_visible_tests(tmp_path, fixture)
    assert (tmp_path / changed).read_text() == fixture.repository[changed]
    assert not addition.exists()


def test_typecheck_replay_reports_first_errors_without_changing_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        diagnose,
        "_run",
        lambda *_: "src/domain/example.ts(4,5): error TS2322: bad assignment\n",
    )
    groups = {
        "visible_regression": {
            "status": "failed",
            "cause": "typecheck_nonzero_exit",
        }
    }
    before = json.dumps(groups, sort_keys=True)
    result = diagnose.diagnose_candidate(
        "image",
        load_fixture(),
        "",
        groups,
        scratch=tmp_path,
    )
    assert result == {
        "preflight_cause": "typecheck_nonzero_exit",
        "typecheck_errors": [
            {"file": "src/domain/example.ts", "code": "TS2322", "message": "bad assignment"},
        ],
    }
    assert json.dumps(groups, sort_keys=True) == before


@pytest.mark.asyncio
async def test_offline_image_reproduces_records_and_replay_keeps_verdicts(tmp_path: Path) -> None:
    if not _docker_ready():
        if os.environ.get("ASSAY_REQUIRE_DOCKER"):
            pytest.fail("Docker is unavailable")
        pytest.skip("Docker is unavailable")
    if (
        subprocess.run(
            ("docker", "image", "inspect", qualify.IMAGE_TAG),
            capture_output=True,
            check=False,
            timeout=30,
        ).returncode
        != 0
    ):
        pytest.skip("pinned Docker image is not provisioned")
    fixture = load_fixture()
    manifest = _committed_manifest()
    route = Path(
        os.environ.get(
            "ASSAY_EXTENSION_ROUTING_CONFIG",
            str(Path.home() / "codes/rol/smithers/routing_config.yaml"),
        )
    )
    if not route.is_file():
        pytest.skip("routing config for committed manifest is not provisioned")
    evidence = tmp_path / "evidence"
    fresh = await qualify.qualify(
        image=qualify.IMAGE_TAG,
        routing_config=route,
        evidence_dir=evidence,
        expected_manifest=manifest,
    )
    assert fresh == manifest
    for name in qualify.CHECKS:
        assert (evidence / "baseline" / f"{name}.json").read_bytes() == (
            EVIDENCE / "baseline" / f"{name}.json"
        ).read_bytes()
    negative = fixture.arms[0].negative_patches[0]
    candidate = tmp_path / "negative"
    materialize(candidate, fixture.repository, negative)
    result = await qualify.make_runner(manifest.observed_runtime_image_digest).run(
        baseline=fixture.repository,
        baseline_tree_digest=fixture.tree_digest,
        expected_tree_digest=workflow_tree_digest(read_tree(candidate)),
        patch=negative,
        groups=fixture.groups,
    )
    groups = {group.name: {"status": group.status, "cause": group.cause} for group in result.groups}
    assert groups["new_behavior"]["status"] == "failed"
    before = json.dumps(groups, sort_keys=True).encode()
    diagnosis = diagnose.diagnose_candidate(
        manifest.observed_runtime_image_digest,
        fixture,
        negative,
        groups,
        scratch=tmp_path,
        manifest=manifest,
    )
    assert "failing_tests" in diagnosis
    failures = diagnosis["failing_tests"]
    assert isinstance(failures, dict) and failures["new_behavior"]
    assert json.dumps(groups, sort_keys=True).encode() == before
