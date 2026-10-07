"""Typed code-metrics wire reports and the legacy metric API's small shared types."""

from __future__ import annotations

import codecs
import io
import re
import sys
from collections.abc import Mapping
from typing import Annotated, Literal, NamedTuple, Self

from pydantic import AfterValidator, Field, StringConstraints, model_validator

from assay.models import Identifier, NonEmpty, WireModel
from assay.repository import validate_repository

# Keep the promoted API's public metric order stable.
DELTAS = (
    "radon.sloc",
    "radon.lloc",
    "radon.cc",
    "radon.halstead_volume",
    "radon.mi",
    "complexipy.cognitive",
    "grimp.imports",
    "ruff.violations",
    "ruff.magic_values",
    "mypy.errors",
    "jscpd.clones",
    "jscpd.duplicated_lines",
)
NEW_CODE = ("new_lines", "new_duplicated_lines", "new_max_nesting_depth")
METRICS = DELTAS + NEW_CODE
Snapshot = Mapping[str, str]


def validate_snapshot(snapshot: Snapshot) -> dict[str, str]:
    """Apply the repository path boundary without the study-sized file and byte caps."""
    return validate_repository(snapshot, max_files=sys.maxsize, max_total_bytes=sys.maxsize)


_CODING = re.compile(r"^[ \t\f]*#.*?(coding)[:=][ \t]*([-\w.]+)", re.ASCII)


def utf8_source(source: str) -> str:
    """*source* for a UTF-8 file, with any declaration of another encoding disarmed.

    A snapshot holds decoded text, so a Latin-1 declaration no longer describes
    it: analyzers would decode the UTF-8 copy as Latin-1. Grimp 3.17 also panics
    on a non-UTF-8 declaration in either of the first two physical lines, even
    one Python ignores or one inside a string. Capitalizing the ``c`` of
    ``coding`` ends the match while keeping every line's length and syntax.
    """
    lines = io.StringIO(source, newline="").readlines()
    for index, line in enumerate(lines[:2]):
        while (match := _CODING.match(line)) and not _is_utf8(match.group(2)):
            line = f"{line[: match.start(1)]}C{line[match.start(1) + 1 :]}"
        lines[index] = line
    return "".join(lines)


def _is_utf8(name: str) -> bool:
    try:
        return codecs.lookup(name).name == "utf-8"
    except LookupError:
        return False


class _Config(NamedTuple):
    clone_min_lines: int
    clone_min_tokens: int
    ruff_ignore: tuple[str, ...]


def is_module_name(value: str) -> bool:
    """Whether *value* is a dotted name of Python identifiers, Unicode ones included."""
    return all(part.isidentifier() for part in value.split("."))


def _module_name(value: str) -> str:
    if not is_module_name(value):
        raise ValueError(f"{value!r} is not a dotted Python identifier")
    return value


# The published pattern is exact for ASCII and admits every non-ASCII character,
# because JSON Schema regex engines disagree on Unicode classes; the model's
# validator applies Python's own identifier rule to the rest.
_IDENTIFIER_START = r"[^\x00-\x40\x5B-\x5E\x60\x7B-\x7F]"
_IDENTIFIER_CONTINUE = r"[^\x00-\x2F\x3A-\x40\x5B-\x5E\x60\x7B-\x7F]"
_IDENTIFIER = f"{_IDENTIFIER_START}{_IDENTIFIER_CONTINUE}*"
ModuleName = Annotated[
    str,
    StringConstraints(pattern=rf"^{_IDENTIFIER}(\.{_IDENTIFIER})*$"),
    AfterValidator(_module_name),
]
ComponentName = Identifier
RepoPath = Annotated[str, StringConstraints(pattern=r"^[^/\\][^\\]*$")]


class ModuleEntry(WireModel):
    module: ModuleName
    path: RepoPath | None


class ImportEdge(WireModel):
    importer: ModuleName
    imported: ModuleName


class ExternalDependency(WireModel):
    module: ModuleName
    package: ModuleName


class ModuleGraph(WireModel):
    modules: tuple[ModuleEntry, ...]
    edges: tuple[ImportEdge, ...]
    external_dependencies: tuple[ExternalDependency, ...]


class ModuleCoupling(WireModel):
    module: ModuleName
    fan_in: int
    fan_out: int


class ComponentCoupling(WireModel):
    component: ComponentName
    modules: tuple[ModuleName, ...]
    afferent: int
    efferent: int
    instability: float | None
    internal_edges: int
    incoming_edges: int
    outgoing_edges: int
    module_count: int
    relational_cohesion: float | None
    internal_dependency_density: float | None
    internal_edge_share: float | None


class ModuleCouplingV3(ModuleCoupling):
    """Direct first-party import counts of one module."""

    fan_in: int = Field(description="Distinct first-party modules that directly import this one.")
    fan_out: int = Field(description="Distinct first-party modules this one directly imports.")


class ComponentCouplingV3(ComponentCoupling):
    """Coupling and cohesion of one component, with the coupling semantics stated."""

    afferent: int = Field(
        description="Ca: distinct modules outside the component that directly import one in it."
    )
    efferent: int = Field(
        description=(
            "Ce: distinct modules outside the component that a module in it directly imports"
            " (the imported modules, not the importing members)."
        )
    )
    instability: float | None = Field(description="Ce / (Ca + Ce); null when Ca + Ce is 0.")


class BoundaryPair(WireModel):
    importer_component: ComponentName
    imported_component: ComponentName
    edge_count: int


class ModuleComponent(WireModel):
    module: ModuleName
    path: RepoPath | None
    component: ComponentName


class ComponentMetricsReport(WireModel):
    module_coupling: tuple[ModuleCouplingV3, ...]
    component_coupling: tuple[ComponentCouplingV3, ...]
    module_components: tuple[ModuleComponent, ...]
    boundaries: tuple[BoundaryPair, ...]


class StronglyConnectedComponent(WireModel):
    modules: tuple[ModuleName, ...]
    is_cyclic: bool


class CycleReport(WireModel):
    components: tuple[StronglyConnectedComponent, ...]
    cyclic_component_count: int
    modules_in_cycles: tuple[ModuleName, ...]


class CycleReportV1(WireModel):
    """The published 0.1.0 cycle shape."""

    components: tuple[StronglyConnectedComponent, ...]
    cyclic_component_count: int
    modules_in_cycles: int


class ModuleVisibility(WireModel):
    module: ModuleName
    reaches: int
    reached_by: int


class PropagationReport(WireModel):
    module_visibility: tuple[ModuleVisibility, ...]
    propagation_cost: float | None


class SnapshotCoverage(WireModel):
    python_files_seen: int
    python_files_analyzed: int
    modules_discovered: int
    files_without_module: tuple[RepoPath, ...]


class ResolvedConfiguration(WireModel):
    clone_min_lines: int
    clone_min_tokens: int
    ruff_ignore: tuple[Identifier, ...]
    components: Mapping[ComponentName, tuple[RepoPath, ...]] = Field(
        json_schema_extra={"additionalProperties": False}
    )
    excluded_directories: tuple[RepoPath, ...]


class ToolVersions(WireModel):
    assay: NonEmpty
    python: NonEmpty
    tools: Mapping[Identifier, NonEmpty] = Field(json_schema_extra={"additionalProperties": False})


class ExistingMetrics(WireModel):
    radon_sloc: int
    radon_lloc: int
    radon_cc: int
    radon_halstead_volume: float
    complexipy_cognitive: int
    grimp_imports: int | None
    ruff_violations: int
    ruff_magic_values: int
    mypy_errors: int | None
    jscpd_clones: int
    jscpd_duplicated_lines: int
    maintainability_index: Mapping[RepoPath, float] = Field(
        json_schema_extra={"additionalProperties": False}
    )
    maintainability_index_mean: float | None


class NewCodeMetrics(WireModel):
    """Metrics of added lines; only a comparison can define these values."""

    new_lines: int
    new_duplicated_lines: int
    new_max_nesting_depth: int


class MetricDelta(WireModel):
    metric: Identifier
    before: float | None
    after: float | None
    delta: float | None
    provenance: Literal["absolute_difference", "shared_file_mean"]
    shared_files: tuple[RepoPath, ...] = ()


class StructuralChanges(WireModel):
    added_modules: tuple[ModuleName, ...]
    removed_modules: tuple[ModuleName, ...]
    added_edges: tuple[ImportEdge, ...]
    removed_edges: tuple[ImportEdge, ...]


class ArchitectureReport(WireModel):
    graph: ModuleGraph
    module_coupling: tuple[ModuleCoupling, ...]
    component_coupling: tuple[ComponentCoupling, ...]
    module_components: tuple[ModuleComponent, ...]
    boundaries: tuple[BoundaryPair, ...]
    cycles: CycleReport
    propagation: PropagationReport


class ArchitectureReportV1(WireModel):
    """The published 0.1.0 architecture shape."""

    graph: ModuleGraph
    module_coupling: tuple[ModuleCoupling, ...]
    component_coupling: tuple[ComponentCoupling, ...]
    module_components: Mapping[ModuleName, ComponentName] = Field(
        json_schema_extra={"additionalProperties": False}
    )
    boundaries: tuple[BoundaryPair, ...]
    cycles: CycleReportV1
    propagation: PropagationReport


class CodeMetricsReport(WireModel):
    """Published 0.1.0 absolute snapshot report."""

    schema_version: Literal["assay-code-metrics-report/0.1.0"] = "assay-code-metrics-report/0.1.0"
    existing_metrics: ExistingMetrics
    architecture: ArchitectureReportV1
    coverage: SnapshotCoverage
    configuration: ResolvedConfiguration
    versions: ToolVersions


class CodeMetricsComparison(WireModel):
    """Published 0.1.0 comparison of two absolute reports."""

    schema_version: Literal["assay-code-metrics-comparison/0.1.0"] = (
        "assay-code-metrics-comparison/0.1.0"
    )
    before: CodeMetricsReport
    after: CodeMetricsReport
    deltas: tuple[MetricDelta, ...]
    new_code: NewCodeMetrics
    structural_changes: StructuralChanges


class CodeMetricsReportV2(WireModel):
    """Absolute snapshot report with path-bearing component and cycle evidence."""

    schema_version: Literal["assay-code-metrics-report/0.2.0"] = "assay-code-metrics-report/0.2.0"
    existing_metrics: ExistingMetrics
    architecture: ArchitectureReport
    coverage: SnapshotCoverage
    configuration: ResolvedConfiguration
    versions: ToolVersions


class CodeMetricsComparisonV2(WireModel):
    """Comparison of two 0.2.0 absolute reports."""

    schema_version: Literal["assay-code-metrics-comparison/0.2.0"] = (
        "assay-code-metrics-comparison/0.2.0"
    )
    before: CodeMetricsReportV2
    after: CodeMetricsReportV2
    deltas: tuple[MetricDelta, ...]
    new_code: NewCodeMetrics
    structural_changes: StructuralChanges


class DetailedStructuralChanges(WireModel):
    """Explicit structural additions and removals, including components and cycles."""

    modules_added: tuple[ModuleName, ...]
    modules_removed: tuple[ModuleName, ...]
    edges_added: tuple[ImportEdge, ...]
    edges_removed: tuple[ImportEdge, ...]
    components_added: tuple[ComponentName, ...]
    components_removed: tuple[ComponentName, ...]
    cycles_created: tuple[tuple[ModuleName, ...], ...]
    cycles_resolved: tuple[tuple[ModuleName, ...], ...]


class DetailedMetricDelta(MetricDelta):
    """A metric delta with an explicit shared-file count for legacy MI."""

    shared_file_count: int | None = None


class DetailedCodeMetricsComparison(WireModel):
    """Published 0.3.0 comparison with complete structural evidence."""

    schema_version: Literal["assay-code-metrics-comparison/0.3.0"] = (
        "assay-code-metrics-comparison/0.3.0"
    )
    before: CodeMetricsReportV2
    after: CodeMetricsReportV2
    deltas: tuple[DetailedMetricDelta, ...]
    new_code: NewCodeMetrics
    structural_changes: DetailedStructuralChanges


class CycleReportV3(CycleReport):
    """The 0.3.0 cycle shape: full SCC evidence plus scalars derived from it."""

    scc_count: int
    cyclic_scc_count: int
    cyclic_module_count: int
    largest_cyclic_scc_size: int


class ModuleVisibilityV3(ModuleVisibility):
    """Raw reach counts and the same counts over the module total, self included."""

    fan_out_visibility: float
    fan_in_visibility: float


class PropagationReportV3(WireModel):
    module_visibility: tuple[ModuleVisibilityV3, ...]
    propagation_cost: float | None


class ArchitectureReportV3(WireModel):
    """The 0.3.0 architecture shape with graph-level counts.

    ``first_party_edge_count`` counts every first-party module-to-module edge;
    ``cross_component_edge_count`` counts those whose two ends have different
    owning components (``unassigned`` included as an owner).
    """

    graph: ModuleGraph
    module_count: int
    first_party_edge_count: int
    cross_component_edge_count: int
    module_coupling: tuple[ModuleCouplingV3, ...]
    component_coupling: tuple[ComponentCouplingV3, ...]
    module_components: tuple[ModuleComponent, ...]
    boundaries: tuple[BoundaryPair, ...]
    cycles: CycleReportV3
    propagation: PropagationReportV3


class CodeMetricsReportV3(WireModel):
    """Absolute snapshot report with derived cycle, visibility, and edge scalars."""

    schema_version: Literal["assay-code-metrics-report/0.3.0"] = "assay-code-metrics-report/0.3.0"
    existing_metrics: ExistingMetrics
    architecture: ArchitectureReportV3
    coverage: SnapshotCoverage
    configuration: ResolvedConfiguration
    versions: ToolVersions


class CountDelta(WireModel):
    before: int
    after: int
    delta: int


class RatioDelta(WireModel):
    """A ratio on both sides; ``delta`` is null when either side is undefined."""

    before: float | None
    after: float | None
    delta: float | None


class SystemArchitectureDeltas(WireModel):
    propagation_cost: RatioDelta
    first_party_edge_count: CountDelta
    cross_component_edge_count: CountDelta
    cyclic_scc_count: CountDelta
    cyclic_module_count: CountDelta
    largest_cyclic_scc_size: CountDelta


class ComponentMetricDeltas(WireModel):
    afferent: CountDelta
    efferent: CountDelta
    instability: RatioDelta
    internal_edges: CountDelta
    incoming_edges: CountDelta
    outgoing_edges: CountDelta
    relational_cohesion: RatioDelta
    internal_dependency_density: RatioDelta
    internal_edge_share: RatioDelta


class ComponentDelta(WireModel):
    component: ComponentName
    metrics: ComponentMetricDeltas


class ModuleCouplingDelta(WireModel):
    module: ModuleName
    fan_in: CountDelta
    fan_out: CountDelta


class BoundaryPairDelta(WireModel):
    importer_component: ComponentName
    imported_component: ComponentName
    before: int
    after: int
    delta: int


class ArchitectureDeltas(WireModel):
    """Before, after, and difference for architecture scalars, without interpretation.

    Components and modules appear only when both sides have them; a boundary
    pair appears when either side has it, its edge count zero on the other.
    """

    system: SystemArchitectureDeltas
    components: tuple[ComponentDelta, ...]
    modules: tuple[ModuleCouplingDelta, ...]
    boundaries: tuple[BoundaryPairDelta, ...]


class CrossComponentEdge(WireModel):
    importer: ModuleName
    imported: ModuleName
    importer_component: ComponentName
    imported_component: ComponentName


class StructuralChangesV4(DetailedStructuralChanges):
    """Structural changes with the cross-component edges each side lacks."""

    cross_component_edges_added: tuple[CrossComponentEdge, ...]
    cross_component_edges_removed: tuple[CrossComponentEdge, ...]


class CodeMetricsComparisonV4(WireModel):
    """Published 0.4.0 comparison with explicit architecture deltas."""

    schema_version: Literal["assay-code-metrics-comparison/0.4.0"] = (
        "assay-code-metrics-comparison/0.4.0"
    )
    before: CodeMetricsReportV3
    after: CodeMetricsReportV3
    deltas: tuple[DetailedMetricDelta, ...]
    architecture_deltas: ArchitectureDeltas
    new_code: NewCodeMetrics
    structural_changes: StructuralChangesV4


# Report 0.4.0 and comparison 0.5.0 carry graphs of more than one language.
# A Python module keeps its dotted name; other languages' extractors choose
# ids that cannot collide with one (a Python name never contains "/" or "::").
Language = Literal["python", "rust", "typescript"]
LANGUAGES: tuple[Language, ...] = ("python", "rust", "typescript")
LANGUAGE_EXTENSIONS: Mapping[Language, tuple[str, ...]] = {
    "python": (".py",),
    "rust": (".rs",),
    "typescript": (".ts", ".tsx", ".mts", ".cts"),
}


def language_of(path: str) -> Language | None:
    """The supported language a snapshot path's extension names, if any."""
    for language in LANGUAGES:
        if path.endswith(LANGUAGE_EXTENSIONS[language]):
            return language
    return None


ModuleId = Annotated[str, StringConstraints(pattern=r"^[^\x00-\x1F\x7F]+$")]
PackageName = Annotated[str, StringConstraints(pattern=r"^[^\x00-\x1F\x7F]+$")]


class ModuleEntryV2(ModuleEntry):
    """A first-party module, its source path, and the language it is written in."""

    module: ModuleId
    language: Language

    @model_validator(mode="after")
    def python_name(self) -> Self:
        if self.language == "python":
            _module_name(self.module)
        return self


class ImportEdgeV2(ImportEdge):
    importer: ModuleId
    imported: ModuleId


class ExternalDependencyV2(ExternalDependency):
    module: ModuleId
    package: PackageName


class ModuleGraphV2(ModuleGraph):
    modules: tuple[ModuleEntryV2, ...]
    edges: tuple[ImportEdgeV2, ...]
    external_dependencies: tuple[ExternalDependencyV2, ...]


class ModuleCouplingV4(ModuleCouplingV3):
    module: ModuleId


class ComponentCouplingV4(ComponentCouplingV3):
    modules: tuple[ModuleId, ...]


class ModuleComponentV2(ModuleComponent):
    module: ModuleId


class ComponentMetricsReportV2(WireModel):
    module_coupling: tuple[ModuleCouplingV4, ...]
    component_coupling: tuple[ComponentCouplingV4, ...]
    module_components: tuple[ModuleComponentV2, ...]
    boundaries: tuple[BoundaryPair, ...]


class StronglyConnectedComponentV2(StronglyConnectedComponent):
    modules: tuple[ModuleId, ...]


class CycleReportV4(CycleReportV3):
    components: tuple[StronglyConnectedComponentV2, ...]
    modules_in_cycles: tuple[ModuleId, ...]


class ModuleVisibilityV4(ModuleVisibilityV3):
    module: ModuleId


class PropagationReportV4(PropagationReportV3):
    module_visibility: tuple[ModuleVisibilityV4, ...]


class ArchitectureReportV4(ArchitectureReportV3):
    """The 0.3.0 architecture shape over a graph whose modules name their language."""

    graph: ModuleGraphV2
    module_coupling: tuple[ModuleCouplingV4, ...]
    component_coupling: tuple[ComponentCouplingV4, ...]
    module_components: tuple[ModuleComponentV2, ...]
    cycles: CycleReportV4
    propagation: PropagationReportV4


class LanguageCoverage(WireModel):
    """How much of one language's source the graph extraction reached.

    ``files_seen`` counts snapshot files with the language's extensions and
    ``files_analyzed`` those an analyzer read. A language without a graph
    extractor analyzes none, so every file it sees is without a module.
    """

    language: Language
    files_seen: int
    files_analyzed: int
    modules_discovered: int
    files_without_module: tuple[RepoPath, ...]


class SnapshotCoverageV2(WireModel):
    """One coverage entry per supported language, in name order, zeros included."""

    languages: tuple[LanguageCoverage, ...]


class ExistingMetricsV2(WireModel):
    """The Python analyzers' metrics over the snapshot's Python files.

    Every analyzer here reads Python only, so each value is null, and the
    maintainability index map empty, when the snapshot has no Python file.
    """

    radon_sloc: int | None
    radon_lloc: int | None
    radon_cc: int | None
    radon_halstead_volume: float | None
    complexipy_cognitive: int | None
    grimp_imports: int | None
    ruff_violations: int | None
    ruff_magic_values: int | None
    mypy_errors: int | None
    jscpd_clones: int | None
    jscpd_duplicated_lines: int | None
    maintainability_index: Mapping[RepoPath, float] = Field(
        json_schema_extra={"additionalProperties": False}
    )
    maintainability_index_mean: float | None


class CodeMetricsReportV4(WireModel):
    """Absolute snapshot report whose graph and coverage name each module's language."""

    schema_version: Literal["assay-code-metrics-report/0.4.0"] = "assay-code-metrics-report/0.4.0"
    existing_metrics: ExistingMetricsV2
    architecture: ArchitectureReportV4
    coverage: SnapshotCoverageV2
    configuration: ResolvedConfiguration
    versions: ToolVersions


class NewCodeMetricsV2(WireModel):
    """Metrics of added Python lines; null when the after side has no Python file."""

    new_lines: int | None
    new_duplicated_lines: int | None
    new_max_nesting_depth: int | None


class ModuleCouplingDeltaV2(ModuleCouplingDelta):
    module: ModuleId


class ArchitectureDeltasV2(ArchitectureDeltas):
    modules: tuple[ModuleCouplingDeltaV2, ...]


class CrossComponentEdgeV2(CrossComponentEdge):
    importer: ModuleId
    imported: ModuleId


class StructuralChangesV5(StructuralChangesV4):
    modules_added: tuple[ModuleId, ...]
    modules_removed: tuple[ModuleId, ...]
    edges_added: tuple[ImportEdgeV2, ...]
    edges_removed: tuple[ImportEdgeV2, ...]
    cycles_created: tuple[tuple[ModuleId, ...], ...]
    cycles_resolved: tuple[tuple[ModuleId, ...], ...]
    cross_component_edges_added: tuple[CrossComponentEdgeV2, ...]
    cross_component_edges_removed: tuple[CrossComponentEdgeV2, ...]


class CodeMetricsComparisonV5(WireModel):
    """Comparison of two 0.4.0 reports.

    A Python-analyzer delta's side is null when that side has no Python file,
    and its ``delta`` null when either side is.
    """

    schema_version: Literal["assay-code-metrics-comparison/0.5.0"] = (
        "assay-code-metrics-comparison/0.5.0"
    )
    before: CodeMetricsReportV4
    after: CodeMetricsReportV4
    deltas: tuple[DetailedMetricDelta, ...]
    architecture_deltas: ArchitectureDeltasV2
    new_code: NewCodeMetricsV2
    structural_changes: StructuralChangesV5
