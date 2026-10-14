from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from assay.fixture_manifest import FixtureManifest
from assay.investigations.workflow_correctness import workflow_tree_digest
from assay.models import CellCoordinate
from workflow_edit.arms import ARM_IDS
from workflow_edit.shape import validate_worker_grid
from workflow_edit.smoke import (
    MAX_REPOSITORY_BYTES,
    MAX_REPOSITORY_FILES,
    SUBJECT_ID,
    fixture_files,
)

ROOT = Path(__file__).resolve().parents[3]


def test_manifest_matches_exported_schema() -> None:
    document = json.loads(
        (ROOT / "experiments/workflow_edit/fixtures/smoke/MANIFEST.json").read_text()
    )
    schema = json.loads((ROOT / "schemas/assay-fixture-manifest.schema.json").read_text())
    Draft202012Validator(schema).validate(document)
    assert FixtureManifest.model_validate(document).checkpoint_sha == (
        "f3b3ffca43e43672ff2f58ab797d65c7532aaed8"
    )
    assert document["observed_runtime_image_digest"].startswith("sha256:")


def test_pinned_slice_fits_repository_boundary() -> None:
    oakridge = Path("/home/steve/codes/rol/oakridge")
    if not (oakridge / ".git").exists():
        pytest.skip("pinned Oakridge source checkout is unavailable")
    files = fixture_files(oakridge)
    manifest = json.loads(
        (ROOT / "experiments/workflow_edit/fixtures/smoke/MANIFEST.json").read_text()
    )
    assert len(files) == 4
    assert len(files) < MAX_REPOSITORY_FILES
    assert sum(len(value.encode()) for value in files.values()) < MAX_REPOSITORY_BYTES
    assert workflow_tree_digest(files) == manifest["per_arm_tree_digests"]["mess-00"]


def test_smoke_subject_is_reserved_from_part_two_population() -> None:
    cells = [
        CellCoordinate(subject_id=SUBJECT_ID, arm_id=arm, worker_repeat=0,
                       realization_ref="sha256:" + "0" * 64)
        for arm in ARM_IDS
    ]
    with pytest.raises(ValueError, match="smoke subject"):
        validate_worker_grid(
            subject_ids=[SUBJECT_ID], arm_ids=ARM_IDS, cells=cells, worker_repeats=1
        )
