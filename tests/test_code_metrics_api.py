"""Public report and comparison behavior."""

import pytest

from assay.code_metrics import analyze, compare, measure, tools
from assay.code_metrics.api import CodeMetricsConfig
from assay.code_metrics.components import ComponentConfig

PACKAGE = {"src/pkg/__init__.py": "", "src/pkg/a.py": "x = 1\n"}


@pytest.fixture(autouse=True)
def stub_clones(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        tools,
        "_jscpd",
        lambda *args: {"jscpd.clones": 0, "jscpd.duplicated_lines": 0, "cloned_lines": {}},
    )


def test_absolute_report_and_partial_graph() -> None:
    report = analyze({"solo.py": "x = 1\n"})
    assert report.architecture.graph.modules == ()
    assert report.architecture.propagation.propagation_cost is None
    assert report.existing_metrics.grimp_imports is None
    assert report.coverage.files_without_module == ("solo.py",)


def test_component_zero_denominators_and_unmapped_file() -> None:
    report = analyze(
        {**PACKAGE, "loose.py": "pass\n"},
        config=CodeMetricsConfig(components=(ComponentConfig("alpha", ("src/pkg/a.py",)),)),
    )
    alpha = next(c for c in report.architecture.component_coupling if c.component == "alpha")
    assert alpha.instability is None
    assert alpha.internal_dependency_density is None
    assert alpha.internal_edge_share is None
    assert report.coverage.files_without_module == ("loose.py",)


def test_mi_shared_intersection_and_explicit_structure() -> None:
    before = {
        "src/pkg/__init__.py": "",
        "src/pkg/a.py": "x = 1\n",
        "src/pkg/old.py": "x = 2\n",
    }
    after = {
        "src/pkg/__init__.py": "",
        "src/pkg/a.py": "x = 3\n",
        "src/pkg/new.py": "x = 4\n",
        "src/pkg/second.py": "x = 5\n",
    }
    result = compare(before, after)
    mi = next(delta for delta in result.deltas if delta.metric == "radon.mi")
    assert mi.delta == measure(before, after)["radon.mi"]
    assert mi.shared_files == ("src/pkg/__init__.py", "src/pkg/a.py")
    assert mi.shared_file_count == 2
    assert result.structural_changes.modules_added == ("pkg.new", "pkg.second")
    assert result.structural_changes.modules_removed == ("pkg.old",)
    assert result.model_dump()["structural_changes"]["modules_added"] == ("pkg.new", "pkg.second")
    assert result.new_code.new_lines == 3
