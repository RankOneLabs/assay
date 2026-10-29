"""Prepare and preflight the existing code-intelligence provider for one cell."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from assay.code_intel.baseline import BaselineCodeIntel
from assay.code_intel.contract import (
    CodeIntelContract,
    CodeIntelSettings,
    append_code_intel_tools,
)
from assay.code_intel.delivery import CodeIntelDeliveryConfig
from assay.code_intel.errors import Err
from assay.code_intel.leak_scan import scan_pre_run
from assay.code_intel.models import (
    BaselineMode,
    IndexManifest,
    PreloadedDelivery,
    PreloadedSummary,
    QueryResult,
    RelationshipsMode,
    ToolDelivery,
)
from assay.code_intel.relationships import RelationshipsCodeIntel
from assay.code_intel.snapshot import repo_revision
from assay.code_intel.symbols import SymbolsCodeIntel


@dataclass(frozen=True)
class PreparedExtensionCodeIntel:
    manifest: IndexManifest
    summary: PreloadedSummary | None
    query_results: tuple[QueryResult, ...]
    tools: list[dict[str, Any]]
    prompt_block: str | None
    index_files: dict[str, bytes] | None
    delivery: CodeIntelDeliveryConfig


def _query_tool(kind: str) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "codeintel_query",
            "description": "Query the mounted index for repository context.",
            "parameters": {
                "type": "object", "additionalProperties": False,
                "required": ["kind", "text"],
                "properties": {
                    "kind": {"type": "string", "enum": [kind]},
                    "text": {"type": "string"},
                },
            },
            "strict": True,
        },
    }


def _provider(config: CodeIntelDeliveryConfig, index_root: Path) -> CodeIntelContract:
    settings = CodeIntelSettings(mode=config.mode, delivery=config.delivery)
    if isinstance(config.mode, BaselineMode):
        return BaselineCodeIntel(settings)
    if isinstance(config.mode, RelationshipsMode):
        return RelationshipsCodeIntel(settings, index_root=index_root)
    return SymbolsCodeIntel(settings, index_root=index_root)


def prepare_extension_codeintel(
    *,
    snapshot: Mapping[str, str],
    hidden_paths: frozenset[str],
    hidden_source_texts: Sequence[str],
    term_patterns: Sequence[str],
    preflight_queries: Sequence[tuple[str, str]],
    image_digest: str,
    index_root: Path,
    config: CodeIntelDeliveryConfig,
    baseline_tools: Sequence[dict[str, Any]],
    provider: CodeIntelContract | None = None,
) -> PreparedExtensionCodeIntel:
    """Refuse every leak hit before a model or sandbox receives index bytes."""
    if repo_revision(snapshot) != config.repository_revision:
        raise ValueError("codeintel_stale_index: repository revision differs")
    selected = provider or _provider(config, index_root)
    try:
        prepared = selected.prepare(
            snapshot, image_digest=image_digest, excluded_paths=hidden_paths
        )
        if isinstance(prepared, Err):
            raise ValueError(f"{prepared.error.cause}: {prepared.error.detail}")
        manifest = prepared.value
        indexed_hidden = hidden_paths.intersection(manifest.indexed_paths)
        if indexed_hidden:
            raise ValueError(f"codeintel_hidden_path: {sorted(indexed_hidden)[0]}")
        summarized = selected.summarize(manifest, token_budget=config.max_context_tokens)
        if isinstance(summarized, Err):
            raise ValueError(f"{summarized.error.cause}: {summarized.error.detail}")
        summary = summarized.value
        query_plan = list(preflight_queries)
        if isinstance(config.mode, RelationshipsMode) and isinstance(
            config.delivery, PreloadedDelivery
        ) and not query_plan:
            query_plan = [
                (kind, path)
                for path in manifest.indexed_paths
                for kind in ("importers", "affected")
            ][:config.query_limit]
        results: list[QueryResult] = []
        for kind, text in query_plan:
            queried = selected.query(manifest, kind, text)
            if isinstance(queried, Err):
                raise ValueError(f"{queried.error.cause}: {queried.error.detail}")
            results.append(queried.value)
        hits = scan_pre_run(
            manifest, summary, results, term_patterns, hidden_paths, hidden_source_texts
        )
        if hits:
            hit = hits[0]
            raise ValueError(f"codeintel_leak: {hit.source}: {hit.term}: {hit.context}")
        extras: list[dict[str, Any]] = []
        if isinstance(config.delivery, ToolDelivery) and not isinstance(config.mode, BaselineMode):
            if isinstance(config.mode, RelationshipsMode):
                raise ValueError(
                    "codeintel_unsupported_query: relationships require preloaded delivery"
                )
            extras.append(_query_tool("symbol"))
        tools = append_code_intel_tools(baseline_tools, extras)
        block = None
        if isinstance(config.delivery, PreloadedDelivery) and summary is not None:
            parts = [f"Code intelligence for {manifest.repo_revision}:\n{summary.text}"]
            if isinstance(config.mode, RelationshipsMode):
                parts.extend(result.model_dump_json() for result in results)
            block = "\n".join(parts).encode("utf-8")[:4 * config.max_context_tokens].decode(
                "utf-8", errors="ignore"
            )
        files = None if isinstance(config.mode, BaselineMode) else {
            "index.json": manifest.model_dump_json().encode("utf-8")
        }
        return PreparedExtensionCodeIntel(
            manifest, summary, tuple(results), tools, block, files, config,
        )
    finally:
        selected.close()
