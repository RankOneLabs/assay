"""Relationship queries over the first-party import graph and indexed calls."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from pathlib import Path
from time import perf_counter

from assay.canonical import digest_bytes
from assay.code_intel.contract import CodeIntelSettings
from assay.code_intel.errors import CodeIntelError, Err, Ok, Result
from assay.code_intel.index import approximate_tokens, build_index
from assay.code_intel.models import (
    AffectedModuleItem,
    CallEdgeItem,
    CapabilityManifest,
    ImportEdgeItem,
    IndexManifest,
    PreloadedSummary,
    QueryResult,
    RelationshipIndexManifest,
    RelationshipQueryResult,
    RelationshipsMode,
)
from assay.code_intel.snapshot import index_cache_key
from assay.code_intel.symbols import SymbolsCodeIntel
from assay.code_metrics.cycles import analyze_cycles
from assay.code_metrics.models import (
    CycleReportV4,
    ImportEdgeV2,
    ModuleGraphV2,
    PropagationReportV4,
)
from assay.code_metrics.propagation import analyze_propagation
from assay.code_metrics.typescript import extract_typescript_graph


def _affected(graph: ModuleGraphV2, changed: str) -> tuple[str, ...]:
    """Enumerate importers of one module; propagation publishes counts only."""
    reverse: dict[str, list[str]] = defaultdict(list)
    for edge in graph.edges:
        reverse[edge.imported].append(edge.importer)
    reached = {changed}
    pending = [changed]
    while pending:
        for importer in reverse[pending.pop()]:
            if importer not in reached:
                reached.add(importer)
                pending.append(importer)
    return tuple(sorted(reached))


class RelationshipsCodeIntel(SymbolsCodeIntel):
    """Keep the symbols index and add metrics-backed and parse-backed relationships."""

    def __init__(self, settings: CodeIntelSettings, *, index_root: Path | None = None) -> None:
        super().__init__(settings, index_root=index_root)

    def prepare(
        self, snapshot_mapping: Mapping[str, str], *, image_digest: str,
        excluded_paths: frozenset[str],
    ) -> Result[IndexManifest]:
        started = perf_counter()
        try:
            visible = {path: source for path, source in snapshot_mapping.items()
                       if path not in excluded_paths}
            base = build_index(
                snapshot_mapping, image_digest=image_digest,
                excluded_paths=excluded_paths, index_root=self.index_root,
            )
            extraction = extract_typescript_graph(visible)
            graph: ModuleGraphV2 = extraction.graph
            cycles: CycleReportV4 = analyze_cycles(graph)
            propagation: PropagationReportV4 = analyze_propagation(graph)
            indexer_version = base.indexer_version.replace(
                "typescript-symbols/", "typescript-relationships/", 1
            )
            manifest = RelationshipIndexManifest(
                repo_revision=base.repo_revision,
                snapshot_digest=base.snapshot_digest,
                image_digest=base.image_digest,
                indexer_version=indexer_version,
                cache_key=index_cache_key(base.snapshot_digest, image_digest, indexer_version),
                indexed_paths=base.indexed_paths,
                items=base.items,
                definitions=base.definitions,
                references=base.references,
                structures=base.structures,
                tool_versions=base.tool_versions,
                build_time_ms=(perf_counter() - started) * 1000,
                graph=graph, cycles=cycles, propagation=propagation,
            )
            (self.index_root / f"{manifest.cache_key.removeprefix('sha256:')}.json").write_text(
                manifest.model_dump_json() + "\n", encoding="utf-8",
            )
            return Ok(manifest)
        except Exception as error:
            return Err(CodeIntelError(
                operation="prepare relationships", entity_id=image_digest,
                detail=str(error), cause="codeintel_index_failure",
            ))

    def capabilities(self) -> CapabilityManifest:
        return CapabilityManifest(
            mode=RelationshipsMode(), delivery=self.delivery,
            query_kinds=("callers_and_callees", "importers", "affected"),
            supports_summary=True,
            unresolvable_cases=(
                "dynamic import()", "string-keyed dispatch", "any-typed calls",
                "A graph edge is a static inference, not proof of runtime execution.",
            ),
        )

    def query(self, manifest: IndexManifest, query_kind: str, text: str) -> Result[QueryResult]:
        started = perf_counter()
        if not isinstance(manifest, RelationshipIndexManifest):
            return Err(CodeIntelError(
                operation="query relationships", entity_id=manifest.cache_key,
                detail="relationship index required", cause="codeintel_unsupported_query",
            ))
        needle = text.strip()
        if query_kind not in self.capabilities().query_kinds:
            return Err(CodeIntelError(
                operation="query relationships", entity_id=manifest.cache_key,
                detail=f"unsupported query kind: {query_kind}",
                cause="codeintel_unsupported_query",
            ))
        paths = {entry.module for entry in manifest.graph.modules}
        if query_kind != "callers_and_callees" and needle not in paths:
            return Err(CodeIntelError(
                operation="query relationships", entity_id=manifest.cache_key,
                detail=f"unknown module: {needle}", cause="codeintel_unsupported_query",
            ))
        results: list[ImportEdgeItem | CallEdgeItem | AffectedModuleItem] = []
        if query_kind == "importers":
            for edge in manifest.graph.edges:
                if edge.imported == needle:
                    results.append(self._import_item(manifest, edge, len(results)))
        elif query_kind == "affected":
            for module in _affected(manifest.graph, needle):
                results.append(self._affected_item(manifest, module, needle, len(results)))
        else:
            direction, _, symbol = needle.partition(":")
            if direction not in ("callers", "callees"):
                direction, symbol = "both", needle
            for call in manifest.call_edges:
                if ((direction in ("both", "callers") and call.callee == symbol)
                        or (direction in ("both", "callees") and call.caller == symbol)):
                    content = f"{call.caller} calls {call.callee}"
                    results.append(CallEdgeItem(
                        repo_revision=manifest.repo_revision,
                        file_path=call.file_path, start_line=call.start_line,
                        end_line=call.end_line, symbol=call.callee,
                        retrieval_method="typescript_call_edge", rank=len(results),
                        content_hash=digest_bytes(content.encode()),
                        approximate_tokens=approximate_tokens(content),
                        raw_source_ref=f"{call.file_path}:{call.start_line}:{call.end_line}",
                        content=content, caller=call.caller, callee=call.callee,
                        target_path=call.target_path, resolution=call.resolution,
                    ))
        result = RelationshipQueryResult(
            query_kind=query_kind, items=tuple(results),
            latency_ms=(perf_counter() - started) * 1000,
            supplied_tokens=sum(item.approximate_tokens for item in results),
            snippets=tuple(item.content or "" for item in results),
        )
        return Ok[QueryResult](result)

    @staticmethod
    def _import_item(
        manifest: RelationshipIndexManifest, edge: ImportEdgeV2, rank: int,
    ) -> ImportEdgeItem:
        content = f"{edge.importer} imports {edge.imported}"
        return ImportEdgeItem(
            repo_revision=manifest.repo_revision, file_path=edge.importer,
            retrieval_method="typescript_import_graph", rank=rank,
            content_hash=digest_bytes(content.encode()),
            approximate_tokens=approximate_tokens(content),
            raw_source_ref=edge.importer, content=content,
            importer=edge.importer, imported=edge.imported,
        )

    @staticmethod
    def _affected_item(
        manifest: RelationshipIndexManifest, module: str, changed: str, rank: int,
    ) -> AffectedModuleItem:
        content = f"{module} is affected by a change to {changed}"
        return AffectedModuleItem(
            repo_revision=manifest.repo_revision, file_path=module,
            retrieval_method="typescript_import_propagation", rank=rank,
            content_hash=digest_bytes(content.encode()),
            approximate_tokens=approximate_tokens(content),
            raw_source_ref=module, content=content,
            module=module, changed_module=changed,
        )

    def summarize(
        self, manifest: IndexManifest, *, token_budget: int = 512
    ) -> Result[PreloadedSummary | None]:
        return super().summarize(manifest, token_budget=token_budget)
