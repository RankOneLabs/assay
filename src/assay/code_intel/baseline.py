"""The baseline configuration has no code-intelligence surface."""

from __future__ import annotations

from collections.abc import Mapping

from assay.code_intel.contract import CodeIntelContract, CodeIntelSettings, ToolDefinition
from assay.code_intel.errors import CodeIntelError, Err, Ok, Result
from assay.code_intel.models import (
    BaselineMode,
    CapabilityManifest,
    IndexManifest,
    PreloadedSummary,
    QueryResult,
    RelationshipsMode,
    SymbolsMode,
)
from assay.code_intel.snapshot import make_index_manifest


class BaselineCodeIntel:
    def prepare(
        self, snapshot_mapping: Mapping[str, str], *, image_digest: str,
        excluded_paths: frozenset[str],
    ) -> Result[IndexManifest]:
        return Ok(make_index_manifest(
            snapshot_mapping, image_digest=image_digest, indexer_version="baseline/0.1.0",
            excluded_paths=excluded_paths, indexed_paths=(),
        ))

    def capabilities(self) -> CapabilityManifest:
        return CapabilityManifest(
            mode=BaselineMode(), delivery=self.delivery,
            query_kinds=(), supports_summary=False,
        )

    def __init__(self, settings: CodeIntelSettings) -> None:
        self.delivery = settings.delivery

    def query(self, manifest: IndexManifest, query_kind: str, text: str) -> Result[QueryResult]:
        return Err(CodeIntelError(
            operation="query index", entity_id=manifest.cache_key,
            detail=f"baseline supports no query kind: {query_kind}",
            cause="codeintel_unsupported_query",
        ))

    def summarize(
        self, manifest: IndexManifest, *, token_budget: int = 512
    ) -> Result[PreloadedSummary | None]:
        return Ok(None)

    def tools(self) -> tuple[ToolDefinition, ...]:
        return ()

    def prompt_block(self) -> str | None:
        return None

    def prefix_block(self) -> tuple[dict[str, object], ...]:
        return ()

    def close(self) -> None:
        return None


def select_code_intel(settings: CodeIntelSettings) -> Result[CodeIntelContract]:
    if isinstance(settings.mode, BaselineMode):
        return Ok(BaselineCodeIntel(settings))
    if isinstance(settings.mode, SymbolsMode):
        from assay.code_intel.symbols import SymbolsCodeIntel

        return Ok(SymbolsCodeIntel(settings))
    if isinstance(settings.mode, RelationshipsMode):
        from assay.code_intel.relationships import RelationshipsCodeIntel

        return Ok(RelationshipsCodeIntel(settings))
    return Err(CodeIntelError(
        operation="select mode", entity_id=settings.mode.kind,
        detail="index implementation has not been installed",
        cause="codeintel_unsupported_query",
    ))
