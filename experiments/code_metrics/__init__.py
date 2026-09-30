"""Standard code-quality metrics for a change between two repository snapshots.

    measure(before, after) -> {metric: after - before, ...}

Snapshots map relative paths to file text; only ``.py`` files are measured.
Every number comes from an established tool under that tool's own definition,
keyed ``<tool>.<metric>`` so its provenance travels with it. This module only
runs the tools on both snapshots and subtracts, plus SonarQube-style
"new code" figures for the lines the change added. Nothing is executed.

| key | definition | tool |
|---|---|---|
| radon.sloc, radon.lloc | source / logical lines of code | radon raw |
| radon.cc | cyclomatic complexity (McCabe 1976), summed over functions | radon cc |
| radon.halstead_volume | Halstead volume, summed per file (Halstead 1977) | radon hal |
| radon.mi | Maintainability Index, mean over files present in both | radon mi |
| complexipy.cognitive | total cognitive complexity (SonarSource 2017) | complexipy |
| grimp.imports | direct module import dependencies; None without a package | grimp |
| ruff.violations | findings from ruff's default rule set | ruff |
| ruff.magic_values | magic-value comparisons (PLR2004) | ruff |
| mypy.errors | type errors with --check-untyped-defs | mypy |
| jscpd.clones, jscpd.duplicated_lines | clone pairs and duplicated lines | jscpd |
| new_lines | non-blank lines the change added (Sonar new_lines) | difflib |
| new_duplicated_lines | added lines inside a jscpd clone (Sonar) | jscpd |
| new_max_nesting_depth | deepest nesting in a function the change touched | lizard |

Clone thresholds default to jscpd's own (5 lines, 50 tokens). ``ruff_ignore``
drops rules a harness, not the author, is responsible for. jscpd runs through
``npx``, so Node must be on PATH.
"""

from __future__ import annotations

import hashlib
import json
import os
import statistics
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from difflib import SequenceMatcher
from importlib.metadata import version
from pathlib import Path, PurePosixPath
from typing import Any, NamedTuple

import grimp
import lizard  # type: ignore[import-untyped]
from complexipy import code_complexity
from radon.complexity import add_inner_blocks  # type: ignore[import-untyped]
from radon.metrics import h_visit, mi_visit  # type: ignore[import-untyped]
from radon.raw import analyze  # type: ignore[import-untyped]
from radon.visitors import ComplexityVisitor, Function  # type: ignore[import-untyped]

JSCPD = "jscpd@5.4.0"
DELTAS = (
    "radon.sloc",
    "radon.lloc",
    "radon.cc",
    "radon.halstead_volume",
    "radon.mi",
    "complexipy.cognitive",
    "grimp.imports",
    "ruff.violations",
    "ruff.magic_values",
    "mypy.errors",
    "jscpd.clones",
    "jscpd.duplicated_lines",
)
NEW_CODE = ("new_lines", "new_duplicated_lines", "new_max_nesting_depth")
METRICS = DELTAS + NEW_CODE

Snapshot = Mapping[str, str]


class _Config(NamedTuple):
    clone_min_lines: int
    clone_min_tokens: int
    ruff_ignore: tuple[str, ...]


def tool_versions() -> dict[str, str]:
    """Versions behind every number, for the run record."""
    pinned = ("radon", "complexipy", "lizard", "grimp", "ruff", "mypy")
    return {name: version(name) for name in pinned} | {"jscpd": JSCPD.split("@")[1]}


def measure(
    before: Snapshot,
    after: Snapshot,
    *,
    clone_min_lines: int = 5,
    clone_min_tokens: int = 50,
    ruff_ignore: tuple[str, ...] = (),
) -> dict[str, float | None]:
    """after - before for every repository metric, plus new-code metrics for the change."""
    config = _Config(clone_min_lines, clone_min_tokens, ruff_ignore)
    old, new = _snapshot(before, config), _snapshot(after, config)
    result: dict[str, float | None] = {}
    for key in DELTAS:
        if key == "radon.mi":
            shared = sorted(set(old["mi"]) & set(new["mi"]))
            result[key] = (
                round(statistics.fmean(new["mi"][p] - old["mi"][p] for p in shared), 3)
                if shared
                else 0.0
            )
        elif old[key] is None or new[key] is None:
            result[key] = None
        else:
            result[key] = round(new[key] - old[key], 3)
    added = _added_lines(before, after)
    result["new_lines"] = sum(len(lines) for lines in added.values())
    result["new_duplicated_lines"] = sum(
        len(lines & new["cloned_lines"].get(path, set())) for path, lines in added.items()
    )
    result["new_max_nesting_depth"] = max(
        (
            depth
            for path, start, end, depth in new["functions"]
            if any(start <= line <= end for line in added.get(path, ()))
        ),
        default=0,
    )
    return result


def _python(snapshot: Snapshot) -> dict[str, str]:
    return {path: text for path, text in snapshot.items() if path.endswith(".py")}


_CACHE: dict[tuple[str, _Config], dict[str, Any]] = {}


_EMPTY: dict[str, Any] = {
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
            raise ValueError(f"snapshot path must be relative and inside the repository: {path}")
    if not files:
        return _EMPTY
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
        raise RuntimeError(f"mypy failed: {completed.stderr.strip()}")
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


def _added_lines(before: Snapshot, after: Snapshot) -> dict[str, set[int]]:
    """1-based line numbers of non-blank lines in ``after`` that ``before`` lacks."""
    added: dict[str, set[int]] = {}
    for path, text in _python(after).items():
        new = text.splitlines()
        old = before.get(path, "").splitlines()
        lines: set[int] = set()
        for tag, _, _, start, end in SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
            if tag in ("insert", "replace"):
                lines.update(n + 1 for n in range(start, end) if new[n].strip())
        if lines:
            added[path] = lines
    return added
