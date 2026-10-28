"""The real omission-owner trees remain searchable without hidden material."""

import tempfile
from pathlib import Path

import pytest

from assay.code_intel.errors import CodeIntelError, Err, Ok
from assay.code_intel.snapshot import check_omission_coverage
from assay.code_intel.symbols import SymbolsCodeIntel
from verification_pilot.self_trust.codeintel_fixtures import (
    NAMES,
    read_symbol_span_through_tool,
    scripted_symbol_session,
)
from verification_pilot.self_trust.ladder import RUNGS


@pytest.mark.parametrize("name", NAMES)
def test_omission_module_is_indexed_without_leaks(name: str, tmp_path: Path) -> None:
    manifest, result, report = scripted_symbol_session(name, index_root=tmp_path)
    assert report["leak_hits"] == []
    assert isinstance(check_omission_coverage(
        manifest, RUNGS[name].omission_paths.values()
    ), Ok)
    item = result.items[0]
    assert item.file_path == next(iter(RUNGS[name].omission_paths.values()))
    assert item.start_line is not None and item.end_line is not None
    assert item.start_line <= item.end_line
    assert item.repo_revision == manifest.repo_revision
    assert item.approximate_tokens > 0
    assert item.content_hash.startswith("sha256:")
    assert report["image_digest"] == manifest.image_digest
    assert report["query_latency_ms"] >= 0
    assert report["supplied_tokens"] == result.supplied_tokens
    assert report["model_calls"] == 0
    truncated = manifest.model_copy(update={
        "indexed_paths": tuple(path for path in manifest.indexed_paths
                               if path != item.file_path),
    })
    assert isinstance(check_omission_coverage(
        truncated, RUNGS[name].omission_paths.values()
    ), Err)


def test_prepare_failure_stops_script_before_query(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*args: object, **kwargs: object) -> Err:
        return Err(CodeIntelError(
            operation="prepare index", entity_id="fixture", detail="grammar unavailable",
            cause="codeintel_index_failure",
        ))

    def queried(*args: object, **kwargs: object) -> None:
        raise AssertionError("query must not start")

    monkeypatch.setattr(SymbolsCodeIntel, "prepare", fail)
    monkeypatch.setattr(SymbolsCodeIntel, "query", queried)
    with pytest.raises(RuntimeError, match="codeintel_index_failure: grammar unavailable"):
        scripted_symbol_session("resume146", index_root=tmp_path)


@pytest.mark.parametrize("name", NAMES)
def test_indexed_symbol_span_is_read_through_docker_tool(name: str, tmp_path: Path) -> None:
    _, result, _ = scripted_symbol_session(name, index_root=tmp_path)
    runtime_root = Path(__file__).resolve().parents[3] / ".assay" / "code-intel" / "tests"
    runtime_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="span-read-", dir=runtime_root) as temporary:
        read_symbol_span_through_tool(name, result, work=Path(temporary))
