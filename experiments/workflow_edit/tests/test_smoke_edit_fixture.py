"""The committed smoke-edit fixture stays a real, bounded, self-consistent edit task."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from assay.investigations.workflow_correctness import (
    DockerWorkflowRunner,
    WorkflowRunnerSettings,
    workflow_tree_digest,
)
from workflow_edit import diagnose as diagnosis
from workflow_edit.fixture import (
    MAX_REPOSITORY_BYTES,
    MAX_REPOSITORY_FILES,
    SMOKE_EDIT,
    load_fixture,
    materialize,
    read_tree,
)
from workflow_edit.settings import SMOKE_SUBJECT_IDS
from workflow_edit.shape import validate_worker_grid

ROOT = Path(__file__).resolve().parents[3]
ORACLE_IMAGE = "sha256:a2848a705b2c638acde713ad68f45d13b337621a510131fcf93fda7c5b8762d1"
# Reserved for the Part 2 population (spec part 2, section 4).
PART2_ANCHORS = (
    "src/domain/output-release-policy.ts",
    "src/domain/workflow-recovery.ts",
    "src/decision/derive.ts",
)


def _patched_files(patch: str) -> set[str]:
    return set(re.findall(r"^diff --git a/(\S+) b/", patch, flags=re.MULTILINE))


def test_repository_is_within_the_authorized_package_limits() -> None:
    fixture = load_fixture()
    assert 40 <= len(fixture.repository) <= MAX_REPOSITORY_FILES
    assert sum(len(text.encode()) for text in fixture.repository.values()) <= MAX_REPOSITORY_BYTES


def test_dependency_manifests_are_the_runtime_image_locks() -> None:
    fixture = load_fixture()
    for name in ("package.json", "package-lock.json"):
        image_copy = (ROOT / "integrations/pier/workflow_edit" / name).read_text()
        assert fixture.repository[name] == image_copy


def test_patches_are_multi_file_production_edits_off_the_part2_anchors() -> None:
    fixture = load_fixture()
    for patch in (fixture.reference_patch, fixture.negative_patch):
        files = _patched_files(patch)
        assert len(files) >= 2 and all(path.startswith("src/") for path in files)
        assert not files & set(PART2_ANCHORS)
        assert files <= set(fixture.repository)


def test_frozen_groups_never_collide_with_the_repository() -> None:
    fixture = load_fixture()
    visible, hidden, new = fixture.groups
    assert visible.restores and visible.files
    assert all(fixture.repository[path] == text for path, text in visible.files.items())
    assert all(path.endswith(".test.ts") for path in visible.command[2:] if path.startswith("./"))
    for group in (hidden, new):
        assert not group.restores
        assert group.files and not set(group.files) & set(fixture.repository)


def test_task_names_the_checks_and_no_hidden_material() -> None:
    task = load_fixture().task
    assert "bun test ./tests/visible" in task and "tsc --noEmit -p tsconfig.json" in task
    assert "hidden" not in task.lower() and "reference" not in task.lower()


def test_smoke_subject_cannot_enter_a_study_grid() -> None:
    import pytest

    from workflow_edit.arms import ARM_IDS

    for subject in SMOKE_SUBJECT_IDS:
        with pytest.raises(ValueError, match="qualification smoke subject"):
            validate_worker_grid(
                subject_ids=(subject,), arm_ids=ARM_IDS, cells=(), worker_repeats=1
            )


def test_fixture_readme_records_provenance() -> None:
    readme = (SMOKE_EDIT / "README.md").read_text()
    assert "f3b3ffca43e43672ff2f58ab797d65c7532aaed8" in readme
    assert "Excluded" in readme and "Adaptations" in readme


@pytest.mark.parametrize(
    "cause",
    [
        "typecheck_timeout",
        "build_nonzero_exit",
        "build_output_missing",
    ],
)
def test_preflight_diagnosis_never_reports_failing_tests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cause: str
) -> None:
    def unexpected_run(*args: object, **kwargs: object) -> str:
        raise AssertionError("a preflight cause must not run test groups")

    monkeypatch.setattr(diagnosis, "_run", unexpected_run)
    groups = {
        name: {"status": "failed", "cause": cause}
        for name in ("visible_regression", "hidden_regression", "new_behavior")
    }
    assert diagnosis.diagnose_candidate("image", load_fixture(), "", groups, scratch=tmp_path) == {
        "preflight_cause": cause
    }


def test_empty_patch_materializes_the_baseline(tmp_path: Path) -> None:
    fixture = load_fixture()
    materialize(tmp_path / "candidate", fixture.repository, "")
    assert (tmp_path / "candidate" / "package.json").read_text() == fixture.repository[
        "package.json"
    ]


@pytest.mark.asyncio
async def test_docker_oracle_grades_frozen_smoke_patches(tmp_path: Path) -> None:
    if shutil.which("docker") is None:
        if os.environ.get("ASSAY_REQUIRE_DOCKER"):
            pytest.fail("ASSAY_REQUIRE_DOCKER is set but the docker CLI is not installed")
        pytest.skip("docker CLI is not installed")
    try:
        daemon = subprocess.run(
            ["docker", "info"], capture_output=True, text=True, timeout=30, check=False
        )
    except subprocess.TimeoutExpired:
        pytest.fail("docker info did not answer within 30 s")
    assert daemon.returncode == 0, f"docker daemon is not reachable: {daemon.stderr[-2000:]}"
    versions = (
        subprocess.run(
            ["docker", "version", "--format", "{{.Client.Version}} {{.Server.Version}}"],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        .stdout.strip()
        .split()
    )
    assert len(versions) == 2
    image = ORACLE_IMAGE
    if subprocess.run(
        ["docker", "image", "inspect", image], capture_output=True, check=False
    ).returncode:
        tag = "assay-workflow-edit:oracle"
        build = subprocess.run(
            ["docker", "build", "-t", tag, str(ROOT / "integrations" / "pier")],
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
        assert build.returncode == 0, f"oracle image build failed: {build.stderr[-2000:]}"
        image = subprocess.run(
            ["docker", "image", "inspect", "--format", "{{.Id}}", tag],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        ).stdout.strip()
    fixture = load_fixture()
    runner = DockerWorkflowRunner(
        WorkflowRunnerSettings(
            image=image,
            toolchain="bun",
            docker_client_version=versions[0],
            docker_server_version=versions[1],
            deadline_s=300,
        )
    )
    for label, patch, expected in (
        ("reference", fixture.reference_patch, "correct"),
        ("negative", fixture.negative_patch, "correct"),
        ("empty", "", "incorrect"),
    ):
        root = tmp_path / label
        materialize(root, fixture.repository, patch)
        result = await runner.run(
            baseline=fixture.repository,
            baseline_tree_digest=fixture.tree_digest,
            expected_tree_digest=workflow_tree_digest(read_tree(root)),
            patch=patch,
            groups=fixture.groups,
        )
        assert result.verdict == expected, (label, result)
        if label == "empty":
            assert [(g.name, g.status) for g in result.groups] == [
                ("visible_regression", "passed"),
                ("hidden_regression", "passed"),
                ("new_behavior", "failed"),
            ]
