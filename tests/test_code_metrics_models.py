"""Code metrics report wire contracts."""

from typing import get_args, get_type_hints

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaValidationError
from pydantic import ValidationError

from assay.code_metrics.models import (
    ArchitectureReport,
    CodeMetricsComparison,
    CodeMetricsReport,
    ComponentCoupling,
    CycleReport,
    ExistingMetrics,
    MetricDelta,
    ModuleGraph,
    NewCodeMetrics,
    PropagationReport,
    ResolvedConfiguration,
    SnapshotCoverage,
    StructuralChanges,
    ToolVersions,
)


def _report() -> CodeMetricsReport:
    return CodeMetricsReport(
        existing_metrics=ExistingMetrics(
            radon_sloc=1,
            radon_lloc=1,
            radon_cc=0,
            radon_halstead_volume=0.0,
            complexipy_cognitive=0,
            grimp_imports=None,
            ruff_violations=0,
            ruff_magic_values=0,
            mypy_errors=0,
            jscpd_clones=0,
            jscpd_duplicated_lines=0,
            maintainability_index={"solo.py": 100.0},
            maintainability_index_mean=100.0,
        ),
        architecture=ArchitectureReport(
            graph=ModuleGraph(modules=(), edges=(), external_dependencies=()),
            module_coupling=(),
            component_coupling=(),
            module_components={},
            boundaries=(),
            cycles=CycleReport(components=(), cyclic_component_count=0, modules_in_cycles=0),
            propagation=PropagationReport(module_visibility=(), propagation_cost=None),
        ),
        coverage=SnapshotCoverage(
            python_files_seen=1,
            python_files_analyzed=1,
            modules_discovered=0,
            files_without_module=("solo.py",),
        ),
        configuration=ResolvedConfiguration(
            clone_min_lines=5,
            clone_min_tokens=50,
            ruff_ignore=(),
            components={},
            excluded_directories=(),
        ),
        versions=ToolVersions(assay="0.1.0", python="3.13", tools={"grimp": "3.17"}),
    )


def test_report_and_comparison_round_trip_and_closed_frozen_wire() -> None:
    report = _report()
    comparison = CodeMetricsComparison(
        before=report,
        after=report,
        deltas=(
            MetricDelta(
                metric="radon.mi",
                before=100.0,
                after=100.0,
                delta=0.0,
                provenance="shared_file_mean",
                shared_files=("solo.py",),
            ),
        ),
        new_code=NewCodeMetrics(new_lines=0, new_duplicated_lines=0, new_max_nesting_depth=0),
        structural_changes=StructuralChanges(
            added_modules=(), removed_modules=(), added_edges=(), removed_edges=()
        ),
    )
    for model in (report, comparison):
        assert type(model).model_validate(model.model_dump()) == model
        with pytest.raises(ValidationError):
            type(model).model_validate({**model.model_dump(), "unknown": 1})
        with pytest.raises(ValidationError):
            model.schema_version = "changed"  # type: ignore[misc,assignment]
    assert not any(
        hasattr(report, field)
        for field in ("new_lines", "new_duplicated_lines", "new_max_nesting_depth")
    )
    assert "radon.mi" not in ExistingMetrics.model_fields
    assert "maintainability_index_delta" not in ExistingMetrics.model_fields


def test_denominator_fields_are_nullable() -> None:
    for model, names in (
        (
            ComponentCoupling,
            (
                "instability",
                "relational_cohesion",
                "internal_dependency_density",
                "internal_edge_share",
            ),
        ),
        (PropagationReport, ("propagation_cost",)),
        (ExistingMetrics, ("maintainability_index_mean",)),
    ):
        hints = get_type_hints(model)
        for name in names:
            assert set(get_args(hints[name])) == {float, type(None)}


@pytest.mark.parametrize(("section", "field", "valid", "invalid"), [
    ("configuration", "components", {"core": ["src/pkg"]}, {"bad key": []}),
    ("versions", "tools", {"grimp": "3.17"}, {"bad key": "3.17"}),
    ("existing_metrics", "maintainability_index", {"pkg/a.py": 100.0}, {"/a.py": 100.0}),
    ("architecture", "module_components", {"pkg.a": "core"}, {"pkg..a": "core"}),
])
def test_mapping_keys_match_published_schema(section, field, valid, invalid) -> None:
    schema = CodeMetricsReport.model_json_schema()
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    payload = _report().model_dump(mode="json")
    payload[section][field] = valid
    validator.validate(payload)
    CodeMetricsReport.model_validate(payload)
    payload[section][field] = invalid
    with pytest.raises(SchemaValidationError):
        validator.validate(payload)
    with pytest.raises(ValidationError):
        CodeMetricsReport.model_validate(payload)
