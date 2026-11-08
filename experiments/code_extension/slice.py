"""Cut a scenario library start tree from oakridge at a pinned commit, without any model.

A slice spec names the pinned source files, where each lands in the fixture tree, and
the exact text replacements that relocation needs. Every replacement must match exactly
as often as declared, so a drifted source fails loudly instead of yielding a quietly
different tree. The dependency manifests are the image's own lock, renamed.

    uv run python -m code_extension.slice --scenario worker-silence-bound \
        --oakridge ~/codes/rol/oakridge
"""

from __future__ import annotations

import argparse
import json
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from code_extension.fixture import PILOT, read_tree

LIBRARY_PIN = "1495ec34d63a3147c60203ec7877cc2667212e93"
LOCK_DIRECTORY = Path(__file__).resolve().parents[2] / "integrations" / "pier" / "scenario_library"
TSCONFIG = {
    "compilerOptions": {
        "target": "ESNext",
        "module": "ESNext",
        "moduleResolution": "bundler",
        "strict": True,
        "noImplicitOverride": True,
        "noUnusedLocals": True,
        "noUnusedParameters": True,
        "esModuleInterop": True,
        "skipLibCheck": True,
        "resolveJsonModule": True,
        "allowJs": False,
        "allowImportingTsExtensions": True,
        "jsx": "react-jsx",
        "types": ["bun"],
        "lib": ["ESNext", "DOM"],
    },
}


@dataclass(frozen=True)
class Replacement:
    path: str  # destination path in the fixture tree
    old: str
    new: str
    count: int = 1


@dataclass(frozen=True)
class SliceSpec:
    package_name: str
    # source path at the pin -> destination path in the fixture tree
    files: Mapping[str, str]
    replacements: tuple[Replacement, ...] = ()
    # destination path -> complete authored content (small test helpers)
    authored: Mapping[str, str] = field(default_factory=dict)
    # what tsc checks; files read only as text by tests stay outside it
    typecheck_include: tuple[str, ...] = ("src/**/*.ts", "tests/**/*.ts")


def _show(oakridge: Path, pin: str, path: str) -> str:
    return subprocess.run(
        ["git", "-C", str(oakridge), "show", f"{pin}:{path}"],
        check=True, capture_output=True, text=True,
    ).stdout


def _manifests(package_name: str, include: tuple[str, ...]) -> dict[str, str]:
    package = json.loads((LOCK_DIRECTORY / "package.json").read_text())
    package["name"] = package_name
    lock = json.loads((LOCK_DIRECTORY / "package-lock.json").read_text())
    lock["name"] = package_name
    lock["packages"][""]["name"] = package_name
    return {
        "package.json": json.dumps(package, indent=2) + "\n",
        "package-lock.json": json.dumps(lock, indent=2) + "\n",
        "tsconfig.json": json.dumps({**TSCONFIG, "include": list(include)}, indent=2) + "\n",
    }


def cut(spec: SliceSpec, oakridge: Path, pin: str = LIBRARY_PIN) -> dict[str, str]:
    tree = {destination: _show(oakridge, pin, source) for source, destination in spec.files.items()}
    for replacement in spec.replacements:
        source = tree[replacement.path]
        found = source.count(replacement.old)
        if found != replacement.count:
            raise ValueError(
                f"{replacement.path}: expected {replacement.count} of {replacement.old!r}, "
                f"found {found}"
            )
        tree[replacement.path] = source.replace(replacement.old, replacement.new)
    generated = {"package.json", "package-lock.json", "tsconfig.json"}
    overlap = set(tree) & (set(spec.authored) | generated)
    if overlap:
        raise ValueError(f"authored paths collide with pinned sources: {sorted(overlap)}")
    return {**tree, **spec.authored, **_manifests(spec.package_name, spec.typecheck_include)}


HIDDEN_REGRESSION = "hidden/regression/"


def write(tree: Mapping[str, str], scenario: Path) -> None:
    """Ship everything under repository/, except pinned tests moved to the hidden group."""
    for name in sorted(tree):
        hidden = name.startswith(HIDDEN_REGRESSION)
        target = scenario / name if hidden else scenario / "repository" / name
        if target.exists():
            raise FileExistsError(f"{target} exists; remove the scenario's cut files to recut")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(tree[name], encoding="utf-8")
    read_tree(scenario / "repository")  # enforces the 200-file and 1,000,000-byte limits


def main() -> None:
    from code_extension.library import SLICES

    parser = argparse.ArgumentParser(prog="code_extension.slice")
    parser.add_argument("--scenario", required=True, choices=sorted(SLICES))
    parser.add_argument("--oakridge", type=Path, required=True)
    args = parser.parse_args()
    tree = cut(SLICES[args.scenario], args.oakridge.expanduser())
    write(tree, PILOT.parent / args.scenario)
    shipped = {k: v for k, v in tree.items() if not k.startswith(HIDDEN_REGRESSION)}
    print(f"{len(shipped)} files, {sum(len(v.encode()) for v in shipped.values())} bytes shipped;"
          f" {len(tree) - len(shipped)} pinned tests moved to the hidden group")


if __name__ == "__main__":
    main()
