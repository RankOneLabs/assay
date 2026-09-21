"""The shipping framework must never import experiment packages."""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_ROOTS = {
    "consistency_pilot",
    "pier_qualification",
    "typesafe_relevance",
    "experiments",
}


def tracked_framework_files() -> tuple[PurePosixPath, ...]:
    output = subprocess.run(
        ["git", "ls-files", "-z", "src/assay"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    return tuple(
        PurePosixPath(item.decode())
        for item in output.split(b"\0")
        if item and item.endswith(b".py")
    )


def test_framework_does_not_import_experiments() -> None:
    violations: list[str] = []
    for path in tracked_framework_files():
        tree = ast.parse((ROOT / path).read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names: tuple[str, ...] = ()
            if isinstance(node, ast.Import):
                names = tuple(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = (node.module,)
            for name in names:
                if name.split(".", 1)[0] in FORBIDDEN_ROOTS:
                    violations.append(f"{path}:{node.lineno}: {name}")

    assert violations == []
