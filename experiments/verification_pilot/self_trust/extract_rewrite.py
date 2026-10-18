"""Cut rung L, Oakridge's #468 decision-layer rewrite, into a sandbox slice.

#468 (``c90404d5``) replaced the pure materialization layer
(``compiler/materialize-*``, ``select-*``, ``runtime/run-materialization``,
``domain/run-decisions``, ``domain/output-availability``) with the pure
``src/decision`` package, and rewired storage and runtime over it. The slice
keeps every file the commit touched whose import closure is pure at both ends
(no ``pg``, DBOS, ``hono``, Kysely or React), plus those closures. It writes
the parent's versions to ``raw/rewrite_repo/before`` and the commit's to
``raw/rewrite_repo/after``.

Three mechanical changes keep the slice self-contained, as for the pilot slice:

- the ``oakridge-core`` example definitions and prompts the code reads are
  copied into ``workflow-config/``, and their ``new URL(...)`` paths rewritten;
- ``tests/architecture.test.ts`` is left out: its rules name storage files
  outside the slice;
- ``package.json``, ``package-lock.json`` and ``tsconfig.json`` are the pilot
  slice's, which typecheck and test in the sandbox image without a database.

Run ``uv run python -m verification_pilot.self_trust.extract_rewrite --oakridge
~/codes/rol/oakridge`` from ``experiments/``.
"""

from __future__ import annotations

import argparse
import posixpath
import re
import shutil
import subprocess
from pathlib import Path

COMMIT = "c90404d5"
PREFIX = "oakridge-dbos/"
IMPURE = ("pg", "@dbos-inc", "hono", "kysely", "react")
LEFT_OUT = ("tests/architecture.test.ts",)
CONFIG = ("package.json", "package-lock.json", "tsconfig.json")
OUT = Path(__file__).resolve().parents[1] / "raw" / "rewrite_repo"
PILOT_SLICE = Path(__file__).resolve().parents[1] / "raw" / "refactor_repo"
_IMPORT = re.compile(r"""(?:import|export)\s+(?:type\s+)?(?:[^'";]*?\sfrom\s+)?['"]([^'"]+)['"]"""
                     r"""|import\(\s*['"]([^'"]+)['"]\s*\)""", re.S)
_DATA_URL = re.compile(r"""new URL\(([`"])((?:\.\./)+)oakridge-core/(examples|prompts)/""")


class Revision:
    def __init__(self, repo: Path, rev: str) -> None:
        self.repo, self.rev = repo, rev
        listing = self._git("ls-tree", "-r", "--name-only", rev)
        self.files = set(listing.splitlines())
        self._cache: dict[str, str] = {}

    def _git(self, *args: str) -> str:
        return subprocess.run(["git", "-C", str(self.repo), *args], capture_output=True,
                              text=True, check=True).stdout

    def read(self, path: str) -> str:
        if path not in self._cache:
            self._cache[path] = self._git("show", f"{self.rev}:{path}")
        return self._cache[path]

    def closure(self, start: list[str]) -> tuple[set[str], set[str]]:
        """Repository files reachable by relative imports, and every other specifier."""
        seen: set[str] = set()
        external: set[str] = set()
        todo = list(start)
        while todo:
            path = todo.pop()
            if path in seen:
                continue
            if path not in self.files:
                external.add(f"MISSING:{path}")
                continue
            seen.add(path)
            for match in _IMPORT.finditer(self.read(path)):
                spec = match.group(1) or match.group(2)
                if not spec.startswith("."):
                    external.add(spec)
                    continue
                base = posixpath.normpath(posixpath.join(posixpath.dirname(path), spec))
                stem = base[:-3] if base.endswith(".js") else base
                for candidate in (f"{stem}.ts", f"{stem}.tsx", f"{stem}/index.ts", base):
                    if candidate in self.files:
                        todo.append(candidate)
                        break
                else:
                    external.add(f"UNRESOLVED:{spec}")
        return seen, external

    def pure(self, path: str) -> bool:
        _, external = self.closure([path])
        return not any(spec.startswith((*IMPURE, "MISSING:", "UNRESOLVED:")) for spec in external)


def changed_files(repo: Path) -> list[tuple[str, str]]:
    listing = subprocess.run(["git", "-C", str(repo), "show", "--name-status", "--format=",
                              COMMIT], capture_output=True, text=True, check=True).stdout
    return [(line.split("\t")[0], line.split("\t")[1]) for line in listing.splitlines()
            if line and line.split("\t")[1].startswith((f"{PREFIX}src/", f"{PREFIX}tests/"))]


def _relocate(path: str, source: str) -> str:
    """Point ``oakridge-core`` data URLs at the slice's ``workflow-config``."""
    depth = path.count("/")

    def repl(match: re.Match[str]) -> str:
        quote, kind = match.group(1), match.group(3)
        folder = "definitions" if kind == "examples" else "prompts"
        return f"new URL({quote}{'../' * depth}workflow-config/{folder}/"

    return _DATA_URL.sub(repl, source)


def extract(oakridge: Path) -> dict[str, int]:
    before, after = Revision(oakridge, f"{COMMIT}^"), Revision(oakridge, COMMIT)
    seeds_before: list[str] = []
    seeds_after: list[str] = []
    for status, path in changed_files(oakridge):
        if status == "D" and before.pure(path):
            seeds_before.append(path)
        elif status == "A" and after.pure(path):
            seeds_after.append(path)
        elif status == "M" and before.pure(path) and after.pure(path):
            seeds_before.append(path)
            seeds_after.append(path)
    keep = before.closure(seeds_before)[0] | after.closure(seeds_after)[0]
    counts: dict[str, int] = {}
    if OUT.exists():
        shutil.rmtree(OUT)
    for name, revision in (("before", before), ("after", after)):
        root = OUT / name
        written = 0
        data_kinds: set[str] = set()
        for path in sorted(keep):
            relative = path.removeprefix(PREFIX)
            if path not in revision.files or relative in LEFT_OUT:
                continue
            source = revision.read(path)
            data_kinds.update(match.group(3) for match in _DATA_URL.finditer(source))
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(_relocate(relative, source), encoding="utf-8")
            written += 1
        for kind, folder in (("examples", "definitions"), ("prompts", "prompts")):
            if kind not in data_kinds:
                continue
            for path in sorted(revision.files):
                if path.startswith(f"oakridge-core/{kind}/"):
                    target = root / "workflow-config" / folder / path.removeprefix(
                        f"oakridge-core/{kind}/")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(revision.read(path), encoding="utf-8")
        for name_ in CONFIG:
            shutil.copy(PILOT_SLICE / name_, root / name_)
        counts[name] = written
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--oakridge", type=Path, required=True)
    args = parser.parse_args()
    print(extract(args.oakridge.expanduser()))


if __name__ == "__main__":
    main()
