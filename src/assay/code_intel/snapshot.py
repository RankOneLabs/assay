"""Snapshot identity, index freshness, and fixture-derived exclusions."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Protocol

from assay.canonical import canonical_json, digest_bytes
from assay.code_intel.errors import CodeIntelError, Err, Ok, Result
from assay.code_intel.models import ContextItem, IndexManifest


class HiddenFixture(Protocol):
    hidden_test: str
    hidden_tests: str


def delivered_workspace(package: Mapping[str, str]) -> dict[str, str]:
    """Mirror the bridge's ``workspace/`` stripping, excluding instruction.md."""
    return {
        path.removeprefix("workspace/"): content
        for path, content in package.items()
        if path.startswith("workspace/")
    }


def repo_revision(snapshot_mapping: Mapping[str, str]) -> str:
    """Identify the exact subject tree from Rung.start_tree/subject_tree."""
    return digest_bytes(canonical_json(dict(snapshot_mapping)))


def index_cache_key(snapshot_digest: str, image_digest: str, indexer_version: str) -> str:
    return digest_bytes(canonical_json({
        "snapshot_digest": snapshot_digest,
        "image_digest": image_digest,
        "indexer_version": indexer_version,
    }))


def hidden_paths(fixture: HiddenFixture) -> frozenset[str]:
    """Rung.hidden_test is the exclusion path; hidden_tests is its source text."""
    return frozenset((fixture.hidden_test,))


def hidden_sources(fixture: HiddenFixture) -> dict[str, str]:
    return {fixture.hidden_test: fixture.hidden_tests}


def make_index_manifest(
    snapshot_mapping: Mapping[str, str], *, image_digest: str, indexer_version: str,
    excluded_paths: Iterable[str], indexed_paths: Iterable[str],
    items: Iterable[ContextItem] = (),
) -> IndexManifest:
    revision = repo_revision(snapshot_mapping)
    excluded = frozenset(excluded_paths)
    visible = frozenset(snapshot_mapping) - excluded
    paths = tuple(sorted(frozenset(indexed_paths) & visible))
    kept_items = tuple(item for item in items if item.file_path in paths)
    return IndexManifest(
        repo_revision=revision, snapshot_digest=revision,
        image_digest=image_digest, indexer_version=indexer_version,
        cache_key=index_cache_key(revision, image_digest, indexer_version),
        indexed_paths=paths, items=kept_items,
    )


def current_index(
    manifest: IndexManifest, session_tree: Mapping[str, str]
) -> Result[IndexManifest]:
    actual = repo_revision(session_tree)
    if manifest.snapshot_digest != actual:
        return Err(CodeIntelError(
            operation="load index", entity_id=manifest.cache_key,
            detail=f"snapshot digest {manifest.snapshot_digest} differs from {actual}",
            cause="codeintel_stale_index",
        ))
    return Ok(manifest)


def check_omission_coverage(
    manifest: IndexManifest, omission_paths: Iterable[str]
) -> Result[None]:
    """A pure plan-time check against Rung.omission_paths values."""
    missing = sorted(set(omission_paths) - set(manifest.indexed_paths))
    if missing:
        return Err(CodeIntelError(
            operation="check omission coverage", entity_id=manifest.cache_key,
            detail=f"index does not cover: {', '.join(missing)}",
            cause="codeintel_omission_uncovered",
        ))
    return Ok(None)
