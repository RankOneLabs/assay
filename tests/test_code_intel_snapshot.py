"""Snapshot and cache identity are specific to a subject tree."""

from assay.canonical import canonical_json, digest_bytes
from assay.code_intel.errors import Err, Ok
from assay.code_intel.snapshot import (
    check_omission_coverage,
    current_index,
    delivered_workspace,
    index_cache_key,
    make_index_manifest,
    repo_revision,
)

IMAGE = "sha256:" + "2" * 64


def test_subject_tree_identity_and_cache_key() -> None:
    a = {"src/a.ts": "one", "src/b.ts": "same"}
    b = {"src/a.ts": "two", "src/b.ts": "same"}
    assert repo_revision(a) == digest_bytes(canonical_json(a))
    assert repo_revision(a) != repo_revision(b)
    assert index_cache_key(repo_revision(a), IMAGE, "v1") != (
        index_cache_key(repo_revision(b), IMAGE, "v1")
    )
    package = {"instruction.md": "task", "workspace/src/a.ts": "one", "meta/x": "no"}
    assert delivered_workspace(package) == {"src/a.ts": "one"}


def test_stale_manifest_and_omission_coverage() -> None:
    tree = {"src/a.ts": "one", "src/b.ts": "same"}
    manifest = make_index_manifest(
        tree, image_digest=IMAGE, indexer_version="v1", excluded_paths=(),
        indexed_paths=tree,
    )
    assert isinstance(current_index(manifest, tree), Ok)
    stale = current_index(manifest, {**tree, "src/a.ts": "two"})
    assert isinstance(stale, Err)
    assert stale.error.cause == "codeintel_stale_index"
    assert isinstance(check_omission_coverage(manifest, tree), Ok)
    uncovered = check_omission_coverage(manifest, [*tree, "src/c.ts"])
    assert isinstance(uncovered, Err)
    assert uncovered.error.cause == "codeintel_omission_uncovered"
    assert "src/c.ts" in uncovered.error.detail
