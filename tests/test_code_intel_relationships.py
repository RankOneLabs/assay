"""The import half must agree exactly with the published metrics graph."""

from pathlib import Path

import pytest

from assay.code_intel.contract import CodeIntelSettings
from assay.code_intel.errors import Ok
from assay.code_intel.models import (
    AffectedModuleItem,
    CallEdgeItem,
    ImportEdgeItem,
    RelationshipIndexManifest,
    RelationshipsMode,
    ResolvedCall,
    UnresolvedCall,
)
from assay.code_intel.relationships import RelationshipsCodeIntel
from assay.code_metrics.propagation import analyze_propagation
from assay.code_metrics.typescript import extract_typescript_graph

FILES = {
    "src/core.ts": "export function value(): number { return 1; }\n",
    "src/api.ts": "import { value } from './core';\nexport const read = value;\n",
    "src/view.ts": "import type { Read } from './types';\n"
                   "import { read } from './api';\n"
                   "import { missing } from './missing';\n"
                   "export const rendered = read;\n",
    "src/types.ts": "export type Read = () => number;\n",
}
IMAGE = "sha256:" + "0" * 64


def _prepared(tmp_path: Path) -> tuple[RelationshipsCodeIntel, RelationshipIndexManifest]:
    provider = RelationshipsCodeIntel(
        CodeIntelSettings(mode=RelationshipsMode()), index_root=tmp_path
    )
    result = provider.prepare(FILES, image_digest=IMAGE, excluded_paths=frozenset())
    assert isinstance(result, Ok)
    assert isinstance(result.value, RelationshipIndexManifest)
    return provider, result.value


def test_import_query_has_exact_metrics_edges(tmp_path: Path) -> None:
    provider, manifest = _prepared(tmp_path)
    queried = [provider.query(manifest, "importers", path) for path in FILES]
    assert all(isinstance(result, Ok) for result in queried)
    pairs = {
        (item.importer, item.imported)
        for result in queried if isinstance(result, Ok)
        for item in result.value.items if isinstance(item, ImportEdgeItem)
    }
    graph = extract_typescript_graph(FILES).graph
    assert pairs == {(edge.importer, edge.imported) for edge in graph.edges}
    assert ("src/view.ts", "src/types.ts") in pairs
    assert any(dependency.module == "src/view.ts" and dependency.package == "src/missing"
               for dependency in graph.external_dependencies)
    assert all(item.start_line is None and item.end_line is None
               for result in queried if isinstance(result, Ok)
               for item in result.value.items)


def test_affected_set_reconciles_with_propagation_counts(tmp_path: Path) -> None:
    provider, manifest = _prepared(tmp_path)
    graph = extract_typescript_graph(FILES).graph
    report = analyze_propagation(graph)
    for visibility in report.module_visibility:
        queried = provider.query(manifest, "affected", visibility.module)
        assert isinstance(queried, Ok)
        paths = {item.module for item in queried.value.items
                 if isinstance(item, AffectedModuleItem)}
        assert visibility.module in paths
        assert len(paths) == visibility.reached_by
    assert {item.module for item in provider.query(
        manifest, "affected", "src/core.ts"
    ).value.items if isinstance(item, AffectedModuleItem)} == {
        "src/core.ts", "src/api.ts", "src/view.ts"
    }


def test_cross_file_caller_and_unresolved_shapes(tmp_path: Path) -> None:
    files = {
        "src/target.ts": "export function target(): number { return 7; }\n",
        "src/client.ts": (
            "import { target } from './target';\n"
            "export function run(): number {\n"
            "  const byAny:any = target;\n"
            "  const table = { go: target };\n"
            "  target();\n"
            "  byAny();\n"
            "  table['go']();\n"
            "  import('./target').then(m => m.target());\n"
            "  return 1;\n"
            "}\n"
        ),
    }
    provider = RelationshipsCodeIntel(
        CodeIntelSettings(mode=RelationshipsMode()), index_root=tmp_path
    )
    prepared = provider.prepare(files, image_digest=IMAGE, excluded_paths=frozenset())
    assert isinstance(prepared, Ok)
    result = provider.query(prepared.value, "callers_and_callees", "callers:target")
    assert isinstance(result, Ok)
    calls = [item for item in result.value.items if isinstance(item, CallEdgeItem)]
    assert {item.start_line for item in calls} == {5, 6, 7, 8}
    resolved = [item for item in calls if isinstance(item.resolution, ResolvedCall)]
    assert len(resolved) == 1
    assert resolved[0].file_path == "src/client.ts"
    assert resolved[0].target_path == "src/target.ts"
    assert resolved[0].caller == "run"
    assert resolved[0].raw_source_ref == "src/client.ts:5:5"
    assert resolved[0].repo_revision == prepared.value.repo_revision
    assert resolved[0].content_hash.startswith("sha256:")
    assert resolved[0].approximate_tokens > 0
    assert {item.resolution.reason for item in calls
            if isinstance(item.resolution, UnresolvedCall)} == {
                "dynamic import()", "string-keyed dispatch", "any-typed value"
            }
    assert result.value.supplied_tokens == sum(item.approximate_tokens for item in calls)
    capabilities = provider.capabilities()
    assert capabilities.query_kinds == ("callers_and_callees", "importers", "affected")
    assert {"dynamic import()", "string-keyed dispatch", "any-typed calls"}.issubset(
        capabilities.unresolvable_cases
    )
    assert any("static inference" in case and "not proof" in case
               for case in capabilities.unresolvable_cases)


def test_relationships_reuse_the_symbols_parse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from assay.code_intel import typescript_symbols

    original = typescript_symbols.Parser
    parsed: list[bytes] = []

    class CountingParser:
        def __init__(self, language: object) -> None:
            self.parser = original(language)

        def parse(self, source: bytes) -> object:
            parsed.append(source)
            return self.parser.parse(source)

    monkeypatch.setattr(typescript_symbols, "Parser", CountingParser)
    _prepared(tmp_path)
    assert len(parsed) == len(FILES)
