"""Public absolute and comparative code-metrics API."""

from __future__ import annotations

import ast
import posixpath
import re
import shutil
import statistics
import sys
from dataclasses import dataclass
from difflib import SequenceMatcher
from importlib.metadata import version
from typing import Any

from assay.repository import RepositoryPathError

from .architecture import analyze_architecture, compare_architecture, structural_changes
from .components import ComponentConfig, require_pattern_matches
from .errors import (
    AnalyzerFailed,
    ConfigurationError,
    MalformedComponentConfig,
    ReservedComponentName,
    SnapshotPathError,
    SnapshotSyntaxError,
    ToolUnavailable,
)
from .models import (
    DELTAS,
    LANGUAGES,
    CodeMetricsComparisonV7,
    CodeMetricsReportV6,
    CountDelta,
    DetailedMetricDelta,
    ExistingMetricsV2,
    LanguageCoverage,
    ModuleGraphV2,
    NewCodeMetricsV2,
    OptionalCountDelta,
    PatchSummary,
    ResolvedConfigurationV2,
    Snapshot,
    SnapshotCoverageV2,
    ToolVersions,
    TypeScriptMetricDeltas,
    TypeScriptMetrics,
    UnmatchedPattern,
    _Config,
    language_of,
    validate_snapshot,
)
from .pins import (
    assert_pinned_tools,
    node_binary,
    rust_tool_versions,
    tool_versions,
    typescript_tool_versions,
)


@dataclass(frozen=True)
class CodeMetricsConfig:
    """Analyzer thresholds and optional first-party component patterns."""

    clone_min_lines: int = 5
    clone_min_tokens: int = 50
    ruff_ignore: tuple[str, ...] = ()
    components: tuple[ComponentConfig, ...] = ()
    allow_unmatched_patterns: bool = False


def _preflight() -> None:
    if shutil.which("node") is None:
        raise ToolUnavailable("node", "Node.js is unavailable")
    assert_pinned_tools()
    node_binary("jscpd")


def _validate_paths(snapshot: Snapshot) -> dict[str, str]:
    """Use the repository boundary while retaining the public path error type."""
    if not snapshot:
        return {}
    try:
        return validate_snapshot(snapshot)
    except RepositoryPathError as error:
        raise SnapshotPathError(f"must be relative and inside the repository: {error}") from error


def _validate_config(config: CodeMetricsConfig) -> None:
    for key in ("clone_min_lines", "clone_min_tokens"):
        value = getattr(config, key)
        if type(value) is not int or value < 1:
            raise ConfigurationError(f"{key} {value!r} must be a positive integer")
    if not isinstance(config.ruff_ignore, tuple) or not all(
        isinstance(rule, str) for rule in config.ruff_ignore
    ):
        raise ConfigurationError(f"ruff_ignore {config.ruff_ignore!r} must be a tuple of strings")
    if type(config.allow_unmatched_patterns) is not bool:
        raise ConfigurationError("allow_unmatched_patterns must be a bool")
    names: set[str] = set()
    if not isinstance(config.components, tuple):
        raise MalformedComponentConfig(f"components {config.components!r} must be a tuple")
    for component in config.components:
        if not isinstance(component, ComponentConfig):
            raise MalformedComponentConfig(f"component {component!r} is malformed")
        if not isinstance(component.name, str):
            raise MalformedComponentConfig(f"component name {component.name!r} must be a string")
        if component.name == "unassigned":
            raise ReservedComponentName("component 'unassigned' is reserved")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", component.name):
            raise MalformedComponentConfig(f"component {component.name!r} has an invalid name")
        if component.name in names:
            raise MalformedComponentConfig(f"component {component.name!r} is duplicated")
        names.add(component.name)
        if not isinstance(component.patterns, tuple) or not component.patterns:
            raise MalformedComponentConfig(f"component {component.name!r} has empty patterns")
        for pattern in component.patterns:
            if not isinstance(pattern, str) or not pattern:
                raise MalformedComponentConfig(
                    f"component {component.name!r} has malformed pattern {pattern!r}"
                )


def _analyze(
    snapshot: Snapshot, config: CodeMetricsConfig, *, require_matches: bool = True
) -> tuple[CodeMetricsReportV6, dict[str, Any]]:
    _validate_config(config)
    _preflight()
    snapshot = _validate_paths(snapshot)
    from . import tools
    from .graph import extract_module_graph
    from .rust import MANIFEST, extract_rust_graph
    from .typescript import extract_typescript_graph

    files = {path: snapshot[path] for path in sorted(snapshot) if path.endswith(".py")}
    for path, source in files.items():
        try:
            ast.parse(source, filename=path)
        except SyntaxError as error:
            raise SnapshotSyntaxError(path, error) from error
    if snapshot:
        extracted = extract_module_graph(snapshot, python_files_analyzed=files)
        graph, python_coverage = extracted.graph, extracted.coverage
        direct_import_count = extracted.direct_import_count
    else:
        graph = ModuleGraphV2(modules=(), edges=(), external_dependencies=())
        python_coverage = LanguageCoverage(
            language="python",
            files_seen=0,
            files_analyzed=0,
            modules_discovered=0,
            files_without_module=(),
        )
        direct_import_count = None
    typescript_files = {
        path: source for path, source in snapshot.items() if language_of(path) == "typescript"
    }
    typescript = extract_typescript_graph(typescript_files)
    rust_files = {path: source for path, source in snapshot.items() if language_of(path) == "rust"}
    rust = extract_rust_graph(
        rust_files,
        {path: source for path, source in snapshot.items() if posixpath.basename(path) == MANIFEST},
    )
    graph = _merge(_merge(graph, typescript.graph), rust.graph)
    extracted_coverage = {
        "python": python_coverage,
        "rust": rust.coverage,
        "typescript": typescript.coverage,
    }
    coverage = SnapshotCoverageV2(
        languages=tuple(extracted_coverage[language] for language in LANGUAGES)
    )
    legacy_config = _Config(config.clone_min_lines, config.clone_min_tokens, config.ruff_ignore)
    try:
        payload = dict(
            tools._snapshot(
                snapshot, legacy_config, graph=graph, direct_import_count=direct_import_count
            )
        )
    except AnalyzerFailed as error:
        detail = str(error).removeprefix(f"{AnalyzerFailed.operation}: ")
        raise AnalyzerFailed(f"analyze snapshot of {len(files)} Python files: {detail}") from error
    mi = dict(sorted(payload["mi"].items()))
    payload["radon.mi"] = statistics.fmean(mi.values()) if mi else None
    unmatched_patterns: list[tuple[str, str]] = []
    architecture = analyze_architecture(
        graph,
        config.components,
        require_matches=require_matches and not config.allow_unmatched_patterns,
        unmatched_patterns=unmatched_patterns,
    )
    versions = tool_versions()
    if typescript_files:
        versions |= typescript_tool_versions()
    if rust_files:
        versions |= rust_tool_versions()
    # jscpd also reads TypeScript; all other existing metrics require Python.
    measured = {
        key: payload[key] if (files or key.startswith("jscpd.") and typescript_files) else None
        for key in DELTAS
    }
    report = CodeMetricsReportV6(
        existing_metrics=ExistingMetricsV2(
            radon_sloc=measured["radon.sloc"],
            radon_lloc=measured["radon.lloc"],
            radon_cc=measured["radon.cc"],
            radon_halstead_volume=measured["radon.halstead_volume"],
            complexipy_cognitive=measured["complexipy.cognitive"],
            grimp_imports=measured["grimp.imports"],
            ruff_violations=measured["ruff.violations"],
            ruff_magic_values=measured["ruff.magic_values"],
            mypy_errors=measured["mypy.errors"],
            jscpd_clones=measured["jscpd.clones"],
            jscpd_duplicated_lines=measured["jscpd.duplicated_lines"],
            maintainability_index=mi,
            maintainability_index_mean=measured["radon.mi"],
        ),
        architecture=architecture,
        coverage=coverage,
        configuration=ResolvedConfigurationV2(
            clone_min_lines=config.clone_min_lines,
            clone_min_tokens=config.clone_min_tokens,
            ruff_ignore=tuple(sorted(config.ruff_ignore)),
            components={
                item.name: tuple(sorted(item.patterns))
                for item in sorted(config.components, key=lambda item: item.name)
            },
            excluded_directories=(),
            allow_unmatched_patterns=config.allow_unmatched_patterns,
            unmatched_patterns=tuple(
                UnmatchedPattern(component=component, pattern=pattern)
                for component, pattern in unmatched_patterns
            ),
        ),
        versions=ToolVersions(
            assay=version("assay"),
            python=".".join(map(str, sys.version_info[:3])),
            tools=dict(sorted(versions.items())),
        ),
        typescript_metrics=TypeScriptMetrics(
            lines=payload["typescript.lines"] if typescript_files else None,
            clones=payload["typescript.clones"] if typescript_files else None,
            duplicated_lines=payload["typescript.duplicated_lines"] if typescript_files else None,
            type_errors=payload["typescript.type_errors"] if typescript_files else None,
        ),
    )
    return report, payload


def _merge(first: ModuleGraphV2, second: ModuleGraphV2) -> ModuleGraphV2:
    """One graph of two languages' graphs, in the order each graph keeps alone."""
    return ModuleGraphV2(
        modules=tuple(sorted((*first.modules, *second.modules), key=lambda item: item.module)),
        edges=tuple(
            sorted((*first.edges, *second.edges), key=lambda item: (item.importer, item.imported))
        ),
        external_dependencies=tuple(
            sorted(
                (*first.external_dependencies, *second.external_dependencies),
                key=lambda item: (item.module, item.package),
            )
        ),
    )


def analyze(snapshot: Snapshot, *, config: CodeMetricsConfig | None = None) -> CodeMetricsReportV6:
    """Measure one snapshot and assemble its absolute metric and architecture report."""
    return _analyze(snapshot, config or CodeMetricsConfig())[0]


def _compare(
    before: Snapshot, after: Snapshot, config: CodeMetricsConfig
) -> tuple[CodeMetricsComparisonV7, dict[str, float | None]]:
    """The comparison and the legacy delta mapping, which counts a side without Python as 0."""
    old_report, old = _analyze(before, config, require_matches=False)
    new_report, new = _analyze(after, config, require_matches=False)
    if not config.allow_unmatched_patterns:
        require_pattern_matches(
            (old_report.architecture.graph, new_report.architecture.graph), config.components
        )
    shared = tuple(sorted(old["mi"].keys() & new["mi"].keys()))
    old_python = _has_python(before)
    new_python = _has_python(after)
    legacy: dict[str, float | None] = {}
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
        legacy[key] = difference
        old_value = (
            old[key]
            if (old_python or key.startswith("jscpd.") and _has_typescript(before))
            else None
        )
        new_value = (
            new[key]
            if (new_python or key.startswith("jscpd.") and _has_typescript(after))
            else None
        )
        deltas.append(
            DetailedMetricDelta(
                metric=key,
                before=old_value,
                after=new_value,
                delta=difference if old_value is not None and new_value is not None else None,
                provenance="shared_file_mean" if key == "radon.mi" else "absolute_difference",
                shared_files=shared if key == "radon.mi" else (),
                shared_file_count=len(shared) if key == "radon.mi" else None,
            )
        )
    added = _added_lines(before, after)
    metric_added = {
        path: lines
        for path, lines in added.items()
        if language_of(path) in ("python", "typescript")
    }
    python_added = {path: lines for path, lines in added.items() if language_of(path) == "python"}
    new_lines = sum(map(len, metric_added.values()))
    new_duplicated_lines = sum(
        len(lines & new["cloned_lines"].get(path, set())) for path, lines in metric_added.items()
    )
    new_max_nesting_depth = max(
        (
            depth
            for path, start, end, depth in new["functions"]
            if any(start <= line <= end for line in python_added.get(path, ()))
        ),
        default=0,
    )
    legacy["new_lines"] = sum(map(len, python_added.values()))
    legacy["new_duplicated_lines"] = sum(
        len(lines & new["cloned_lines"].get(path, set())) for path, lines in python_added.items()
    )
    legacy["new_max_nesting_depth"] = new_max_nesting_depth
    new_code = (
        NewCodeMetricsV2(
            new_lines=new_lines,
            new_duplicated_lines=new_duplicated_lines,
            new_max_nesting_depth=new_max_nesting_depth if new_python else None,
        )
        if new_python or _has_typescript(after)
        else NewCodeMetricsV2(new_lines=None, new_duplicated_lines=None, new_max_nesting_depth=None)
    )
    old_architecture, new_architecture = old_report.architecture, new_report.architecture
    changes = structural_changes(old_architecture, new_architecture)
    architecture_deltas = compare_architecture(old_architecture, new_architecture)
    old_module_paths = {entry.path: entry.module for entry in old_architecture.graph.modules}
    new_module_paths = {entry.path: entry.module for entry in new_architecture.graph.modules}
    old_ts, new_ts = old_report.typescript_metrics, new_report.typescript_metrics

    def optional_delta(before_value: int | None, after_value: int | None) -> OptionalCountDelta:
        return OptionalCountDelta(
            before=before_value,
            after=after_value,
            delta=None
            if before_value is None or after_value is None
            else after_value - before_value,
        )

    comparison = CodeMetricsComparisonV7(
        before=old_report,
        after=new_report,
        deltas=tuple(deltas),
        architecture_deltas=architecture_deltas,
        new_code=new_code,
        structural_changes=changes,
        typescript_deltas=TypeScriptMetricDeltas(
            lines=optional_delta(old_ts.lines, new_ts.lines),
            clones=optional_delta(old_ts.clones, new_ts.clones),
            duplicated_lines=optional_delta(old_ts.duplicated_lines, new_ts.duplicated_lines),
            type_errors=optional_delta(old_ts.type_errors, new_ts.type_errors),
        ),
        patch=PatchSummary(
            code_lines=_count(_source_lines(before), _source_lines(after)),
            module_count=_count(old_architecture.module_count, new_architecture.module_count),
            cyclic_scc_count=_count(
                old_architecture.cycles.cyclic_scc_count,
                new_architecture.cycles.cyclic_scc_count,
            ),
            propagation_cost=architecture_deltas.system.propagation_cost,
            added_lines=sum(map(len, _added_lines(before, after).values())),
            removed_lines=sum(map(len, _added_lines(after, before).values())),
            changed_modules=tuple(
                sorted(
                    old_module_paths[path]
                    for path in before.keys() & after.keys()
                    if before[path] != after[path]
                    and path in old_module_paths
                    and old_module_paths[path] == new_module_paths.get(path)
                )
            ),
            new_cycles=changes.cycles_created,
        ),
    )
    return comparison, legacy


def _has_python(snapshot: Snapshot) -> bool:
    return any(path.endswith(".py") for path in snapshot)


def _has_typescript(snapshot: Snapshot) -> bool:
    return any(language_of(path) == "typescript" for path in snapshot)


def _source_lines(snapshot: Snapshot) -> int:
    return sum(
        len(text.splitlines()) for path, text in snapshot.items() if language_of(path) is not None
    )


def _count(before: int, after: int) -> CountDelta:
    return CountDelta(before=before, after=after, delta=after - before)


def compare(
    before: Snapshot, after: Snapshot, *, config: CodeMetricsConfig | None = None
) -> CodeMetricsComparisonV7:
    """Compare absolute reports with explicit architecture deltas and structural evidence."""
    return _compare(before, after, config or CodeMetricsConfig())[0]


def measure(
    before: Snapshot,
    after: Snapshot,
    *,
    clone_min_lines: int = 5,
    clone_min_tokens: int = 50,
    ruff_ignore: tuple[str, ...] = (),
) -> dict[str, float | None]:
    """Legacy ordered, rounded metric deltas over the shared analysis."""
    return _compare(
        before,
        after,
        CodeMetricsConfig(
            clone_min_lines=clone_min_lines,
            clone_min_tokens=clone_min_tokens,
            ruff_ignore=ruff_ignore,
        ),
    )[1]


def _added_lines(before: Snapshot, after: Snapshot) -> dict[str, set[int]]:
    """1-based line numbers of nonblank lines in ``after`` that ``before`` lacks."""
    added: dict[str, set[int]] = {}
    for path in sorted(after):
        if language_of(path) is None:
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
