"""The committed smoke-edit fixture stays a real, bounded, self-consistent edit task."""

from __future__ import annotations

import re
from pathlib import Path

from workflow_edit.fixture import (
    MAX_REPOSITORY_BYTES,
    MAX_REPOSITORY_FILES,
    SMOKE_EDIT,
    load_fixture,
)
from workflow_edit.settings import SMOKE_SUBJECT_IDS
from workflow_edit.shape import validate_worker_grid

ROOT = Path(__file__).resolve().parents[3]
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

    assert "oakridge-dbos-verification-pilot-edit" in SMOKE_SUBJECT_IDS
    for subject in SMOKE_SUBJECT_IDS:
        with pytest.raises(ValueError, match="qualification smoke subject"):
            validate_worker_grid(
                subject_ids=(subject,), arm_ids=ARM_IDS, cells=(), worker_repeats=1
            )


def test_fixture_readme_records_provenance() -> None:
    readme = (SMOKE_EDIT / "README.md").read_text()
    assert "f3b3ffca43e43672ff2f58ab797d65c7532aaed8" in readme
    assert "Excluded" in readme and "Adaptations" in readme
