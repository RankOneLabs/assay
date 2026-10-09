"""Extract only tracked paths from a verified commit, without changing Git state."""

from __future__ import annotations

import io
import subprocess
import tarfile
from pathlib import Path

from .config import Err, Ok
from .git_resolve import GitError, ResolvedCommit


def archive_commit(
    repo: Path, commit: ResolvedCommit, destination: Path
) -> Ok[Path] | Err[GitError]:
    if destination.exists():
        return Err(GitError(commit.snapshot.id, commit.sha, "archive destination already exists"))
    destination.mkdir(parents=True)
    if not commit.archived_include_paths:
        return Ok(destination)
    archived = subprocess.run(
        ("git", "-C", str(repo), "archive", "--format=tar", commit.sha,
         "--", *commit.archived_include_paths),
        capture_output=True, check=False,
    )
    if archived.returncode:
        detail = archived.stderr.decode(errors="replace")
        return Err(GitError(commit.snapshot.id, commit.sha, detail))
    with tarfile.open(fileobj=io.BytesIO(archived.stdout), mode="r:") as archive:
        archive.extractall(destination, filter="data")
    return Ok(destination)
