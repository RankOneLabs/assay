"""Architecture deltas and cross-component structural changes between two snapshots."""

import json
from pathlib import Path

import pytest
from code_metrics_fixtures import (
    FIXTURE_B_AFTER,
    FIXTURE_B_BEFORE,
    FIXTURE_F_AFTER,
    FIXTURE_F_BEFORE,
    FIXTURE_G_AFTER,
    FIXTURE_G_BEFORE,
    FIXTURE_K_AFTER,
    FIXTURE_K_BEFORE,
    stub_jscpd,
)
from jsonschema import Draft202012Validator

from assay.code_metrics import analyze, compare
from assay.code_metrics.api import CodeMetricsConfig
from assay.code_metrics.architecture import (
    analyze_architecture,
    compare_architecture,
    structural_changes,
)
from assay.code_metrics.components import ComponentConfig
from assay.code_metrics.graph import build_module_graph
from assay.code_metrics.models import (
    ArchitectureDeltas,
    ArchitectureReportV3,
    ComponentMetricDeltas,
    CrossComponentEdge,
    Snapshot,
)

SCHEMAS = Path(__file__).parents[1] / "schemas"
ALPHA_AB_BETA_C = (
    ComponentConfig("alpha", ("src/pkg/a.py", "src/pkg/b.py")),
    ComponentConfig("beta", ("src/pkg/c.py",)),
)
ALPHA_AB_BETA_CD = (
    ComponentConfig("alpha", ("src/pkg/a.py", "src/pkg/b.py")),
    ComponentConfig("beta", ("src/pkg/c.py", "src/pkg/d.py")),
)
ALPHA_ABC = (ComponentConfig("alpha", ("src/pkg/a.py", "src/pkg/b.py", "src/pkg/c.py")),)
ALPHA_ABC_BETA_D = (*ALPHA_ABC, ComponentConfig("beta", ("src/pkg/d.py",)))


def _architecture(
    snapshot: Snapshot, configuration: tuple[ComponentConfig, ...] = ()
) -> ArchitectureReportV3:
    graph, _ = build_module_graph(snapshot)
    return analyze_architecture(graph, configuration)


def _deltas(
    before: Snapshot, after: Snapshot, configuration: tuple[ComponentConfig, ...] = ()
) -> ArchitectureDeltas:
    return compare_architecture(
        _architecture(before, configuration), _architecture(after, configuration)
    )


def _component(deltas: ArchitectureDeltas, name: str) -> ComponentMetricDeltas:
    return next(item.metrics for item in deltas.components if item.component == name)


def _triple(value: object) -> tuple[object, object, object]:
    return (value.before, value.after, value.delta)  # type: ignore[attr-defined]


def test_added_edge_moves_module_coupling_propagation_and_edge_count() -> None:
    deltas = _deltas(FIXTURE_B_BEFORE, FIXTURE_B_AFTER)
    modules = {item.module: item for item in deltas.modules}
    assert tuple(modules) == ("pkg", "pkg.a", "pkg.b", "pkg.c")
    assert _triple(modules["pkg.a"].fan_out) == (1, 2, 1)
    assert _triple(modules["pkg.c"].fan_in) == (0, 1, 1)
    assert _triple(modules["pkg.b"].fan_in) == (1, 1, 0)
    cost = deltas.system.propagation_cost
    assert (cost.before, cost.after) == (5 / 16, 6 / 16)
    assert cost.delta == pytest.approx(1 / 16)
    assert _triple(deltas.system.first_party_edge_count) == (1, 2, 1)
    # Without a component configuration every module is unassigned, so
    # unassigned -> unassigned never counts as crossing a boundary.
    assert _triple(deltas.system.cross_component_edge_count) == (0, 0, 0)
    assert deltas.boundaries == ()


def test_added_cross_component_edge_moves_coupling() -> None:
    deltas = _deltas(FIXTURE_K_BEFORE, FIXTURE_K_AFTER, ALPHA_AB_BETA_CD)
    alpha, beta = _component(deltas, "alpha"), _component(deltas, "beta")
    assert _triple(alpha.afferent) == (1, 1, 0)
    assert _triple(alpha.efferent) == (1, 2, 1)
    assert _triple(alpha.incoming_edges) == (1, 1, 0)
    assert _triple(alpha.outgoing_edges) == (1, 2, 1)
    assert (alpha.instability.before, alpha.instability.after) == (0.5, pytest.approx(2 / 3))
    assert alpha.instability.delta == pytest.approx(1 / 6)
    # pkg.b already imported pkg.c, so beta gains an incoming edge but no
    # new afferent module: Ca counts distinct importers, not edges.
    assert _triple(beta.afferent) == (1, 1, 0)
    assert _triple(beta.incoming_edges) == (1, 2, 1)
    assert _triple(beta.instability) == (0.5, 0.5, 0.0)
    assert _triple(deltas.system.cross_component_edge_count) == (2, 3, 1)


def test_undefined_instability_has_no_delta() -> None:
    alpha = _component(_deltas(FIXTURE_B_BEFORE, FIXTURE_B_AFTER, ALPHA_AB_BETA_C), "alpha")
    assert _triple(alpha.efferent) == (0, 1, 1)
    assert _triple(alpha.instability) == (None, 1.0, None)


@pytest.mark.parametrize(
    ("before", "after", "configuration", "expected"),
    [
        (
            FIXTURE_F_BEFORE,
            FIXTURE_F_AFTER,
            ALPHA_ABC,
            {
                "relational_cohesion": (2 / 3, 4 / 3, 2 / 3),
                "internal_dependency_density": (1 / 6, 1 / 2, 1 / 3),
                "internal_edge_share": (1.0, 1.0, 0.0),
            },
        ),
        (
            FIXTURE_G_BEFORE,
            FIXTURE_G_AFTER,
            ALPHA_ABC_BETA_D,
            {
                "relational_cohesion": (4 / 3, 1.0, -1 / 3),
                "internal_dependency_density": (1 / 2, 1 / 3, -1 / 6),
                "internal_edge_share": (1.0, 2 / 3, -1 / 3),
            },
        ),
    ],
    ids=["F", "G"],
)
def test_cohesion_deltas(before, after, configuration, expected) -> None:
    alpha = _component(_deltas(before, after, configuration), "alpha")
    for metric, values in expected.items():
        assert _triple(getattr(alpha, metric)) == pytest.approx(values), metric


def test_cross_component_edges_added_and_removed() -> None:
    before = _architecture(FIXTURE_B_BEFORE, ALPHA_AB_BETA_C)
    after = _architecture(FIXTURE_B_AFTER, ALPHA_AB_BETA_C)
    edge = CrossComponentEdge(
        importer="pkg.a", imported="pkg.c", importer_component="alpha", imported_component="beta"
    )
    forward = structural_changes(before, after)
    assert forward.cross_component_edges_added == (edge,)
    assert forward.cross_component_edges_removed == ()
    inverse = structural_changes(after, before)
    assert inverse.cross_component_edges_added == ()
    assert inverse.cross_component_edges_removed == (edge,)


def test_cross_component_edges_follow_owner_changes() -> None:
    graph, _ = build_module_graph(FIXTURE_B_AFTER)
    split = analyze_architecture(graph, ALPHA_AB_BETA_C)
    merged = analyze_architecture(graph, ALPHA_ABC)
    changes = structural_changes(split, merged)
    assert changes.edges_added == changes.edges_removed == ()
    assert changes.cross_component_edges_removed == (
        CrossComponentEdge(
            importer="pkg.a",
            imported="pkg.c",
            importer_component="alpha",
            imported_component="beta",
        ),
    )
    assert changes.cross_component_edges_added == ()


def test_cross_component_edges_sort_by_components_then_modules() -> None:
    before = _architecture(FIXTURE_B_BEFORE, ALPHA_AB_BETA_C)
    after = _architecture(
        {**FIXTURE_B_AFTER, "src/pkg/c.py": "import pkg.b\nimport pkg.a\n"}, ALPHA_AB_BETA_C
    )
    added = structural_changes(before, after).cross_component_edges_added
    assert [
        (item.importer_component, item.imported_component, item.importer, item.imported)
        for item in added
    ] == [
        ("alpha", "beta", "pkg.a", "pkg.c"),
        ("beta", "alpha", "pkg.c", "pkg.a"),
        ("beta", "alpha", "pkg.c", "pkg.b"),
    ]


def test_boundary_pair_deltas_count_a_missing_side_as_zero() -> None:
    forward = _deltas(FIXTURE_B_BEFORE, FIXTURE_B_AFTER, ALPHA_AB_BETA_C)
    assert [
        (item.importer_component, item.imported_component, item.before, item.after, item.delta)
        for item in forward.boundaries
    ] == [("alpha", "beta", 0, 1, 1)]
    inverse = _deltas(FIXTURE_B_AFTER, FIXTURE_B_BEFORE, ALPHA_AB_BETA_C)
    assert [(item.before, item.after, item.delta) for item in inverse.boundaries] == [(1, 0, -1)]


def test_one_sided_entities_have_no_metric_delta() -> None:
    before = {"src/pkg/__init__.py": "", "src/pkg/a.py": ""}
    after = {**before, "src/pkg/plugins/__init__.py": "", "src/pkg/plugins/x.py": ""}
    configuration = (
        ComponentConfig("core", ("src/pkg/a.py",)),
        ComponentConfig("plugins", ("src/pkg/plugins/*",)),
    )
    graphs = build_module_graph(before)[0], build_module_graph(after)[0]
    old, new = (analyze_architecture(g, configuration, require_matches=False) for g in graphs)
    deltas = compare_architecture(old, new)
    assert [item.component for item in deltas.components] == ["core", "unassigned"]
    assert [item.module for item in deltas.modules] == ["pkg", "pkg.a"]
    changes = structural_changes(old, new)
    assert changes.components_added == ("plugins",)
    assert changes.modules_added == ("pkg.plugins", "pkg.plugins.x")


def test_comparison_wires_deltas_and_validates_against_new_schemas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_jscpd(monkeypatch)
    config = CodeMetricsConfig(components=ALPHA_AB_BETA_CD)
    result = compare(FIXTURE_K_BEFORE, FIXTURE_K_AFTER, config=config)
    assert result.schema_version == "assay-code-metrics-comparison/0.4.0"
    assert result.before.schema_version == "assay-code-metrics-report/0.3.0"
    assert result.architecture_deltas == compare_architecture(
        result.before.architecture, result.after.architecture
    )
    assert result.structural_changes.cross_component_edges_added == (
        CrossComponentEdge(
            importer="pkg.b",
            imported="pkg.d",
            importer_component="alpha",
            imported_component="beta",
        ),
    )
    comparison_schema = json.loads(
        (SCHEMAS / "assay-code-metrics-comparison-v0.4.schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator(comparison_schema).validate(result.model_dump(mode="json"))
    report_schema = json.loads(
        (SCHEMAS / "assay-code-metrics-report-v0.3.schema.json").read_text(encoding="utf-8")
    )
    report = analyze(FIXTURE_K_AFTER, config=config)
    Draft202012Validator(report_schema).validate(report.model_dump(mode="json"))
