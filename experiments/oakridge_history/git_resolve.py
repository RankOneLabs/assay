"""Read-only Git transforms for a pinned Oakridge snapshot."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .config import Err, Ok
from .model import ScopeSpec, SnapshotSpec

HISTORY_REF = "origin/main"


@dataclass(frozen=True, slots=True)
class GitError:
    snapshot_id: str
    sha: str
    detail: str


@dataclass(frozen=True, slots=True)
class ResolvedCommit:
    snapshot: SnapshotSpec
    sha: str
    author_date: str
    subject: str
    first_parent: bool
    requested_include_paths: tuple[str, ...]
    archived_include_paths: tuple[str, ...]
    resolved_away_include_paths: tuple[str, ...]
    archive_files: tuple[str, ...]


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ("git", "-C", str(repo), *args), capture_output=True, text=True, check=False
    )


def resolve_commit(
    repo: Path, snapshot: SnapshotSpec, scope: ScopeSpec
) -> Ok[ResolvedCommit] | Err[GitError]:
    """Verify the commit and resolve each requested path against its tree."""
    verified = _git(repo, "rev-parse", "--verify", f"{snapshot.sha}^{{commit}}")
    if verified.returncode or verified.stdout.strip() != snapshot.sha:
        return Err(GitError(snapshot.id, snapshot.sha, "commit is missing or does not match pin"))
    detail = _git(repo, "show", "-s", "--format=%aI%n%s", snapshot.sha)
    if detail.returncode:
        return Err(GitError(snapshot.id, snapshot.sha, detail.stderr.strip()))
    author_date, subject = detail.stdout.splitlines()[:2]
    # Normalize to UTC so the record is independent of the author's offset.
    author_date = datetime.fromisoformat(author_date).astimezone(UTC).isoformat()
    # A fixed ref keeps the record independent of the checkout's current branch.
    first_parent_history = _git(repo, "rev-list", "--first-parent", HISTORY_REF)
    if first_parent_history.returncode:
        return Err(GitError(snapshot.id, snapshot.sha, first_parent_history.stderr.strip()))
    first_parent = snapshot.sha in first_parent_history.stdout.splitlines()
    archived: list[str] = []
    resolved_away: list[str] = []
    files: set[str] = set()
    for path in scope.include_paths:
        listed = _git(repo, "ls-tree", "-r", "--name-only", snapshot.sha, "--", path)
        if listed.returncode:
            return Err(GitError(snapshot.id, snapshot.sha, listed.stderr.strip()))
        matched = listed.stdout.splitlines()
        if matched:
            archived.append(path)
            files.update(matched)
        else:
            resolved_away.append(path)
    return Ok(ResolvedCommit(
        snapshot, snapshot.sha, author_date, subject, first_parent,
        scope.include_paths, tuple(archived), tuple(resolved_away), tuple(sorted(files)),
    ))
