"""Scripted, model-free symbol queries against the three omission-owner trees.

Run ``uv run python -m verification_pilot.self_trust.codeintel_fixtures`` from
``experiments/`` to refresh the durable pre-run leak report.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from assay.code_intel.contract import CodeIntelSettings
from assay.code_intel.errors import Err, Ok
from assay.code_intel.leak_scan import scan_pre_run
from assay.code_intel.models import (
    CallEdgeItem,
    IndexManifest,
    QueryResult,
    RelationshipsMode,
    ResolvedCall,
    SymbolsMode,
)
from assay.code_intel.relationships import RelationshipsCodeIntel
from assay.code_intel.snapshot import check_omission_coverage, hidden_paths, hidden_sources
from assay.code_intel.symbols import SymbolsCodeIntel
from verification_pilot.self_trust.ladder import RUNGS
from verification_pilot.self_trust.leaks import TERMS

RAW = Path(__file__).resolve().parents[1] / "raw" / "self_trust"
REPORT = RAW / "ledger" / "codeintel-leak-scan.json"
RELATIONSHIP_REPORT = RAW / "ledger" / "codeintel-relationships-leak-scan.json"
NAMES = ("resume146", "forge-move", "forge-rewrite")
SYMBOL = {
    "resume146": "createClaudeCodeRuntime",
    "forge-move": "observeFinalPullRequest",
    "forge-rewrite": "observeFinalPullRequest",
}
REFERENCE_PATHS = ("reference_solutions", "reference-solutions")


@dataclass(frozen=True)
class RelationshipFixture:
    hidden_test: str = "tests/hidden/omissions.test.ts"
    hidden_tests: str = (
        "import { privateReport } from '../../src/report';\n"
        "if (privateReport('guest') !== 'denied') throw new Error('access');\n"
    )
    omission_path: str = "src/access.ts"
    effect_path: str = "src/report.ts"

    def subject_tree(self) -> dict[str, str]:
        return {
            self.omission_path: (
                "export function canRead(role: string): boolean {\n"
                "  return true;\n"
                "}\n"
            ),
            self.effect_path: (
                "import { canRead } from './access';\n"
                "export function privateReport(role: string): string {\n"
                "  return canRead(role) ? 'private' : 'denied';\n"
                "}\n"
            ),
            self.hidden_test: self.hidden_tests,
        }


RELATIONSHIP_FIXTURE = RelationshipFixture()
RELATIONSHIP_IMAGE = (
    "python:3.13-slim@sha256:9d2e5553305c7c7b0097999bb17187c69b921ccd6bc9d40e4bb5ebe652c00285"
)

_BRIDGE_SRC = Path(__file__).resolve().parents[3] / "integrations" / "pier" / "src"
if str(_BRIDGE_SRC) not in sys.path:
    sys.path.insert(0, str(_BRIDGE_SRC))

from assay_pier_bridge.agent_loop import (  # noqa: E402
    MODEL_REQUEST_SECONDS,
    DockerToolSandbox,
    LoopBounds,
    _execute_tool,
)


def scripted_symbol_session(
    name: str, *, index_root: Path,
) -> tuple[IndexManifest, QueryResult, dict[str, Any]]:
    """Prepare before query; a prepare error stops the scripted session."""
    rung = RUNGS[name]
    image = json.loads(rung.logs.read_text(encoding="utf-8"))["image"]
    tree = rung.subject_tree("group_a")
    provider = SymbolsCodeIntel(CodeIntelSettings(mode=SymbolsMode()), index_root=index_root)
    prepared = provider.prepare(tree, image_digest=image, excluded_paths=hidden_paths(rung))
    if isinstance(prepared, Err):
        raise RuntimeError(f"{prepared.error.cause}: {prepared.error.detail}")
    manifest = prepared.value
    coverage = check_omission_coverage(manifest, rung.omission_paths.values())
    if isinstance(coverage, Err):
        raise RuntimeError(str(coverage.error))
    queried = provider.query(manifest, "symbol", SYMBOL[name])
    if isinstance(queried, Err) or not queried.value.items:
        raise RuntimeError(f"{name}: symbol query returned no definition")
    result = queried.value
    omission_path = next(iter(rung.omission_paths.values()))
    if result.items[0].file_path != omission_path:
        raise RuntimeError(f"{name}: symbol resolved outside {omission_path}")
    summarized = provider.summarize(manifest, token_budget=512)
    if not isinstance(summarized, Ok) or summarized.value is None:
        raise RuntimeError(f"{name}: summary missing")
    hits = scan_pre_run(
        manifest, summarized.value, (result,), TERMS, (*hidden_paths(rung), *REFERENCE_PATHS),
        hidden_sources(rung).values(),
    )
    entry: dict[str, Any] = {
        "fixture": name, "image_digest": image, "cache_key": manifest.cache_key,
        "indexed_files": len(manifest.indexed_paths),
        "definition_path": result.items[0].file_path,
        "definition_start_line": result.items[0].start_line,
        "definition_end_line": result.items[0].end_line,
        "build_time_ms": manifest.build_time_ms,
        "query_latency_ms": result.latency_ms,
        "query_kind": result.query_kind,
        "supplied_tokens": result.supplied_tokens,
        "model_calls": 0,
        "leak_hits": [hit.__dict__ for hit in hits],
    }
    return manifest, result, entry


def read_symbol_span_through_tool(
    name: str, result: QueryResult, *, work: Path, image: str | None = None,
) -> None:
    """Exercise the normal read-file tool on the span returned by the index."""
    rung = RUNGS[name]
    image = image or json.loads(rung.logs.read_text(encoding="utf-8"))["image"]
    root = work / name
    workspace, cache = root / "workspace", root / "cache"
    workspace.mkdir(parents=True)
    cache.mkdir()
    for path, source in rung.subject_tree("group_a").items():
        target = workspace / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source, encoding="utf-8")
    item = result.items[0]
    start_line = item.start_line or 1
    expected_line = rung.subject_tree("group_a")[item.file_path].splitlines()[start_line - 1]
    sandbox = DockerToolSandbox(
        workspace, cache, image, f"codeintel-{name}-{os.getpid()}"
    )
    try:
        output = _execute_tool(
            sandbox, "read_file", {
                "path": item.file_path, "start_line": item.start_line,
                "end_line": min(item.end_line or item.start_line or 1,
                                (item.start_line or 1) + 3),
            }, LoopBounds().max_tool_output_bytes, MODEL_REQUEST_SECONDS,
        )
        if not output.text.startswith("exit=0\n") or output.read_range is None:
            raise RuntimeError(f"{name}: read_file could not retrieve indexed span")
        if output.read_range[0] != item.start_line:
            raise RuntimeError(f"{name}: read_file returned a different span")
        if not output.text.removeprefix("exit=0\n").startswith(expected_line):
            raise RuntimeError(f"{name}: read_file returned different source content")
    finally:
        sandbox.close()


def scripted_relationship_session(
    *, index_root: Path, image: str = RELATIONSHIP_IMAGE,
) -> tuple[IndexManifest, QueryResult, dict[str, Any]]:
    """Find the call in the effect module before reading its raw source."""
    fixture = RELATIONSHIP_FIXTURE
    tree = fixture.subject_tree()
    provider = RelationshipsCodeIntel(
        CodeIntelSettings(mode=RelationshipsMode()), index_root=index_root
    )
    prepared = provider.prepare(
        tree, image_digest=image.rsplit("@", 1)[-1],
        excluded_paths=hidden_paths(fixture),
    )
    if isinstance(prepared, Err):
        raise RuntimeError(f"{prepared.error.cause}: {prepared.error.detail}")
    manifest = prepared.value
    coverage = check_omission_coverage(manifest, (fixture.omission_path,))
    if isinstance(coverage, Err):
        raise RuntimeError(str(coverage.error))
    queried = provider.query(manifest, "callers_and_callees", "callers:canRead")
    if isinstance(queried, Err):
        raise RuntimeError(str(queried.error))
    result = queried.value
    matches = [item for item in result.items if isinstance(item, CallEdgeItem)
               and isinstance(item.resolution, ResolvedCall)]
    if len(matches) != 1 or matches[0].file_path != fixture.effect_path:
        raise RuntimeError("cross-file caller was not found in the effect module")
    summarized = provider.summarize(manifest, token_budget=512)
    if not isinstance(summarized, Ok) or summarized.value is None:
        raise RuntimeError("relationship summary missing")
    imported = provider.query(manifest, "importers", fixture.omission_path)
    affected = provider.query(manifest, "affected", fixture.omission_path)
    if not isinstance(imported, Ok) or not isinstance(affected, Ok):
        raise RuntimeError("relationship sample queries failed")
    hits = scan_pre_run(
        manifest, summarized.value, (result, imported.value, affected.value),
        TERMS, (*hidden_paths(fixture), *REFERENCE_PATHS),
        hidden_sources(fixture).values(),
    )
    entry: dict[str, Any] = {
        "fixture": "cross-file-caller", "omission_module": fixture.omission_path,
        "effect_module": fixture.effect_path, "caller_module": matches[0].file_path,
        "caller_line": matches[0].start_line,
        "query_latency_ms": result.latency_ms,
        "supplied_tokens": result.supplied_tokens,
        "build_time_ms": manifest.build_time_ms,
        "model_calls": 0, "leak_hits": [hit.__dict__ for hit in hits],
        "cache_key": manifest.cache_key,
    }
    return manifest, result, entry


def read_relationship_span_through_tool(
    result: QueryResult, *, work: Path, image: str = RELATIONSHIP_IMAGE,
) -> None:
    """Use the same Docker read_file path as a scripted fake-model session."""
    tree = RELATIONSHIP_FIXTURE.subject_tree()
    workspace, cache = work / "workspace", work / "cache"
    workspace.mkdir(parents=True)
    cache.mkdir()
    for path, source in tree.items():
        if path in hidden_paths(RELATIONSHIP_FIXTURE):
            continue
        target = workspace / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source, encoding="utf-8")
    item = result.items[0]
    sandbox = DockerToolSandbox(
        workspace, cache, image, f"codeintel-relationships-{os.getpid()}"
    )
    try:
        output = _execute_tool(
            sandbox, "read_file", {
                "path": item.file_path, "start_line": item.start_line,
                "end_line": item.end_line,
            }, LoopBounds().max_tool_output_bytes, MODEL_REQUEST_SECONDS,
        )
        if not output.text.startswith("exit=0\n") or output.read_range is None:
            raise RuntimeError("relationship caller span could not be read")
        if "canRead(role)" not in output.text:
            raise RuntimeError("relationship caller span returned different source")
    finally:
        sandbox.close()


def relationship_main() -> None:
    runtime_root = Path(__file__).resolve().parents[3] / ".assay" / "code-intel"
    manifest, result, entry = scripted_relationship_session(
        index_root=runtime_root / "indexes"
    )
    runtime_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="relationship-", dir=runtime_root) as temporary:
        read_relationship_span_through_tool(result, work=Path(temporary))
        entry["tool_read"] = "passed"
    RELATIONSHIP_REPORT.parent.mkdir(parents=True, exist_ok=True)
    RELATIONSHIP_REPORT.write_text(
        json.dumps(entry, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if entry["leak_hits"]:
        raise RuntimeError(f"relationship leak scan found hits; inspect {RELATIONSHIP_REPORT}")
    print(f"1 relationship index scanned, 0 leak hits -> {RELATIONSHIP_REPORT}")


def main() -> None:
    runtime_root = Path(__file__).resolve().parents[3] / ".assay" / "code-intel"
    index_root = runtime_root / "indexes"
    sessions = [scripted_symbol_session(name, index_root=index_root) for name in NAMES]
    runtime_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="session-", dir=runtime_root) as temporary:
        for name, (_, result, entry) in zip(NAMES, sessions, strict=True):
            read_symbol_span_through_tool(name, result, work=Path(temporary))
            entry["tool_read"] = "passed"
    entries = [entry for _, _, entry in sessions]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(entries, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if any(entry["leak_hits"] for entry in entries):
        raise RuntimeError(f"index leak scan found hits; inspect {REPORT}")
    print(f"{len(entries)} indexes scanned, 0 leak hits -> {REPORT}")


if __name__ == "__main__":
    if sys.argv[1:] == ["--relationships"]:
        relationship_main()
    else:
        main()
