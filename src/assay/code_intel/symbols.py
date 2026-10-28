"""Host-side symbols provider for the code-intelligence contract."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from time import perf_counter

from assay.code_intel.contract import CodeIntelSettings, ToolDefinition
from assay.code_intel.errors import CodeIntelError, Err, Ok, Result
from assay.code_intel.index import approximate_tokens, build_index
from assay.code_intel.models import (
    CapabilityManifest,
    ContextItem,
    IndexManifest,
    PreloadedSummary,
    QueryResult,
    SymbolsMode,
)


class SymbolsCodeIntel:
    """One JSON index per snapshot, with deterministic symbol lookup and map."""

    def __init__(self, settings: CodeIntelSettings, *, index_root: Path | None = None) -> None:
        self.delivery = settings.delivery
        self.index_root = index_root or Path(
            os.environ.get("ASSAY_CODE_INTEL_INDEX_ROOT", ".assay/code-intel/indexes")
        )

    def prepare(
        self, snapshot_mapping: Mapping[str, str], *, image_digest: str,
        excluded_paths: frozenset[str],
    ) -> Result[IndexManifest]:
        try:
            return Ok(build_index(
                snapshot_mapping, image_digest=image_digest,
                excluded_paths=excluded_paths, index_root=self.index_root,
            ))
        except Exception as error:
            return Err(CodeIntelError(
                operation="prepare index", entity_id=image_digest,
                detail=str(error), cause="codeintel_index_failure",
            ))

    def capabilities(self) -> CapabilityManifest:
        return CapabilityManifest(
            mode=SymbolsMode(), delivery=self.delivery, query_kinds=("symbol",),
            supports_summary=True,
            unresolvable_cases=("dynamic import()", "string-keyed dispatch", "any-typed calls"),
        )

    def query(self, manifest: IndexManifest, query_kind: str, text: str) -> Result[QueryResult]:
        start = perf_counter()
        if query_kind != "symbol":
            return Err(CodeIntelError(
                operation="query index", entity_id=manifest.cache_key,
                detail=f"unsupported query kind: {query_kind}", cause="codeintel_unsupported_query",
            ))
        needle = text.strip().casefold()
        matches = [item for item in manifest.items
                   if item.symbol and needle and needle in item.symbol.casefold()]
        matches.sort(key=lambda item: (
            item.symbol.casefold() != needle if item.symbol else True,
            item.file_path, item.start_line or 0, item.symbol or "",
        ))
        ranked: tuple[ContextItem, ...] = tuple(
            item.model_copy(update={"rank": rank}) for rank, item in enumerate(matches[:20])
        )
        return Ok(QueryResult(
            query_kind=query_kind, items=ranked,
            latency_ms=(perf_counter() - start) * 1000,
            supplied_tokens=sum(item.approximate_tokens for item in ranked),
            snippets=tuple(item.content or "" for item in ranked),
        ))

    def summarize(
        self, manifest: IndexManifest, *, token_budget: int = 512
    ) -> Result[PreloadedSummary | None]:
        if token_budget < 0:
            return Err(CodeIntelError(
                operation="summarize index", entity_id=manifest.cache_key,
                detail="token budget must be nonnegative", cause="codeintel_unsupported_query",
            ))
        by_path: dict[str, list[str]] = {path: [] for path in manifest.indexed_paths}
        for definition in manifest.definitions:
            by_path[definition.file_path].append(definition.name)
        lines: list[str] = []
        used = 0
        for path, names in sorted(by_path.items()):
            line = path + (": " + ", ".join(dict.fromkeys(names[:8])) if names else "") + "\n"
            cost = approximate_tokens(line)
            if used + cost > token_budget:
                continue
            lines.append(line)
            used += cost
        return Ok(PreloadedSummary(repo_revision=manifest.repo_revision, text="".join(lines)))

    def tools(self) -> tuple[ToolDefinition, ...]:
        return ()

    def prompt_block(self) -> str | None:
        return None

    def prefix_block(self) -> tuple[dict[str, object], ...]:
        return ()

    def close(self) -> None:
        return None
