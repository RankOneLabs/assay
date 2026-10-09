from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from assay.code_metrics import CodeMetricsConfig
from assay.code_metrics.cli_snapshot import snapshot_directory
from oakridge_history import metadata as metadata_module
from oakridge_history.config import Ok
from oakridge_history.extract import archive_commit
from oakridge_history.git_resolve import resolve_commit
from oakridge_history.model import ScopeSpec, SnapshotSpec
from oakridge_history.run import run_snapshot


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(("git", "-C", str(repo), *args), text=True).strip()


def test_archive_and_pruned_snapshot_leave_git_state_untouched(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "commit.gpgsign", "false")
    for name in ("live.ts", "live.test.ts", "tests/case.ts", "__tests__/case.ts",
                 "__fixtures__/sample.ts"):
        path = repo / "kbbl/core" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("export const x = 1;\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "test tree")
    sha = _git(repo, "rev-parse", "HEAD")
    scope = ScopeSpec(("kbbl/core", "absent"),
                      ("tests", "__tests__", "__fixtures__", "*.test.ts", "**/tests/**"), ())
    resolved = resolve_commit(repo, SnapshotSpec("s", sha, None, None, "", ""), scope)
    assert isinstance(resolved, Ok)
    destination = tmp_path / "archive"
    extracted = archive_commit(repo, resolved.value, destination)
    assert isinstance(extracted, Ok)
    snapshot, exclusions = snapshot_directory(destination, exclude=scope.exclude_globs)
    assert snapshot == {"kbbl/core/live.ts": "export const x = 1;\n"}
    assert "tests" in exclusions
    assert _git(repo, "rev-parse", "HEAD") == sha
    assert _git(repo, "status", "--porcelain") == ""


def test_runner_writes_reports_only_after_valid_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_version = metadata_module._version
    monkeypatch.setattr(
        metadata_module, "_version",
        lambda *command: (
            "v22.21.1" if command[0] == "node" else
            "10.9.4" if command[0] == "npx" else original_version(*command)
        ),
    )
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "commit.gpgsign", "false")
    (repo / "kbbl/core").mkdir(parents=True)
    (repo / "kbbl/core/README.txt").write_text("tracked\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "source")
    sha = _git(repo, "rev-parse", "HEAD")
    scope = ScopeSpec(("kbbl/core", "missing"), (), ())
    output = tmp_path / "output"
    with pytest.raises(RuntimeError, match="missing-snapshot 000000"):
        run_snapshot(repo, SnapshotSpec("missing-snapshot", "0" * 40, None, None,
                                        "", ""), scope, CodeMetricsConfig(), (), output)
    assert not output.exists()
    run_snapshot(repo, SnapshotSpec("s", sha, None, None, "", ""),
                 scope, CodeMetricsConfig(), (), output)
    target = output / "snapshots/s"
    assert (target / "code-metrics.json").is_file()
    assert (target / "metadata.json").is_file()
    metadata = json.loads((target / "metadata.json").read_bytes())
    assert metadata["resolved_away_include_paths"] == ["missing"]
    assert _git(repo, "status", "--porcelain") == ""
    assert _git(repo, "rev-parse", "HEAD") == sha
