"""Deterministic first-party import graph extraction for one snapshot."""

from __future__ import annotations

import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import grimp
from grimp.application.config import settings
from grimp.application.ports.filesystem import AbstractFileSystem
from grimp.application.ports.packagefinder import AbstractPackageFinder

from ._imports import IMPORT_LOCK
from .models import (
    ExternalDependency,
    ImportEdge,
    ModuleEntry,
    ModuleGraph,
    Snapshot,
    SnapshotCoverage,
    validate_snapshot,
)


class _SnapshotPackageFinder(AbstractPackageFinder):
    """Resolve each package inside the snapshot, never from ``sys.modules`` or ``sys.path``.

    Grimp's default finder uses ``importlib.util.find_spec``, which returns an
    already-imported module's spec, so a snapshot package named like anything
    loaded in this process (``assay`` itself, ``pydantic``) would graph the
    installed code instead.
    """

    def __init__(self, base: Path) -> None:
        self._base = base

    def determine_package_directories(
        self, package_name: str, file_system: AbstractFileSystem
    ) -> set[str]:
        return {str(self._base / package_name)}


def build_import_graph(base: Path, packages: Iterable[str]) -> grimp.ImportGraph:
    """Build one Grimp graph of the top-level packages directly under *base*."""
    with IMPORT_LOCK:
        previous = settings.PACKAGE_FINDER
        settings.configure(PACKAGE_FINDER=_SnapshotPackageFinder(base))
        try:
            return grimp.build_graph(*packages, include_external_packages=True, cache_dir=None)
        finally:
            settings.configure(PACKAGE_FINDER=previous)


@dataclass(frozen=True)
class GraphExtraction:
    """Graph evidence and the uncollapsed direct-import count from one Grimp run."""

    graph: ModuleGraph
    coverage: SnapshotCoverage
    direct_import_count: int | None


def build_module_graph(
    snapshot: Snapshot, *, python_files_analyzed: Iterable[str] | None = None
) -> tuple[ModuleGraph, SnapshotCoverage]:
    """Build one Grimp graph and return sorted first-party evidence and coverage."""
    extracted = extract_module_graph(snapshot, python_files_analyzed=python_files_analyzed)
    return extracted.graph, extracted.coverage


def extract_module_graph(
    snapshot: Snapshot, *, python_files_analyzed: Iterable[str] | None = None
) -> GraphExtraction:
    """Extract public evidence and the legacy direct-import scalar together."""
    validated = validate_snapshot(snapshot)
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
) -> GraphExtraction:
    base = root / "src" if (root / "src").is_dir() else root
    packages = sorted(p.parent.name for p in base.glob("*/__init__.py"))
    if not packages:
        graph = ModuleGraph(modules=(), edges=(), external_dependencies=())
        direct_import_count: int | None = None
    else:
        imports = build_import_graph(base, packages)
        first_party = sorted(
            module
            for module in imports.modules
            if any(module == package or module.startswith(package + ".") for package in packages)
        )
        nodes = set(first_party)
        direct_imports = {
            module: tuple(sorted(imports.find_modules_directly_imported_by(module)))
            for module in sorted(imports.modules)
        }
        direct_import_count = sum(len(imported) for imported in direct_imports.values())
        modules = tuple(
            ModuleEntry(module=module, path=_module_path(root, base, module))
            for module in first_party
        )
        edges: list[ImportEdge] = []
        external: set[tuple[str, str]] = set()
        for importer in first_party:
            for imported in direct_imports[importer]:
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
    return GraphExtraction(graph, coverage, direct_import_count)


def _module_path(root: Path, base: Path, module: str) -> str | None:
    stem = base.joinpath(*module.split("."))
    for candidate in (stem.with_suffix(".py"), stem / "__init__.py"):
        if candidate.is_file():
            return candidate.relative_to(root).as_posix()
    return None
