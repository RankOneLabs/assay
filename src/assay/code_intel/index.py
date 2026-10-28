"""Host-side JSON index construction for one delivered TypeScript snapshot."""

from __future__ import annotations

from collections.abc import Mapping
from importlib.metadata import version
from pathlib import Path
from time import perf_counter

from assay.canonical import digest_bytes
from assay.code_intel.models import ContextItem, IndexManifest
from assay.code_intel.snapshot import make_index_manifest, repo_revision
from assay.code_intel.typescript_calls import CallCandidate
from assay.code_metrics.pins import (
    assert_pinned_tools,
    node_binary,
    typescript_tool_versions,
)

INDEXER_VERSION = "typescript-symbols/0.1.0"


def approximate_tokens(text: str) -> int:
    return (len(text.encode("utf-8")) + 3) // 4


def build_index(
    snapshot_mapping: Mapping[str, str], *, image_digest: str,
    excluded_paths: frozenset[str], index_root: Path,
    call_sink: list[CallCandidate] | None = None,
) -> IndexManifest:
    """Persist a JSON index under its version-sensitive snapshot cache key."""
    start = perf_counter()
    assert_pinned_tools()
    node_binary("depcruise")
    node_binary("tsc")
    from assay.code_intel.typescript_symbols import extract_typescript_symbols

    versions = {
        "tree-sitter": version("tree-sitter"),
        "tree-sitter-typescript": version("tree-sitter-typescript"),
        **typescript_tool_versions(),
    }
    indexer_version = INDEXER_VERSION + ";" + ";".join(
        f"{name}={resolved}" for name, resolved in sorted(versions.items())
    )
    visible = {path: text for path, text in snapshot_mapping.items()
               if path not in excluded_paths}
    revision = repo_revision(snapshot_mapping)
    extracted = extract_typescript_symbols(visible, include_calls=call_sink is not None)
    if call_sink is not None:
        call_sink.extend(extracted.calls)
    items: list[ContextItem] = []
    for definition in extracted.definitions:
        lines = visible[definition.file_path].splitlines()
        content = definition.signature or lines[definition.start_line - 1][:400]
        items.append(ContextItem(
            repo_revision=revision, file_path=definition.file_path,
            start_line=definition.start_line, end_line=definition.end_line,
            symbol=definition.name, retrieval_method="typescript_symbol_definition",
            rank=0, content_hash=digest_bytes(content.encode("utf-8")),
            approximate_tokens=approximate_tokens(content),
            raw_source_ref=f"{definition.file_path}:{definition.start_line}:{definition.end_line}",
            content=content,
        ))
    base = make_index_manifest(
        snapshot_mapping, image_digest=image_digest, indexer_version=indexer_version,
        excluded_paths=excluded_paths, indexed_paths=visible, items=items,
    )
    manifest = base.model_copy(update={
        "definitions": extracted.definitions,
        "references": extracted.references,
        "structures": extracted.structures,
        "tool_versions": versions,
        "build_time_ms": (perf_counter() - start) * 1000,
    })
    index_root.mkdir(parents=True, exist_ok=True)
    (index_root / f"{manifest.cache_key.removeprefix('sha256:')}.json").write_text(
        manifest.model_dump_json() + "\n", encoding="utf-8",
    )
    return manifest
