"""Metric analyzer runners and the bounded snapshot cache."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from collections import OrderedDict
from pathlib import Path, PurePosixPath
from typing import Any

import grimp
import lizard  # type: ignore[import-untyped]
from complexipy import code_complexity
from radon.complexity import add_inner_blocks  # type: ignore[import-untyped]
from radon.metrics import h_visit, mi_visit  # type: ignore[import-untyped]
from radon.raw import analyze  # type: ignore[import-untyped]
from radon.visitors import ComplexityVisitor, Function  # type: ignore[import-untyped]

from .errors import AnalyzerFailed, SnapshotPathError
from .models import DELTAS, Snapshot, _Config
from .pins import JSCPD

def _python(snapshot: Snapshot) -> dict[str, str]:
    return {path: text for path, text in snapshot.items() if path.endswith(".py")}


_CACHE: OrderedDict[tuple[str, _Config], dict[str, Any]] = OrderedDict()


def _empty() -> dict[str, Any]:
    return {
    **dict.fromkeys(DELTAS, 0),
    "grimp.imports": None,
    "mi": {},
    "cloned_lines": {},
        "functions": [],
    }


def _snapshot(snapshot: Snapshot, config: _Config) -> dict[str, Any]:
    files = _python(snapshot)
    for path in files:
        parts = PurePosixPath(path).parts
        if PurePosixPath(path).is_absolute() or ".." in parts or "\\" in path:
            raise SnapshotPathError(f"snapshot path must be relative and inside the repository: {path}")
    if not files:
        return _empty()
    digest = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    if (digest, config) not in _CACHE:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for path, text in files.items():
                (root / path).parent.mkdir(parents=True, exist_ok=True)
                (root / path).write_text(text, encoding="utf-8")
            _CACHE[(digest, config)] = {
                **_radon(files),
                "complexipy.cognitive": sum(code_complexity(t).complexity for t in files.values()),
                "grimp.imports": _imports(root),
                **_ruff(root, config.ruff_ignore),
                "mypy.errors": _mypy(root),
                **_jscpd(root, config),
                "functions": _functions(root),
            }
    _CACHE.move_to_end((digest, config))
    if len(_CACHE) > 8:
        _CACHE.popitem(last=False)
    return _CACHE[(digest, config)]


def _radon(files: dict[str, str]) -> dict[str, Any]:
    raw = [analyze(text) for text in files.values()]
    return {
        "radon.sloc": sum(module.sloc for module in raw),
        "radon.lloc": sum(module.lloc for module in raw),
        "radon.cc": sum(_cyclomatic(text) for text in files.values()),
        "radon.halstead_volume": sum(h_visit(t).total.volume for t in files.values()),
        "mi": {path: mi_visit(text, multi=True) for path, text in files.items()},
    }


def _cyclomatic(text: str) -> int:
    """Sum of per-function McCabe scores, as SonarQube's ``complexity`` aggregates them.

    Radon scores nested functions separately from their enclosing function, so
    closures and inner-class methods are expanded before summing.
    """
    blocks = add_inner_blocks(ComplexityVisitor.from_code(text).blocks)
    return sum(block.complexity for block in blocks if isinstance(block, Function))


def _imports(root: Path) -> int | None:
    """Direct import dependencies among the snapshot's packages and to anything outside."""
    base = root / "src" if (root / "src").is_dir() else root
    packages = sorted(p.parent.name for p in base.glob("*/__init__.py"))
    if not packages:
        return None
    sys.path.insert(0, str(base))
    try:
        graph = grimp.build_graph(*packages, include_external_packages=True, cache_dir=None)
    finally:
        sys.path.remove(str(base))
    return sum(len(graph.find_modules_directly_imported_by(module)) for module in graph.modules)


def _ruff(root: Path, ignore: tuple[str, ...]) -> dict[str, int]:
    ignored = ["--extend-ignore", ",".join(ignore)] if ignore else []
    completed = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--extend-select", "PLR2004",
         *ignored, "--output-format", "json", "--exit-zero", "."],
        cwd=root, capture_output=True, text=True, check=True,
    )  # fmt: skip
    codes = [finding["code"] for finding in json.loads(completed.stdout)]
    return {
        "ruff.violations": sum(code != "PLR2004" for code in codes),
        "ruff.magic_values": codes.count("PLR2004"),
    }


def _mypy(root: Path) -> int:
    base = root / "src" if (root / "src").is_dir() else root
    completed = subprocess.run(
        [sys.executable, "-m", "mypy", "--check-untyped-defs", "--explicit-package-bases",
         "--cache-dir", os.devnull, "--no-error-summary", "--hide-error-context", "."],
        cwd=root, env={**os.environ, "MYPYPATH": str(base)},
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    if completed.returncode not in (0, 1):
        raise AnalyzerFailed(f"mypy failed: {completed.stderr.strip()}")
    return sum(": error:" in line for line in completed.stdout.splitlines())


def _jscpd(root: Path, config: _Config) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as output:
        subprocess.run(
            ["npx", "--yes", JSCPD, "--silent", "--format", "python", "--reporters", "json",
             "--min-lines", str(config.clone_min_lines),
             "--min-tokens", str(config.clone_min_tokens),
             "--output", output, "."],
            cwd=root, capture_output=True, text=True, check=True,
        )  # fmt: skip
        report = json.loads((Path(output) / "jscpd-report.json").read_text())
    cloned: dict[str, set[int]] = {}
    for clone in report["duplicates"]:
        for side in (clone["firstFile"], clone["secondFile"]):
            path = Path(side["name"]).as_posix()
            cloned.setdefault(path, set()).update(range(side["start"], side["end"] + 1))
    total = report["statistics"]["total"]
    return {
        "jscpd.clones": total["clones"],
        "jscpd.duplicated_lines": total["duplicatedLines"],
        "cloned_lines": cloned,
    }


def _functions(root: Path) -> list[tuple[str, int, int, int]]:
    extensions = lizard.get_extensions(["nd"])
    return [
        (
            Path(info.filename).relative_to(root).as_posix(),
            function.start_line,
            function.end_line,
            function.max_nesting_depth,
        )
        for info in lizard.analyze([str(root)], exts=extensions)
        for function in info.function_list
    ]


