"""Deterministic first-party import graph extraction for one snapshot."""

from __future__ import annotations

import sys
import tempfile
from collections.abc import Iterable
from pathlib import Path

import grimp

from assay.repository import validate_repository

from ._imports import IMPORT_LOCK
from .models import (
    ExternalDependency,
    ImportEdge,
    ModuleEntry,
    ModuleGraph,
    Snapshot,
    SnapshotCoverage,
)


def build_module_graph(
    snapshot: Snapshot, *, python_files_analyzed: Iterable[str] | None = None
) -> tuple[ModuleGraph, SnapshotCoverage]:
    """Build one Grimp graph and return sorted first-party evidence and coverage."""
    validated = validate_repository(snapshot)
    files = {path: text for path, text in validated.items() if path.endswith(".py")}
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        for path, source in sorted(files.items()):
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(source, encoding="utf-8")
        return _extract(root, files, python_files_analyzed)


def _extract(
    root: Path, files: dict[str, str], python_files_analyzed: Iterable[str] | None
) -> tuple[ModuleGraph, SnapshotCoverage]:
    base = root / "src" if (root / "src").is_dir() else root
    packages = sorted(p.parent.name for p in base.glob("*/__init__.py"))
    if not packages:
        graph = ModuleGraph(modules=(), edges=(), external_dependencies=())
    else:
        with IMPORT_LOCK:
            sys.path.insert(0, str(base))
            try:
                imports = grimp.build_graph(
                    *packages, include_external_packages=True, cache_dir=None
                )
            finally:
                sys.path.remove(str(base))
        first_party = sorted(
            module
            for module in imports.modules
            if any(module == package or module.startswith(package + ".") for package in packages)
        )
        nodes = set(first_party)
        modules = tuple(
            ModuleEntry(module=module, path=_module_path(root, base, module))
            for module in first_party
        )
        edges: list[ImportEdge] = []
        external: set[tuple[str, str]] = set()
        for importer in first_party:
            for imported in sorted(imports.find_modules_directly_imported_by(importer)):
                if imported in nodes:
                    edges.append(ImportEdge(importer=importer, imported=imported))
                else:
                    external.add((importer, imported.split(".", 1)[0]))
        graph = ModuleGraph(
            modules=modules,
            edges=tuple(sorted(edges, key=lambda edge: (edge.importer, edge.imported))),
            external_dependencies=tuple(
                ExternalDependency(module=module, package=package)
                for module, package in sorted(external)
            ),
        )
    resolved = {entry.path for entry in graph.modules if entry.path is not None}
    analyzed = set(files) if python_files_analyzed is None else set(python_files_analyzed)
    coverage = SnapshotCoverage(
        python_files_seen=len(files),
        python_files_analyzed=len(analyzed & files.keys()),
        modules_discovered=len(graph.modules),
        files_without_module=tuple(sorted(files.keys() - resolved)),
    )
    return graph, coverage


def _module_path(root: Path, base: Path, module: str) -> str | None:
    stem = base.joinpath(*module.split("."))
    for candidate in (stem.with_suffix(".py"), stem / "__init__.py"):
        if candidate.is_file():
            return candidate.relative_to(root).as_posix()
    return None
