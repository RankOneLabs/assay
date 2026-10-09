from __future__ import annotations

import hashlib
from types import SimpleNamespace

from assay.canonical import canonical_json
from oakridge_history.git_resolve import ResolvedCommit
from oakridge_history.metadata import build_metadata
from oakridge_history.model import ScopeSpec, SnapshotSpec


def test_metadata_records_resolved_inputs_and_environment() -> None:
    commit = ResolvedCommit(
        SnapshotSpec("s", "a" * 40, None, 7, "event", "reason"),
        "a" * 40, "2026-01-01T00:00:00+00:00", "subject", True,
        ("kbbl/core", "dbos"), ("kbbl/core",), ("dbos",), ("kbbl/core/a.ts",),
    )
    scope = ScopeSpec(("kbbl/core", "dbos"), ("tests",), ())
    language = SimpleNamespace(language="typescript", files_seen=1, files_analyzed=1,
                               modules_discovered=1, files_without_module=())
    report = SimpleNamespace(coverage=SimpleNamespace(languages=(language,)))
    metadata = build_metadata(commit, scope, ("tests", "node_modules"), report)  # type: ignore[arg-type]
    assert metadata["resolved_away_include_paths"] == ["dbos"]
    assert metadata["exclude_globs"] == ["tests"]
    assert metadata["resolved_exclusions"] == ["tests", "node_modules"]
    assert metadata["coverage"]["typescript"]["modules_discovered"] == 1
    assert metadata["archive_file_list_digest"] == hashlib.sha256(
        canonical_json(["kbbl/core/a.ts"])
    ).hexdigest()
    assert metadata["node_version"]
    assert metadata["npx_version"]
    assert metadata["dependency_cruiser_version"] == "18.4.0"
    assert len(metadata["uv_lock_digest"]) == 64
    assert len(metadata["assay_git_sha"]) == 40
