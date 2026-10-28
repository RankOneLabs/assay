"""The import half must agree exactly with the published metrics graph."""

from pathlib import Path

from assay.code_intel.contract import CodeIntelSettings
from assay.code_intel.errors import Ok
from assay.code_intel.models import (
    AffectedModuleItem,
    ImportEdgeItem,
    RelationshipIndexManifest,
    RelationshipsMode,
)
from assay.code_intel.relationships import RelationshipsCodeIntel
from assay.code_metrics.propagation import analyze_propagation
from assay.code_metrics.typescript import extract_typescript_graph

FILES = {
    "src/core.ts": "export function value(): number { return 1; }\n",
    "src/api.ts": "import { value } from './core';\nexport const read = value;\n",
    "src/view.ts": "import type { Read } from './types';\n"
                   "import { read } from './api';\nexport const rendered = read;\n",
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
