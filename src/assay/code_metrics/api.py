"""Public absolute and comparative code-metrics API."""

from __future__ import annotations

import ast
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
    CodeMetricsComparisonV5,
    CodeMetricsReportV4,
    DetailedMetricDelta,
    ExistingMetricsV2,
    Language,
    LanguageCoverage,
    ModuleGraphV2,
    NewCodeMetricsV2,
    ResolvedConfiguration,
    Snapshot,
    SnapshotCoverageV2,
    ToolVersions,
    _Config,
    language_of,
    validate_snapshot,
)
from .pins import JSCPD, assert_pinned_tools, tool_versions, typescript_tool_versions


@dataclass(frozen=True)
class CodeMetricsConfig:
    """Analyzer thresholds and optional first-party component patterns."""

    clone_min_lines: int = 5
    clone_min_tokens: int = 50
    ruff_ignore: tuple[str, ...] = ()
    components: tuple[ComponentConfig, ...] = ()


def _preflight() -> None:
    if shutil.which("npx") is None or shutil.which("node") is None:
        raise ToolUnavailable(JSCPD, "Node.js or npx is unavailable")
    assert_pinned_tools()


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
) -> tuple[CodeMetricsReportV4, dict[str, Any]]:
    _validate_config(config)
    _preflight()
    snapshot = _validate_paths(snapshot)
    from . import tools
    from .graph import extract_module_graph
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
        python_coverage = _unextracted("python", {})
        direct_import_count = None
    typescript_files = {
        path: source for path, source in snapshot.items() if language_of(path) == "typescript"
    }
    typescript = extract_typescript_graph(typescript_files)
    graph = _merge(graph, typescript.graph)
    # Rust has no graph extractor yet; its files are counted and listed without a module.
    extracted_coverage = {"python": python_coverage, "typescript": typescript.coverage}
    coverage = SnapshotCoverageV2(
        languages=tuple(
            extracted_coverage.get(language) or _unextracted(language, snapshot)
            for language in LANGUAGES
        )
    )
    legacy_config = _Config(config.clone_min_lines, config.clone_min_tokens, config.ruff_ignore)
    try:
        payload = dict(
            tools._snapshot(
                files, legacy_config, graph=graph, direct_import_count=direct_import_count
            )
        )
    except AnalyzerFailed as error:
        detail = str(error).removeprefix(f"{AnalyzerFailed.operation}: ")
        raise AnalyzerFailed(f"analyze snapshot of {len(files)} Python files: {detail}") from error
    mi = dict(sorted(payload["mi"].items()))
    payload["radon.mi"] = statistics.fmean(mi.values()) if mi else None
    architecture = analyze_architecture(graph, config.components, require_matches=require_matches)
    versions = tool_versions()
    if typescript_files:
        versions |= typescript_tool_versions()
    # The analyzers read Python only, so without a Python file nothing was measured.
    measured = {key: payload[key] if files else None for key in DELTAS}
    report = CodeMetricsReportV4(
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
        configuration=ResolvedConfiguration(
            clone_min_lines=config.clone_min_lines,
            clone_min_tokens=config.clone_min_tokens,
            ruff_ignore=tuple(sorted(config.ruff_ignore)),
            components={
                item.name: tuple(sorted(item.patterns))
                for item in sorted(config.components, key=lambda item: item.name)
            },
            excluded_directories=(),
        ),
        versions=ToolVersions(
            assay=version("assay"),
            python=".".join(map(str, sys.version_info[:3])),
            tools=dict(sorted(versions.items())),
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


def _unextracted(language: Language, snapshot: Snapshot) -> LanguageCoverage:
    paths = tuple(sorted(path for path in snapshot if language_of(path) == language))
    return LanguageCoverage(
        language=language,
        files_seen=len(paths),
        files_analyzed=0,
        modules_discovered=0,
        files_without_module=paths,
    )


def analyze(snapshot: Snapshot, *, config: CodeMetricsConfig | None = None) -> CodeMetricsReportV4:
    """Measure one snapshot and assemble its absolute metric and architecture report."""
    return _analyze(snapshot, config or CodeMetricsConfig())[0]


def _compare(
    before: Snapshot, after: Snapshot, config: CodeMetricsConfig
) -> tuple[CodeMetricsComparisonV5, dict[str, float | None]]:
    """The comparison and the legacy delta mapping, which counts a side without Python as 0."""
    old_report, old = _analyze(before, config, require_matches=False)
    new_report, new = _analyze(after, config, require_matches=False)
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
        old_value = old[key] if old_python else None
        new_value = new[key] if new_python else None
        deltas.append(
            DetailedMetricDelta(
                metric=key,
                before=old_value,
                after=new_value,
                delta=difference if old_python and new_python else None,
                provenance="shared_file_mean" if key == "radon.mi" else "absolute_difference",
                shared_files=shared if key == "radon.mi" else (),
                shared_file_count=len(shared) if key == "radon.mi" else None,
            )
        )
    added = _added_lines(before, after)
    new_lines = sum(map(len, added.values()))
    new_duplicated_lines = sum(
        len(lines & new["cloned_lines"].get(path, set())) for path, lines in added.items()
    )
    new_max_nesting_depth = max(
        (
            depth
            for path, start, end, depth in new["functions"]
            if any(start <= line <= end for line in added.get(path, ()))
        ),
        default=0,
    )
    legacy["new_lines"] = new_lines
    legacy["new_duplicated_lines"] = new_duplicated_lines
    legacy["new_max_nesting_depth"] = new_max_nesting_depth
    new_code = (
        NewCodeMetricsV2(
            new_lines=new_lines,
            new_duplicated_lines=new_duplicated_lines,
            new_max_nesting_depth=new_max_nesting_depth,
        )
        if new_python
        else NewCodeMetricsV2(new_lines=None, new_duplicated_lines=None, new_max_nesting_depth=None)
    )
    old_architecture, new_architecture = old_report.architecture, new_report.architecture
    comparison = CodeMetricsComparisonV5(
        before=old_report,
        after=new_report,
        deltas=tuple(deltas),
        architecture_deltas=compare_architecture(old_architecture, new_architecture),
        new_code=new_code,
        structural_changes=structural_changes(old_architecture, new_architecture),
    )
    return comparison, legacy


def _has_python(snapshot: Snapshot) -> bool:
    return any(path.endswith(".py") for path in snapshot)


def compare(
    before: Snapshot, after: Snapshot, *, config: CodeMetricsConfig | None = None
) -> CodeMetricsComparisonV5:
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
