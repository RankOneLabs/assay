"""Audit the graph evidence carried by the supplied named fixtures."""

import json
from pathlib import Path

import pytest
from code_metrics_fixtures import (
    FIXTURE_A,
    FIXTURE_C_AFTER,
    FIXTURE_C_BEFORE,
    FIXTURE_COUPLING,
    FIXTURE_D_AFTER,
    FIXTURE_D_BEFORE,
    FIXTURE_H,
    FIXTURE_I,
    FIXTURE_J,
)

from assay.code_metrics.cycles import analyze_cycles
from assay.code_metrics.graph import build_module_graph
from assay.code_metrics.models import METRICS, Snapshot
from assay.code_metrics.propagation import analyze_propagation


@pytest.mark.parametrize(
    ("snapshot", "modules", "edges", "scalar"),
    [
        (
            FIXTURE_A,
            ("pkg", "pkg.a", "pkg.b", "pkg.c"),
            (("pkg.a", "pkg.b"), ("pkg.b", "pkg.c")),
            7 / 16,
        ),
        (
            FIXTURE_C_BEFORE,
            ("pkg", "pkg.a", "pkg.b", "pkg.c"),
            (("pkg.a", "pkg.b"), ("pkg.b", "pkg.c")),
            0,
        ),
        (
            FIXTURE_C_AFTER,
            ("pkg", "pkg.a", "pkg.b", "pkg.c"),
            (("pkg.a", "pkg.b"), ("pkg.b", "pkg.c"), ("pkg.c", "pkg.a")),
            1,
        ),
        (
            FIXTURE_D_BEFORE,
            ("pkg", "pkg.a", "pkg.b", "pkg.c"),
            (("pkg.a", "pkg.b"), ("pkg.b", "pkg.c"), ("pkg.c", "pkg.a")),
            1,
        ),
        (
            FIXTURE_D_AFTER,
            ("pkg", "pkg.a", "pkg.b", "pkg.c"),
            (("pkg.a", "pkg.b"), ("pkg.b", "pkg.c")),
            0,
        ),
        (FIXTURE_H, ("pkg", "pkg.isolated"), (), 0),
        (FIXTURE_I, ("pkg", "pkg.a"), (), 0),
        (FIXTURE_J, ("pkg", "pkg.a", "pkg.b"), (("pkg.a", "pkg.b"),), 0),
        (
            FIXTURE_COUPLING,
            ("pkg", "pkg.a", "pkg.b", "pkg.c", "pkg.d"),
            (("pkg.a", "pkg.b"), ("pkg.b", "pkg.c"), ("pkg.d", "pkg.a")),
            0,
        ),
    ],
)
def test_fixture_graph_evidence(
    snapshot: Snapshot,
    modules: tuple[str, ...],
    edges: tuple[tuple[str, str], ...],
    scalar: float,
) -> None:
    graph, _ = build_module_graph(snapshot)
    assert tuple(entry.module for entry in graph.modules) == modules
    assert tuple((edge.importer, edge.imported) for edge in graph.edges) == edges
    if snapshot is FIXTURE_A:
        assert analyze_propagation(graph).propagation_cost == pytest.approx(scalar)
    else:
        assert analyze_cycles(graph).cyclic_component_count == scalar


def test_every_public_metric_has_a_golden_case() -> None:
    golden = json.loads(
        (Path(__file__).parent / "fixtures/code_metrics_golden.json").read_text(encoding="utf-8")
    )
    coverage = {metric: tuple(sorted(golden)) for metric in METRICS}
    assert coverage
    assert all(cases for cases in coverage.values())
    assert all(set(case["metrics"]) == set(coverage) for case in golden.values())
