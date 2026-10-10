from __future__ import annotations

import subprocess
from pathlib import Path

from oakridge_history.config import Err, Ok
from oakridge_history.git_resolve import resolve_commit
from oakridge_history.model import ScopeSpec, SnapshotSpec


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(("git", "-C", str(repo), *args), text=True).strip()


def test_resolves_each_path_at_pinned_commit_without_touching_checkout(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.name", "Test")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "commit.gpgsign", "false")
    (tmp_path / "kbbl/core").mkdir(parents=True)
    (tmp_path / "kbbl/core/a.ts").write_text("export const a = 1;\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "first")
    sha = _git(tmp_path, "rev-parse", "HEAD")
    (tmp_path / "dbos").mkdir()
    (tmp_path / "dbos/b.ts").write_text("export const b = 2;\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "second")
    head = _git(tmp_path, "rev-parse", "HEAD")
    _git(tmp_path, "update-ref", "refs/remotes/origin/main", head)
    spec = SnapshotSpec("s1", sha, None, None, "first", "test")
    scope = ScopeSpec(("kbbl/core", "dbos"), (), ())
    result = resolve_commit(tmp_path, spec, scope)
    assert isinstance(result, Ok)
    assert result.value.sha == sha
    assert result.value.subject == "first"
    assert result.value.first_parent
    assert result.value.archived_include_paths == ("kbbl/core",)
    assert result.value.resolved_away_include_paths == ("dbos",)
    assert result.value.archive_files == ("kbbl/core/a.ts",)
    assert _git(tmp_path, "rev-parse", "HEAD") == head
    assert _git(tmp_path, "status", "--porcelain") == ""
    missing = resolve_commit(tmp_path, SnapshotSpec("bad", "0" * 40, None, None, "", ""), scope)
    assert isinstance(missing, Err)
    assert missing.error.snapshot_id == "bad"
    assert missing.error.sha == "0" * 40
