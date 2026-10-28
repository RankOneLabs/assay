"""Scripted, model-free symbol queries against the three omission-owner trees.

Run ``uv run python -m verification_pilot.self_trust.codeintel_fixtures`` from
``experiments/`` to refresh the durable pre-run leak report.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from assay.code_intel.contract import CodeIntelSettings
from assay.code_intel.errors import Err, Ok
from assay.code_intel.leak_scan import scan_pre_run
from assay.code_intel.models import IndexManifest, QueryResult, SymbolsMode
from assay.code_intel.snapshot import check_omission_coverage, hidden_paths, hidden_sources
from assay.code_intel.symbols import SymbolsCodeIntel
from verification_pilot.self_trust.ladder import RUNGS
from verification_pilot.self_trust.leaks import TERMS

RAW = Path(__file__).resolve().parents[1] / "raw" / "self_trust"
REPORT = RAW / "ledger" / "codeintel-leak-scan.json"
NAMES = ("resume146", "forge-move", "forge-rewrite")
SYMBOL = {
    "resume146": "createClaudeCodeRuntime",
    "forge-move": "observeFinalPullRequest",
    "forge-rewrite": "observeFinalPullRequest",
}
REFERENCE_PATHS = ("reference_solutions", "reference-solutions")

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


def read_symbol_span_through_tool(name: str, result: QueryResult, *, work: Path) -> None:
    """Exercise the normal read-file tool on the span returned by the index."""
    rung = RUNGS[name]
    image = json.loads(rung.logs.read_text(encoding="utf-8"))["image"]
    root = work / name
    workspace, cache = root / "workspace", root / "cache"
    workspace.mkdir(parents=True)
    cache.mkdir()
    for path, source in rung.subject_tree("group_a").items():
        target = workspace / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source, encoding="utf-8")
    item = result.items[0]
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
    finally:
        sandbox.close()


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
    main()
