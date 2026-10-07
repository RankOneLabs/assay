"""Public absolute and comparative code-metrics API."""

from __future__ import annotations

import re
import shutil
import statistics
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from difflib import SequenceMatcher
from importlib.metadata import version
from pathlib import Path, PurePosixPath
from typing import Any

from .components import ComponentConfig, analyze_components
from .cycles import analyze_cycles
from .errors import (
    MalformedComponentConfig,
    ReservedComponentName,
    SnapshotPathError,
    ToolUnavailable,
)
from .models import (
    DELTAS,
    ArchitectureReport,
    CodeMetricsReportV2,
    DetailedCodeMetricsComparison,
    DetailedMetricDelta,
    DetailedStructuralChanges,
    ExistingMetrics,
    ModuleGraph,
    NewCodeMetrics,
    ResolvedConfiguration,
    Snapshot,
    SnapshotCoverage,
    ToolVersions,
    _Config,
)
from .pins import JSCPD, assert_pinned_tools, tool_versions
from .propagation import analyze_propagation


@dataclass(frozen=True)
class CodeMetricsConfig:
    """Analyzer thresholds and optional first-party component patterns."""

    clone_min_lines: int = 5
    clone_min_tokens: int = 50
    ruff_ignore: tuple[str, ...] = ()
    components: tuple[ComponentConfig, ...] = ()
    excluded_directories: tuple[str, ...] = ()


def _preflight() -> None:
    if shutil.which("npx") is None or shutil.which("node") is None:
        raise ToolUnavailable(JSCPD, "Node.js or npx is unavailable")
    assert_pinned_tools()


def _validate_paths(snapshot: Snapshot) -> None:
    for path in snapshot:
        parts = PurePosixPath(path).parts
        if (
            PurePosixPath(path).is_absolute()
            or ".." in parts
            or "\\" in path
            or any(part in ("", ".") for part in path.split("/"))
        ):
            raise SnapshotPathError(
                f"analyze snapshot path must be relative and inside the repository: {path}"
            )


def _validate_config(config: CodeMetricsConfig) -> None:
    names: set[str] = set()
    for component in config.components:
        if not isinstance(component, ComponentConfig):
            raise MalformedComponentConfig(f"component {component!r} is malformed")
        if component.name == "unassigned":
            raise ReservedComponentName("component 'unassigned' is reserved")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", component.name):
            raise MalformedComponentConfig(f"component {component.name!r} has an invalid name")
        if component.name in names:
            raise MalformedComponentConfig(f"component {component.name!r} is duplicated")
        names.add(component.name)
        if not component.patterns or any(not pattern for pattern in component.patterns):
            raise MalformedComponentConfig(f"component {component.name!r} has empty patterns")


def _analyze(
    snapshot: Snapshot, config: CodeMetricsConfig
) -> tuple[CodeMetricsReportV2, dict[str, Any]]:
    _preflight()
    _validate_config(config)
    _validate_paths(snapshot)
    from complexipy import code_complexity

    from . import tools
    from .graph import build_module_graph

    files = {path: snapshot[path] for path in sorted(snapshot) if path.endswith(".py")}
    if snapshot:
        graph, coverage = build_module_graph(snapshot, python_files_analyzed=files)
    else:
        graph = ModuleGraph(modules=(), edges=(), external_dependencies=())
        coverage = SnapshotCoverage(
            python_files_seen=0,
            python_files_analyzed=0,
            modules_discovered=0,
            files_without_module=(),
        )
    legacy_config = _Config(config.clone_min_lines, config.clone_min_tokens, config.ruff_ignore)
    if files:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for path, source in files.items():
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(source, encoding="utf-8")
            try:
                clones = tools._jscpd(root, legacy_config)
            except (subprocess.CalledProcessError, FileNotFoundError, OSError) as error:
                raise ToolUnavailable(JSCPD, str(error)) from error
            payload = {
                **tools._radon(files),
                "complexipy.cognitive": sum(
                    code_complexity(source).complexity for source in files.values()
                ),
                "grimp.imports": (
                    len(graph.edges) + len(graph.external_dependencies) if graph.modules else None
                ),
                **tools._ruff(root, config.ruff_ignore),
                "mypy.errors": tools._mypy(root),
                **clones,
                "functions": sorted(tools._functions(root)),
            }
    else:
        payload = tools._empty()
    mi = dict(sorted(payload["mi"].items()))
    payload["radon.mi"] = statistics.fmean(mi.values()) if mi else None
    components = analyze_components(graph, config.components)
    architecture = ArchitectureReport(
        graph=graph,
        module_coupling=components.module_coupling,
        component_coupling=components.component_coupling,
        module_components=components.module_components,
        boundaries=components.boundaries,
        cycles=analyze_cycles(graph),
        propagation=analyze_propagation(graph),
    )
    report = CodeMetricsReportV2(
        existing_metrics=ExistingMetrics(
            radon_sloc=payload["radon.sloc"],
            radon_lloc=payload["radon.lloc"],
            radon_cc=payload["radon.cc"],
            radon_halstead_volume=payload["radon.halstead_volume"],
            complexipy_cognitive=payload["complexipy.cognitive"],
            grimp_imports=payload["grimp.imports"],
            ruff_violations=payload["ruff.violations"],
            ruff_magic_values=payload["ruff.magic_values"],
            mypy_errors=payload["mypy.errors"],
            jscpd_clones=payload["jscpd.clones"],
            jscpd_duplicated_lines=payload["jscpd.duplicated_lines"],
            maintainability_index=mi,
            maintainability_index_mean=payload["radon.mi"],
        ),
        architecture=architecture,
        coverage=coverage,
        configuration=ResolvedConfiguration(
            clone_min_lines=config.clone_min_lines,
            clone_min_tokens=config.clone_min_tokens,
            ruff_ignore=tuple(sorted(config.ruff_ignore)),
            components={
                item.name: tuple(sorted(item.patterns))
                for item in sorted(config.components, key=lambda item: item.name)
            },
            excluded_directories=tuple(sorted(config.excluded_directories)),
        ),
        versions=ToolVersions(
            assay=version("assay"),
            python=".".join(map(str, sys.version_info[:3])),
            tools=dict(sorted(tool_versions().items())),
        ),
    )
    return report, payload


def analyze(snapshot: Snapshot, *, config: CodeMetricsConfig | None = None) -> CodeMetricsReportV2:
    """Measure one snapshot and assemble its absolute metric and architecture report."""
    return _analyze(snapshot, config or CodeMetricsConfig())[0]


def _compare(
    before: Snapshot, after: Snapshot, config: CodeMetricsConfig
) -> DetailedCodeMetricsComparison:
    old_report, old = _analyze(before, config)
    new_report, new = _analyze(after, config)
    shared = tuple(sorted(old["mi"].keys() & new["mi"].keys()))
    deltas = []
    for key in DELTAS:
        if key == "radon.mi":
            difference = (
                round(statistics.fmean(new["mi"][path] - old["mi"][path] for path in shared), 3)
                if shared
                else 0.0
            )
        elif old[key] is None or new[key] is None:
            difference = None
        else:
            difference = round(new[key] - old[key], 3)
        deltas.append(
            DetailedMetricDelta(
                metric=key,
                before=old[key],
                after=new[key],
                delta=difference,
                provenance="shared_file_mean" if key == "radon.mi" else "absolute_difference",
                shared_files=shared if key == "radon.mi" else (),
                shared_file_count=len(shared) if key == "radon.mi" else None,
            )
        )
    added = _added_lines(before, after)
    new_code = NewCodeMetrics(
        new_lines=sum(map(len, added.values())),
        new_duplicated_lines=sum(
            len(lines & new["cloned_lines"].get(path, set())) for path, lines in added.items()
        ),
        new_max_nesting_depth=max(
            (
                depth
                for path, start, end, depth in new["functions"]
                if any(start <= line <= end for line in added.get(path, ()))
            ),
            default=0,
        ),
    )
    old_graph, new_graph = old_report.architecture.graph, new_report.architecture.graph
    old_modules = {entry.module for entry in old_graph.modules}
    new_modules = {entry.module for entry in new_graph.modules}
    old_edges, new_edges = set(old_graph.edges), set(new_graph.edges)
    old_components = {entry.component for entry in old_report.architecture.component_coupling}
    new_components = {entry.component for entry in new_report.architecture.component_coupling}
    old_cycles = {
        item.modules for item in old_report.architecture.cycles.components if item.is_cyclic
    }
    new_cycles = {
        item.modules for item in new_report.architecture.cycles.components if item.is_cyclic
    }
    changes = DetailedStructuralChanges(
        modules_added=tuple(sorted(new_modules - old_modules)),
        modules_removed=tuple(sorted(old_modules - new_modules)),
        edges_added=tuple(
            sorted(new_edges - old_edges, key=lambda item: (item.importer, item.imported))
        ),
        edges_removed=tuple(
            sorted(old_edges - new_edges, key=lambda item: (item.importer, item.imported))
        ),
        components_added=tuple(sorted(new_components - old_components)),
        components_removed=tuple(sorted(old_components - new_components)),
        cycles_created=tuple(sorted(new_cycles - old_cycles)),
        cycles_resolved=tuple(sorted(old_cycles - new_cycles)),
    )
    return DetailedCodeMetricsComparison(
        before=old_report,
        after=new_report,
        deltas=tuple(deltas),
        new_code=new_code,
        structural_changes=changes,
    )


def compare(
    before: Snapshot, after: Snapshot, *, config: CodeMetricsConfig | None = None
) -> DetailedCodeMetricsComparison:
    """Compare absolute reports and retain explicit structural change evidence."""
    return _compare(before, after, config or CodeMetricsConfig())


def measure(
    before: Snapshot,
    after: Snapshot,
    *,
    clone_min_lines: int = 5,
    clone_min_tokens: int = 50,
    ruff_ignore: tuple[str, ...] = (),
) -> dict[str, float | None]:
    """Legacy ordered, rounded metric deltas over the shared analysis."""
    comparison = _compare(
        before,
        after,
        CodeMetricsConfig(
            clone_min_lines=clone_min_lines,
            clone_min_tokens=clone_min_tokens,
            ruff_ignore=ruff_ignore,
        ),
    )
    result: dict[str, float | None] = {entry.metric: entry.delta for entry in comparison.deltas}
    result["new_lines"] = comparison.new_code.new_lines
    result["new_duplicated_lines"] = comparison.new_code.new_duplicated_lines
    result["new_max_nesting_depth"] = comparison.new_code.new_max_nesting_depth
    return result


def _added_lines(before: Snapshot, after: Snapshot) -> dict[str, set[int]]:
    """1-based line numbers of nonblank lines in ``after`` that ``before`` lacks."""
    added: dict[str, set[int]] = {}
    for path in sorted(after):
        if not path.endswith(".py"):
            continue
        new = after[path].splitlines()
        old = before.get(path, "").splitlines()
        lines: set[int] = set()
        for tag, _, _, start, end in SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
            if tag in ("insert", "replace"):
                lines.update(n + 1 for n in range(start, end) if new[n].strip())
        if lines:
            added[path] = lines
    return added
