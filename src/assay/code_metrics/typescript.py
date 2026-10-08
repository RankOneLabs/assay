"""First-party TypeScript import graph from pinned dependency-cruiser."""

from __future__ import annotations

import json
import posixpath
import subprocess
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import AnalyzerFailed, ToolUnavailable
from .models import (
    ExternalDependencyV2,
    ImportEdgeV2,
    LanguageCoverage,
    ModuleEntryV2,
    ModuleGraphV2,
)
from .pins import DEPENDENCY_CRUISER, TYPESCRIPT

_COMMAND = ("npx", "--yes", "-p", DEPENDENCY_CRUISER, "-p", TYPESCRIPT, "depcruise")
# Type-only imports are kept: they couple modules at compile time even though
# the emitted JavaScript drops them.
_CONFIG = {"options": {"tsPreCompilationDeps": True, "doNotFollow": {"path": "node_modules"}}}


@dataclass(frozen=True)
class TypeScriptExtraction:
    graph: ModuleGraphV2
    coverage: LanguageCoverage


def extract_typescript_graph(files: Mapping[str, str]) -> TypeScriptExtraction:
    """Graph the snapshot's TypeScript files, each module identified by its path."""
    if not files:
        return _extraction(files, {"modules": []})
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory) / "snapshot"
        for path, source in sorted(files.items()):
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(source, encoding="utf-8")
        config = Path(directory) / "dependency-cruiser.json"
        config.write_text(json.dumps(_CONFIG), encoding="utf-8")
        return _extraction(files, _cruise(root, config))


def _cruise(root: Path, config: Path) -> dict[str, Any]:
    # Fetching and launching is checked apart from the analysis, so a failure
    # on this snapshot is not reported as a missing tool.
    try:
        subprocess.run([*_COMMAND, "--version"], capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as error:
        raise ToolUnavailable(DEPENDENCY_CRUISER, (error.stderr or str(error)).strip()) from error
    except OSError as error:
        raise ToolUnavailable(DEPENDENCY_CRUISER, str(error)) from error
    completed = subprocess.run(
        [*_COMMAND, "--no-cache", "--config", str(config), "--output-type", "json", "."],
        cwd=root, capture_output=True, text=True, check=False,
    )  # fmt: skip
    if completed.returncode != 0:
        raise AnalyzerFailed(f"dependency-cruiser failed: {completed.stderr.strip()}")
    try:
        cruise = json.loads(completed.stdout)
        if not isinstance(cruise, dict) or not isinstance(cruise.get("modules"), list):
            raise ValueError("no modules list")
    except ValueError as error:
        raise AnalyzerFailed(f"dependency-cruiser report unreadable: {error!r}") from error
    return cruise


def _extraction(files: Mapping[str, str], cruise: Mapping[str, Any]) -> TypeScriptExtraction:
    """Keep edges between snapshot files; every other import is an external dependency."""
    try:
        cruised: set[str] = set()
        edges: set[tuple[str, str]] = set()
        external: set[tuple[str, str]] = set()
        for module in cruise["modules"]:
            importer = module["source"]
            if importer not in files:
                continue
            cruised.add(importer)
            for dependency in module["dependencies"]:
                if dependency["resolved"] in files:
                    edges.add((importer, dependency["resolved"]))
                else:
                    external.add((importer, _package(importer, dependency)))
    except (KeyError, TypeError) as error:
        raise AnalyzerFailed(f"dependency-cruiser report unreadable: {error!r}") from error
    modules = tuple(
        ModuleEntryV2(module=path, path=path, language="typescript") for path in sorted(cruised)
    )
    return TypeScriptExtraction(
        graph=ModuleGraphV2(
            modules=modules,
            edges=tuple(
                ImportEdgeV2(importer=importer, imported=imported)
                for importer, imported in sorted(edges)
            ),
            external_dependencies=tuple(
                ExternalDependencyV2(module=module, package=package)
                for module, package in sorted(external)
            ),
        ),
        coverage=LanguageCoverage(
            language="typescript",
            files_seen=len(files),
            files_analyzed=len(cruised),
            modules_discovered=len(modules),
            files_without_module=tuple(sorted(files.keys() - cruised)),
        ),
    )


def _package(importer: str, dependency: Mapping[str, Any]) -> str:
    """A package by its name (``@scope/name``, ``name``, ``bun:test``), a relative
    import that names no snapshot file by its path from the snapshot root."""
    specifier: str = dependency["module"]
    if specifier.startswith(".") and not dependency["coreModule"]:
        return posixpath.normpath(posixpath.join(posixpath.dirname(importer), specifier))
    parts = specifier.split("/")
    return "/".join(parts[:2]) if specifier.startswith("@") else parts[0]
