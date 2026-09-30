"""Write a codebase snapshot that the codebase DRY tasks are set in.

    uv run python experiments/consistency_pilot/snapshot_codebases.py <slice> <checkout> <commit>

Each slice is a part of one of our repositories plus the modules it imports,
copied byte for byte from one commit. Package ``__init__`` files that would
import the rest of the repository are left out;
``assay.investigations.codebase_fixtures`` adds empty ones in their place.
"""

from __future__ import annotations

import fnmatch
import json
import subprocess
import sys
from pathlib import Path

SNAPSHOTS = Path(__file__).resolve().parents[2] / "src/assay/investigations/snapshots"

# Slice -> (included patterns, excluded paths).
SLICES: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    # The LLM adapters and the three modules they import from elsewhere.
    "jig-llm": (
        (
            "src/jig/llm/*.py",
            "src/jig/core/errors.py",
            "src/jig/core/types.py",
            "src/jig/dispatch/client.py",
        ),
        (),
    ),
    # Graders, score persistence and the SQLite tracers.
    "jig-feedback": (
        (
            "src/jig/_embed.py",
            "src/jig/_sqlite.py",
            "src/jig/core/errors.py",
            "src/jig/core/grading.py",
            "src/jig/core/types.py",
            "src/jig/feedback/*.py",
            "src/jig/tracing/*.py",
        ),
        ("src/jig/feedback/__init__.py", "src/jig/tracing/__init__.py"),
    ),
    # scout's platform scanning adapters and the modules they import.
    "scout-platforms": (
        (
            "src/scout/config.py",
            "src/scout/errors.py",
            "src/scout/platforms/*.py",
            "src/scout/registry.py",
            "src/scout/resources.py",
            "src/scout/result.py",
            "src/scout/scanning/schemas.py",
        ),
        (),
    ),
}


def main(name: str, checkout: Path, commit: str) -> None:
    def git(*args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(checkout), *args], capture_output=True, text=True, check=True
        ).stdout

    patterns, excluded = SLICES[name]
    commit = git("rev-parse", "--verify", f"{commit}^{{commit}}").strip()
    tracked = git("ls-tree", "-r", "--name-only", commit).split()
    # A pattern's * stays within one directory.
    paths = sorted(
        path
        for path in tracked
        if path not in excluded
        and any(
            fnmatch.fnmatch(path, pattern) and path.count("/") == pattern.count("/")
            for pattern in patterns
        )
    )
    files = {path: git("show", f"{commit}:{path}") for path in paths}
    remote = git("config", "--get", "remote.origin.url").strip()
    snapshot = {"repository": remote, "commit": commit, "files": files}
    SNAPSHOTS.mkdir(exist_ok=True)
    (SNAPSHOTS / f"{name}.json").write_text(json.dumps(snapshot, indent=1, sort_keys=True) + "\n")
    print(f"{name}: {len(files)} files, {sum(map(len, files.values()))} bytes at {commit}")


if __name__ == "__main__":
    main(sys.argv[1], Path(sys.argv[2]).expanduser(), sys.argv[3])
