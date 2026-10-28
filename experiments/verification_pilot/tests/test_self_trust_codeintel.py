"""The real omission-owner trees remain searchable without hidden material."""

import subprocess
import tempfile
from pathlib import Path

import pytest

from assay.code_intel.delivery import CodeIntelDeliveryConfig
from assay.code_intel.errors import CodeIntelError, Err, Ok
from assay.code_intel.snapshot import check_omission_coverage, repo_revision
from assay.code_intel.symbols import SymbolsCodeIntel
from verification_pilot.self_trust.codeintel import prepare_delivery
from verification_pilot.self_trust.codeintel_fixtures import (
    NAMES,
    read_symbol_span_through_tool,
    scripted_symbol_session,
)
from verification_pilot.self_trust.ladder import RUNGS
from verification_pilot.self_trust.study import self_trust_subjects

# The read_file tool needs Python, not the historical fixture image. Match the
# Python base pinned in integrations/pier/Dockerfile so fresh CI hosts can pull it.
READ_TOOL_IMAGE = (
    "python:3.13-slim@sha256:9d2e5553305c7c7b0097999bb17187c69b921ccd6bc9d40e4bb5ebe652c00285"
)


@pytest.fixture(scope="module")
def read_tool_image() -> str:
    present = subprocess.run(
        ["docker", "image", "inspect", READ_TOOL_IMAGE],
        capture_output=True, text=True, timeout=30, check=False,
    )
    if present.returncode:
        pulled = subprocess.run(
            ["docker", "pull", READ_TOOL_IMAGE],
            capture_output=True, text=True, timeout=300, check=False,
        )
        assert pulled.returncode == 0, f"read-tool image pull failed:\n{pulled.stderr[-2000:]}"
    return READ_TOOL_IMAGE


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


@pytest.mark.parametrize("mode,delivery", [
    ("symbols", "tool"), ("symbols", "preloaded"),
    ("relationships", "tool"), ("relationships", "preloaded"),
])
def test_configured_delivery_uses_subject_snapshot_without_model_calls(
    tmp_path: Path, mode: str, delivery: str,
) -> None:
    subject = next(subject for subject in self_trust_subjects()
                   if subject.fixture == "refactor" and subject.own == "group_a"
                   and subject.remnant_owner == "group_a")
    config = CodeIntelDeliveryConfig.model_validate({
        "mode": {"kind": mode}, "delivery": {"kind": delivery},
        "repository_revision": repo_revision(subject.repository),
        "max_context_tokens": 512, "query_limit": 20,
        "provider_options": {}, "index_mount": "/codeintel-index",
        "index_agent_readable": delivery == "tool",
    })
    prepared = prepare_delivery(
        subject, config, image_digest="sha256:" + "1" * 64, index_root=tmp_path,
    )
    assert prepared.index_files is not None
    assert b'"repo_revision"' in prepared.index_files["index.json"]
    assert RUNGS["refactor"].hidden_test.encode() not in prepared.index_files["index.json"]
    if delivery == "tool":
        from assay.canonical import canonical_json
        from assay_pier_bridge.agent_loop import PILOT_TOOL_SCHEMAS
        from verification_pilot.self_trust.bridge import SelfTrustBridgeClient

        assert prepared.block is None
        assert prepared.tool is not None
        assert prepared.tool["function"]["name"] == "codeintel_query"
        tools_by_turn = SelfTrustBridgeClient._tools(prepared)
        assert tools_by_turn is not None
        for turn, tools in tools_by_turn.items():
            assert canonical_json(tools[:-1]) == canonical_json(PILOT_TOOL_SCHEMAS[turn])
            assert len(canonical_json(tools)) <= 16_384
    else:
        assert prepared.tool is None
        assert prepared.block is not None
        assert repo_revision(subject.repository) in prepared.block


def test_configured_baseline_has_no_delivery_surface(tmp_path: Path) -> None:
    subject = next(subject for subject in self_trust_subjects()
                   if subject.fixture == "refactor" and subject.own == "group_a")
    config = CodeIntelDeliveryConfig.model_validate({
        "mode": {"kind": "baseline"}, "delivery": {"kind": "preloaded"},
        "repository_revision": repo_revision(subject.repository),
        "max_context_tokens": 512, "query_limit": 20,
        "provider_options": {}, "index_mount": "/codeintel-index",
        "index_agent_readable": False,
    })
    prepared = prepare_delivery(
        subject, config, image_digest="sha256:" + "1" * 64, index_root=tmp_path,
    )
    assert prepared.block is None and prepared.tool is None and prepared.index_files is None


def test_stale_delivery_revision_stops_before_indexing(tmp_path: Path) -> None:
    subject = next(subject for subject in self_trust_subjects()
                   if subject.fixture == "refactor" and subject.own == "group_a")
    config = CodeIntelDeliveryConfig.model_validate({
        "mode": {"kind": "symbols"}, "delivery": {"kind": "tool"},
        "repository_revision": "sha256:" + "0" * 64,
        "max_context_tokens": 512, "query_limit": 20,
        "provider_options": {}, "index_mount": "/codeintel-index",
        "index_agent_readable": True,
    })
    with pytest.raises(ValueError, match="codeintel_stale_index"):
        prepare_delivery(subject, config, image_digest="sha256:" + "1" * 64,
                         index_root=tmp_path)


@pytest.mark.parametrize("name", NAMES)
def test_indexed_symbol_span_is_read_through_docker_tool(
    name: str, tmp_path: Path, read_tool_image: str,
) -> None:
    _, result, _ = scripted_symbol_session(name, index_root=tmp_path)
    runtime_root = Path(__file__).resolve().parents[3] / ".assay" / "code-intel" / "tests"
    runtime_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="span-read-", dir=runtime_root) as temporary:
        read_symbol_span_through_tool(name, result, work=Path(temporary), image=read_tool_image)
