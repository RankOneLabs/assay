"""Typecheck a TypeScript snapshot with its project's own locked toolchain.

By default ``typescript.type_errors`` comes from the analyzers' compiler
(``vendor/node-tools``) over a synthetic strict ``nodenext`` project with no
dependencies, so a tree that relies on its own compiler version, compiler
options, or installed types reports errors its own typecheck does not have.
A :class:`TypeScriptToolchain` names a directory where ``npm ci`` installed a
project's lockfile instead. The typecheck then runs that tree's ``tsc`` with the
snapshot's root ``tsconfig.json`` against those dependencies, the same
``tsc --noEmit -p tsconfig.json`` the project runs itself. Nothing is installed
or fetched at metric time.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .errors import (
    AnalyzerFailed,
    ConfigurationError,
    ToolVersionMismatch,
    TypeScriptDependenciesUnavailable,
)
from .pins import _user_node_tools, npm_ci

PROJECT = "tsconfig.json"
MANIFESTS = ("package.json", "package-lock.json")
# Options that make an import resolve somewhere dependency-cruiser, which
# resolves without the project file, would not look.
PATH_MAPPING_OPTIONS = ("baseUrl", "paths", "rootDirs")


@dataclass(frozen=True)
class TypeScriptToolchain:
    """A directory holding a project's ``package.json``, ``package-lock.json``,
    and the ``node_modules`` that ``npm ci`` installed from them."""

    dependencies: Path


@dataclass(frozen=True)
class ResolvedToolchain:
    """An installed tree checked against its lockfile, and the identity it records."""

    dependencies: Path
    tsc: str
    typescript: str
    lock_sha256: str

    def versions(self) -> dict[str, str]:
        """Entries for a report's ``versions.tools``: what typechecked the snapshot."""
        return {
            "typecheck-lock": f"sha256:{self.lock_sha256}",
            "typecheck-typescript": self.typescript,
        }


def lock_sha256(manifests: Path) -> str:
    try:
        return hashlib.sha256((manifests / "package-lock.json").read_bytes()).hexdigest()
    except OSError as error:
        raise TypeScriptDependenciesUnavailable(
            manifests, f"unreadable lockfile: {error}"
        ) from error


def dependencies_directory(manifests: Path) -> Path:
    """The per-user cache directory for a lockfile's installed tree, keyed by its digest."""
    return _user_node_tools().parent / "typescript-dependencies" / lock_sha256(manifests)[:16]


def install_typescript_dependencies(
    manifests: Path, target: Path | None = None, *, offline: bool = False
) -> Path:
    """Copy a project's manifests to *target* and ``npm ci`` them there, scripts disabled."""
    directory = dependencies_directory(manifests) if target is None else target
    try:
        directory.mkdir(parents=True, exist_ok=True)
        for name in MANIFESTS:
            if (manifests / name).resolve() != (directory / name).resolve():
                shutil.copyfile(manifests / name, directory / name)
    except OSError as error:
        raise TypeScriptDependenciesUnavailable(directory, f"cannot prepare: {error}") from error
    npm_ci(directory, offline=offline, include_dev=True)
    resolve_toolchain(TypeScriptToolchain(directory))
    return directory


def resolve_toolchain(toolchain: TypeScriptToolchain) -> ResolvedToolchain:
    """Check every locked package is installed at its locked version, and find ``tsc``."""
    # Absolute, because ``tsc`` runs from inside the temporary project tree.
    directory = toolchain.dependencies.resolve()
    try:
        packages = json.loads((directory / "package-lock.json").read_text(encoding="utf-8"))[
            "packages"
        ]
        if not isinstance(packages, dict):
            raise TypeError("packages is not an object")
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise TypeScriptDependenciesUnavailable(
            directory, f"unreadable lockfile: {error}"
        ) from error
    if "node_modules/typescript" not in packages:
        raise TypeScriptDependenciesUnavailable(directory, "the lockfile has no typescript")
    for key, entry in sorted(packages.items()):
        if not key.startswith("node_modules/") or not isinstance(entry, dict):
            continue
        if entry.get("link"):
            continue
        manifest = directory / key / "package.json"
        if not manifest.is_file():
            if entry.get("optional"):
                continue
            raise TypeScriptDependenciesUnavailable(directory, f"{key} is not installed")
        try:
            installed = str(json.loads(manifest.read_text(encoding="utf-8"))["version"])
            expected = str(entry["version"])
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise TypeScriptDependenciesUnavailable(
                directory, f"unreadable metadata for {key}: {error}"
            ) from error
        if installed != expected:
            raise ToolVersionMismatch(key.removeprefix("node_modules/"), expected, installed)
    bin_dir = directory / "node_modules" / ".bin"
    tsc = next((bin_dir / name for name in ("tsc.cmd", "tsc") if (bin_dir / name).is_file()), None)
    if tsc is None:
        raise TypeScriptDependenciesUnavailable(directory, "node_modules/.bin/tsc is missing")
    return ResolvedToolchain(
        dependencies=directory,
        tsc=str(tsc),
        typescript=str(packages["node_modules/typescript"]["version"]),
        lock_sha256=lock_sha256(directory),
    )


def typecheck(files: Mapping[str, str], project: str, toolchain: ResolvedToolchain) -> int:
    """Diagnostics from ``tsc --noEmit -p tsconfig.json`` over the snapshot's own project.

    The tree is written beside a link to the installed ``node_modules``, so
    module and type resolution walk up to it as they would from a checkout,
    and the tree itself never contains dependencies.
    """
    from .graph import write_sources

    with tempfile.TemporaryDirectory() as directory:
        tree = Path(directory) / "tree"
        write_sources(tree, files)
        (tree / PROJECT).write_text(project, encoding="utf-8")
        try:
            (Path(directory) / "node_modules").symlink_to(
                toolchain.dependencies.resolve() / "node_modules", target_is_directory=True
            )
        except OSError as error:
            raise TypeScriptDependenciesUnavailable(
                toolchain.dependencies, f"cannot link node_modules: {error}"
            ) from error
        _reject_path_mapping(tree, toolchain)
        completed = subprocess.run(
            [toolchain.tsc, "--noEmit", "--pretty", "false", "-p", PROJECT],
            cwd=tree, capture_output=True, text=True, check=False,
        )  # fmt: skip
    if completed.returncode not in (0, 2):
        raise AnalyzerFailed(
            f"typescript {toolchain.typescript} failed: "
            f"{completed.stderr.strip() or completed.stdout.strip()}"
        )
    return sum(bool(re.search(r"error TS\d+:", line)) for line in completed.stdout.splitlines())


def _reject_path_mapping(tree: Path, toolchain: ResolvedToolchain) -> None:
    """Refuse a project whose import resolution the module graph would not follow."""
    completed = subprocess.run(
        [toolchain.tsc, "--showConfig", "-p", PROJECT],
        cwd=tree, capture_output=True, text=True, check=False,
    )  # fmt: skip
    try:
        if completed.returncode != 0:
            raise ValueError(completed.stderr.strip() or completed.stdout.strip())
        options = json.loads(completed.stdout).get("compilerOptions", {})
    except (ValueError, AttributeError) as error:
        raise AnalyzerFailed(
            f"typescript {toolchain.typescript} cannot read {PROJECT}: {error}"
        ) from error
    mapped = sorted(set(PATH_MAPPING_OPTIONS) & set(options))
    if mapped:
        raise ConfigurationError(
            f"{PROJECT} sets {', '.join(mapped)}; the module graph resolves imports "
            "without the project file, so its edges would be wrong"
        )
