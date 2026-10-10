from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from assay.code_metrics import CodeMetricsConfig, cli_snapshot
from assay.code_metrics.cli_snapshot import snapshot_directory
from oakridge_history import run as runner_module
from oakridge_history.config import Ok
from oakridge_history.extract import archive_commit
from oakridge_history.git_resolve import resolve_commit
from oakridge_history.model import ComponentSpec, ImplementationRoot, ScopeSpec, SnapshotSpec
from oakridge_history.run import run_snapshot


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(("git", "-C", str(repo), *args), text=True).strip()


def test_archive_and_pruned_snapshot_leave_git_state_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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
    _git(repo, "update-ref", "refs/remotes/origin/main", sha)
    scope = ScopeSpec(("kbbl/core", "absent"),
                      ("tests", "__tests__", "__fixtures__", "*.test.ts", "**/tests/**"), ())
    resolved = resolve_commit(repo, SnapshotSpec("s", sha, None, None, "", ""), scope)
    assert isinstance(resolved, Ok)
    destination = tmp_path / "archive"
    extracted = archive_commit(repo, resolved.value, destination)
    assert isinstance(extracted, Ok)
    visited: list[Path] = []
    real_walk = os.walk

    def observed_walk(*args: object, **kwargs: object) -> object:
        for directory, directories, filenames in real_walk(*args, **kwargs):  # type: ignore[arg-type]
            visited.append(Path(directory).relative_to(destination))
            yield directory, directories, filenames

    monkeypatch.setattr(cli_snapshot.os, "walk", observed_walk)
    snapshot, _ = snapshot_directory(destination, exclude=scope.exclude_globs)
    assert snapshot == {"kbbl/core/live.ts": "export const x = 1;\n"}
    assert Path("kbbl/core/tests") not in visited
    assert Path("kbbl/core/__tests__") not in visited
    assert Path("kbbl/core/__fixtures__") not in visited
    assert _git(repo, "rev-parse", "HEAD") == sha
    assert _git(repo, "status", "--porcelain") == ""


def test_runner_writes_reports_only_after_valid_commit(tmp_path: Path) -> None:
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
    _git(repo, "update-ref", "refs/remotes/origin/main", sha)
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


def test_runner_containment_failure_writes_no_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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
    _git(repo, "update-ref", "refs/remotes/origin/main", sha)
    scope = ScopeSpec(
        ("kbbl/core", "missing"), (),
        (ImplementationRoot("missing/", "missing", "missing"),),
    )
    component = ComponentSpec("missing", ("missing/**",))
    report = SimpleNamespace(configuration=SimpleNamespace(unmatched_patterns=()))
    monkeypatch.setattr(runner_module, "analyze", lambda *_args, **_kwargs: report)
    output = tmp_path / "output"
    with pytest.raises(RuntimeError, match=r"s: containment guard: missing/\*\*: root missing/"):
        run_snapshot(repo, SnapshotSpec("s", sha, None, None, "", ""),
                     scope, CodeMetricsConfig(), (component,), output)
    assert not output.exists()
