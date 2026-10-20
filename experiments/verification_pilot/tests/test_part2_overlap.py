"""Deferred path-only Part 2 overlap check.

`DoseSite.symbol` names the caller treated at a site, not the delegated-to
anchor. `FixtureTask` has no anchor-symbol field, so this manifest supports
only path-level overlap. Enable this test when the 2b anchor paths are frozen.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from assay.fixture_manifest import FixtureManifestV2

SAMPLE_MANIFEST = (
    Path(__file__).resolve().parents[1] / "fixtures" / "pilot-edit" / "sample-fixture-manifest.json"
)
SAMPLE_ANCHOR_PATHS = frozenset({"src/part2/owner.ts"})


def _contains(prefixes: tuple[str, ...], path: str) -> bool:
    return any(path == prefix or path.startswith(prefix.rstrip("/") + "/") for prefix in prefixes)


def test_committed_sample_manifest_is_valid() -> None:
    manifest = FixtureManifestV2.model_validate(json.loads(SAMPLE_MANIFEST.read_text()))
    assert manifest.schema_version == "assay-fixture-manifest/0.2.0"
    assert manifest.included_paths and manifest.excluded_paths
    assert manifest.tasks[0].treatment_sites


@pytest.mark.skip(reason="deferred until the Part 2b anchor population is frozen")
def test_part2_anchor_paths_do_not_overlap_fixture_paths() -> None:
    manifest = FixtureManifestV2.model_validate(json.loads(SAMPLE_MANIFEST.read_text()))
    treated = {site.path for task in manifest.tasks for site in task.treatment_sites}
    for anchor in SAMPLE_ANCHOR_PATHS:
        assert not _contains(manifest.included_paths, anchor)
        assert _contains(manifest.excluded_paths, anchor)
        assert anchor not in treated
