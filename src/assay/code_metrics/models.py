"""Typed code-metrics wire reports and the legacy metric API's small shared types."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Literal, NamedTuple

from pydantic import Field, StringConstraints

from assay.models import Identifier, NonEmpty, WireModel

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


class _Config(NamedTuple):
    clone_min_lines: int
    clone_min_tokens: int
    ruff_ignore: tuple[str, ...]


ModuleName = Annotated[
    str, StringConstraints(pattern=r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")
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


class BoundaryPair(WireModel):
    importer_component: ComponentName
    imported_component: ComponentName
    edge_count: int


class ModuleComponent(WireModel):
    module: ModuleName
    path: RepoPath | None
    component: ComponentName


class ComponentMetricsReport(WireModel):
    module_coupling: tuple[ModuleCoupling, ...]
    component_coupling: tuple[ComponentCoupling, ...]
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
    mypy_errors: int
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
