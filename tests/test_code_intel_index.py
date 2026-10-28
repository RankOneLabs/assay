"""The JSON index carries provenance and supports bounded lookup and maps."""

from pathlib import Path

import pytest

from assay.code_intel.contract import CodeIntelSettings
from assay.code_intel.errors import Err, Ok
from assay.code_intel.models import SymbolsMode
from assay.code_intel.symbols import SymbolsCodeIntel

IMAGE = "sha256:" + "2" * 64


def test_index_query_and_map(tmp_path: Path) -> None:
    provider = SymbolsCodeIntel(CodeIntelSettings(mode=SymbolsMode()), index_root=tmp_path)
    tree = {
        "src/a.ts": "export function greet(name: string): string { return name; }\n",
        "tests/hidden/omissions.test.ts": "export const secret = 1;\n",
    }
    built = provider.prepare(
        tree, image_digest=IMAGE,
        excluded_paths=frozenset({"tests/hidden/omissions.test.ts"}),
    )
    assert isinstance(built, Ok)
    manifest = built.value
    assert manifest.tool_versions["tree-sitter-typescript"] == "0.23.2"
    assert manifest.tool_versions["dependency-cruiser"] == "18.4.0"
    assert manifest.tool_versions["typescript"] == "6.0.3"
    assert manifest.build_time_ms >= 0
    assert "secret" not in manifest.model_dump_json()
    assert "omissions.test.ts" not in manifest.model_dump_json()
    assert (tmp_path / f"{manifest.cache_key.removeprefix('sha256:')}.json").is_file()
    result = provider.query(manifest, "symbol", "greet")
    assert isinstance(result, Ok)
    assert result.value.query_kind == "symbol"
    assert result.value.latency_ms >= 0
    assert result.value.supplied_tokens > 0
    assert result.value.snippets
    assert (result.value.items[0].file_path, result.value.items[0].start_line) == ("src/a.ts", 1)
    assert result.value.items[0].repo_revision == manifest.repo_revision
    assert result.value.items[0].content_hash.startswith("sha256:")
    assert result.value.items[0].retrieval_method == "typescript_symbol_definition"
    assert result.value.items[0].rank == 0
    first = provider.summarize(manifest, token_budget=40)
    second = provider.summarize(manifest, token_budget=40)
    assert isinstance(first, Ok) and isinstance(second, Ok)
    assert first.value is not None and second.value is not None
    assert first.value.model_dump_json() == second.value.model_dump_json()
    assert len(first.value.text.encode("utf-8")) <= 160
    capabilities = provider.capabilities()
    assert capabilities.query_kinds == ("symbol",)
    assert capabilities.supports_summary
    assert all(case in " ".join(capabilities.unresolvable_cases)
               for case in ("dynamic import()", "string-keyed dispatch", "any-typed calls"))
    assert isinstance(provider.query(manifest, "call", "greet"), Err)


def test_prepare_failure_stops_before_query(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = SymbolsCodeIntel(CodeIntelSettings(mode=SymbolsMode()), index_root=tmp_path)

    def fail(*args: object, **kwargs: object) -> None:
        raise RuntimeError("grammar missing")

    monkeypatch.setattr("assay.code_intel.symbols.build_index", fail)
    result = provider.prepare({"src/a.ts": "x"}, image_digest=IMAGE, excluded_paths=frozenset())
    assert isinstance(result, Err)
    assert result.error.cause == "codeintel_index_failure"
    assert "grammar missing" in result.error.detail
