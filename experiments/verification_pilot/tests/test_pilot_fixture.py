"""Pinned slice, remnant locations, decoys, and masking behavior."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from workflow_edit.arms import ARM_IDS
from workflow_edit.fixture import materialize, read_tree
from workflow_edit.shape import validate_worker_grid

from assay.investigations.workflow_correctness import workflow_tree_digest
from verification_pilot import PILOT_SUBJECT_IDS
from verification_pilot.fixture import (
    MAX_BYTES,
    MAX_FILES,
    OAKRIDGE_COMMIT,
    PILOT_EDIT,
    PINNED_TREE_DIGEST,
    SOURCE_TREE_COMMIT,
    load_fixture,
)
from verification_pilot.ground_truth import MASKING_TEST_PATH, build_specimens
from verification_pilot.migrations import GROUPS, MIGRATIONS


def test_pinned_tree_is_copied_bounded_and_digested() -> None:
    fixture = load_fixture()
    source = read_tree(
        PILOT_EDIT.parents[2] / "workflow_edit" / "fixtures" / "smoke-edit" / "repository"
    )
    assert fixture.repository == source
    assert len(source) == 62 <= MAX_FILES
    assert sum(len(text.encode()) for text in source.values()) == 348_936 <= MAX_BYTES
    assert workflow_tree_digest(source) == fixture.tree_digest == PINNED_TREE_DIGEST
    assert len(OAKRIDGE_COMMIT) == len(SOURCE_TREE_COMMIT) == 40


def test_ground_truth_names_every_remnant_and_decoy() -> None:
    trees, truth = build_specimens(load_fixture())
    by_name = {migration.name: migration for migration in MIGRATIONS}
    assert {remnant.kind for remnant in truth.remnants} == {
        "stale_type_reference",
        "stale_type_import",
        "fallback_object_key",
    }
    assert {decoy.kind for decoy in truth.decoys} == {
        "result_discriminant",
        "comment",
        "masking_test",
    }
    stale_type = next(r for r in truth.remnants if r.kind == "stale_type_reference")
    stale_location = stale_type.location
    stale_source = trees[stale_location.migration][stale_location.path]
    assert stale_source.splitlines()[stale_location.line - 1] == (
        "export type RunContext = { readonly [key: string]: JsonValue };"
    )
    assert "PilotJsonValue" in stale_source.splitlines()[5]
    for record in (*truth.remnants, *truth.decoys):
        location = record.location
        migration = by_name[location.migration]
        directory = str(Path(location.path).parent)
        directories = sorted({str(Path(site).parent) for site in migration.use_sites})
        assert directory in directories
        expected_group = GROUPS[(directories.index(directory) + migration.rotation) % len(GROUPS)]
        assert (
            location.symbol
            in trees[location.migration][location.path].splitlines()[location.line - 1]
        )
        assert location.ownership_group == expected_group


def test_masking_test_passes_with_unmigrated_key(tmp_path: Path) -> None:
    trees, truth = build_specimens(load_fixture())
    key_remnant = next(r for r in truth.remnants if r.kind == "fallback_object_key")
    repository = trees[key_remnant.location.migration]
    assert '["slot_bindings"]' in repository[key_remnant.location.path]
    materialize(tmp_path, repository)
    result = subprocess.run(
        ["bun", "test", f"./{MASKING_TEST_PATH}"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 pass" in result.stderr + result.stdout


def test_pilot_subject_is_refused_by_workflow_grid() -> None:
    for subject in PILOT_SUBJECT_IDS:
        with pytest.raises(ValueError, match="qualification smoke subject"):
            validate_worker_grid(
                subject_ids=(subject,),
                arm_ids=ARM_IDS,
                cells=(),
                worker_repeats=1,
            )
