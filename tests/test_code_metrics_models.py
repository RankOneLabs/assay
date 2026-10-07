"""Code metrics report wire contracts."""

import json
from typing import get_args, get_type_hints

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaValidationError
from pydantic import ValidationError
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from assay.code_metrics.models import (
    ArchitectureReport,
    ArchitectureReportV1,
    CodeMetricsComparison,
    CodeMetricsComparisonV2,
    CodeMetricsReport,
    CodeMetricsReportV2,
    ComponentCoupling,
    CycleReport,
    CycleReportV1,
    ExistingMetrics,
    MetricDelta,
    ModuleComponent,
    ModuleGraph,
    NewCodeMetrics,
    PropagationReport,
    ResolvedConfiguration,
    SnapshotCoverage,
    StructuralChanges,
    ToolVersions,
)
from assay.schema_export import schema_documents


def _report() -> CodeMetricsReportV2:
    return CodeMetricsReportV2(
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
            module_components=(),
            boundaries=(),
            cycles=CycleReport(components=(), cyclic_component_count=0, modules_in_cycles=()),
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
    comparison = CodeMetricsComparisonV2(
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


@pytest.mark.parametrize(
    ("section", "field", "valid", "invalid"),
    [
        ("configuration", "components", {"core": ["src/pkg"]}, {"bad key": []}),
        ("versions", "tools", {"grimp": "3.17"}, {"bad key": "3.17"}),
        ("existing_metrics", "maintainability_index", {"pkg/a.py": 100.0}, {"/a.py": 100.0}),
    ],
)
def test_mapping_keys_match_published_schema(section, field, valid, invalid) -> None:
    schema = CodeMetricsReportV2.model_json_schema()
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    payload = _report().model_dump(mode="json")
    payload[section][field] = valid
    validator.validate(payload)
    CodeMetricsReportV2.model_validate(payload)
    payload[section][field] = invalid
    with pytest.raises(SchemaValidationError):
        validator.validate(payload)
    with pytest.raises(ValidationError):
        CodeMetricsReportV2.model_validate(payload)


def test_architecture_module_components_include_path_on_wire() -> None:
    item = ModuleComponent(module="pkg.a", path="src/pkg/a.py", component="core")
    report = _report().model_copy(
        update={
            "architecture": _report().architecture.model_copy(update={"module_components": (item,)})
        }
    )
    payload = report.model_dump(mode="json")
    Draft202012Validator(CodeMetricsReportV2.model_json_schema()).validate(payload)
    assert CodeMetricsReportV2.model_validate(payload) == report
    payload["architecture"]["module_components"][0]["module"] = "pkg..a"
    with pytest.raises(SchemaValidationError):
        Draft202012Validator(CodeMetricsReportV2.model_json_schema()).validate(payload)
    with pytest.raises(ValidationError):
        CodeMetricsReportV2.model_validate(payload)


def test_cycle_modules_in_cycles_rejects_integer() -> None:
    with pytest.raises(ValidationError):
        CycleReport(components=(), cyclic_component_count=0, modules_in_cycles=0)  # type: ignore[arg-type]


def test_published_v1_shapes_remain_distinct_from_v2() -> None:
    new = _report()
    old_architecture = ArchitectureReportV1(
        **{
            **new.architecture.model_dump(),
            "module_components": {"pkg.a": "core"},
            "cycles": CycleReportV1(components=(), cyclic_component_count=0, modules_in_cycles=0),
        }
    )
    old = CodeMetricsReport(
        **{
            **new.model_dump(exclude={"schema_version", "architecture"}),
            "architecture": old_architecture,
        }
    )
    assert old.schema_version == "assay-code-metrics-report/0.1.0"
    assert new.schema_version == "assay-code-metrics-report/0.2.0"
    assert CodeMetricsReport.model_validate(old.model_dump()) == old
    assert CodeMetricsReportV2.model_validate(new.model_dump()) == new
    with pytest.raises(ValidationError):
        CodeMetricsReportV2.model_validate(old.model_dump())
    with pytest.raises(ValidationError):
        CodeMetricsReport.model_validate(new.model_dump())
    old_comparison = CodeMetricsComparison(
        before=old,
        after=old,
        deltas=(),
        new_code=NewCodeMetrics(new_lines=0, new_duplicated_lines=0, new_max_nesting_depth=0),
        structural_changes=StructuralChanges(
            added_modules=(), removed_modules=(), added_edges=(), removed_edges=()
        ),
    )
    assert old_comparison.schema_version == "assay-code-metrics-comparison/0.1.0"

    new_comparison = CodeMetricsComparisonV2(
        before=new,
        after=new,
        deltas=(),
        new_code=old_comparison.new_code,
        structural_changes=old_comparison.structural_changes,
    )
    documents = {
        name: json.loads(data) for name, data in schema_documents().items()
    }
    registry: Registry = Registry()
    for name, schema in documents.items():
        if name.startswith("assay-code-metrics-"):
            registry = registry.with_resource(
                schema["$id"], Resource.from_contents(schema, default_specification=DRAFT202012)
            )
    for family, old_payload, new_payload in (
        ("report", old.model_dump(mode="json"), new.model_dump(mode="json")),
        (
            "comparison",
            old_comparison.model_dump(mode="json"),
            new_comparison.model_dump(mode="json"),
        ),
    ):
        root = documents[f"assay-code-metrics-{family}.schema.json"]
        old_schema = documents[f"assay-code-metrics-{family}-v0.1.schema.json"]
        new_schema = documents[f"assay-code-metrics-{family}-v0.2.schema.json"]
        validator = Draft202012Validator(root, registry=registry)
        validator.validate(old_payload)
        validator.validate(new_payload)
        Draft202012Validator(old_schema).validate(old_payload)
        Draft202012Validator(new_schema).validate(new_payload)
        with pytest.raises(SchemaValidationError):
            Draft202012Validator(old_schema).validate(new_payload)
        with pytest.raises(SchemaValidationError):
            Draft202012Validator(new_schema).validate(old_payload)
