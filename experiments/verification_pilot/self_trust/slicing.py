"""Cut a sandbox slice of Oakridge at one or two revisions.

A slice keeps the seed files and everything they reach by relative imports,
and refuses any that reach a package the sandbox image does not carry. It is
the general form of ``extract_rewrite.py``: that module cuts rung L, and this
one cuts the later fixtures (``fixtures.py``).

Run ``uv run python -m verification_pilot.self_trust.slicing --oakridge
~/codes/rol/oakridge --fixture NAME`` from ``experiments/``.
"""

from __future__ import annotations

import argparse
import shutil
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from verification_pilot.self_trust.extract_rewrite import Revision

RAW = Path(__file__).resolve().parents[1] / "raw"


@dataclass(frozen=True)
class Slice:
    """Which revision(s) of which package to cut, and where to write them."""

    out: str  # directory under ``raw/``
    package: str  # the Oakridge package prefix, stripped from every path
    revisions: dict[str, str]  # output folder -> git revision
    seeds: tuple[str, ...]  # package-relative paths; a seed absent at a revision is skipped
    packages: tuple[str, ...]  # bare specifiers the image provides
    config: dict[str, str]  # slice-root config files -> their contents


def cut(slice_: Slice, oakridge: Path, seeds: Iterable[str] | None = None) -> dict[str, int]:
    root = RAW / slice_.out
    counts: dict[str, int] = {}
    wanted = tuple(seeds if seeds is not None else slice_.seeds)
    for folder, rev in slice_.revisions.items():
        revision = Revision(oakridge, rev)
        start = [slice_.package + path for path in wanted
                 if slice_.package + path in revision.files]
        files, external = revision.closure(start)
        refused = sorted(spec for spec in external if not spec.startswith(slice_.packages))
        if refused:
            raise ValueError(f"{rev}: the slice reaches what the image lacks: {refused}")
        target = root / folder
        if target.exists():
            shutil.rmtree(target)
        for path in sorted(files):
            out = target / path.removeprefix(slice_.package)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(revision.read(path), encoding="utf-8")
        for name, content in slice_.config.items():
            (target / name).write_text(content, encoding="utf-8")
        counts[folder] = len(files)
    return counts


def main() -> None:
    from verification_pilot.self_trust.fixtures import SLICES

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--oakridge", type=Path, required=True)
    parser.add_argument("--fixture", choices=sorted(SLICES), required=True)
    args = parser.parse_args()
    print(cut(SLICES[args.fixture], args.oakridge.expanduser()))


if __name__ == "__main__":
    main()
