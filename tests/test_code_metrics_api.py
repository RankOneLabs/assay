"""Public report and comparison behavior."""

import ast
import json
from pathlib import Path

import pytest
from code_metrics_fixtures import stub_jscpd
from jsonschema import Draft202012Validator

from assay.code_metrics import analyze, compare, graph, measure
from assay.code_metrics.api import CodeMetricsConfig
from assay.code_metrics.components import ComponentConfig
from assay.code_metrics.errors import EmptyComponentPattern
from assay.code_metrics.models import utf8_source

PACKAGE = {"src/pkg/__init__.py": "", "src/pkg/a.py": "x = 1\n"}


@pytest.fixture(autouse=True)
def stub_clones(monkeypatch: pytest.MonkeyPatch) -> None:
    stub_jscpd(monkeypatch)


def test_absolute_report_and_partial_graph() -> None:
    report = analyze({"solo.py": "x = 1\n"})
    assert report.architecture.graph.modules == ()
    assert report.architecture.propagation.propagation_cost is None
    assert report.existing_metrics.grimp_imports is None
    assert report.coverage.languages[0].files_without_module == ("solo.py",)
    assert "excluded_directories" not in CodeMetricsConfig.__dataclass_fields__
    assert report.configuration.excluded_directories == ()


def test_package_initializer_wins_over_same_named_module() -> None:
    report = analyze({"pkg.py": "", "pkg/__init__.py": "", "pkg/a.py": "x = 1\n"})
    paths = {entry.module: entry.path for entry in report.architecture.graph.modules}
    assert paths["pkg"] == "pkg/__init__.py"
    assert report.coverage.languages[0].files_without_module == ("pkg.py",)


def test_component_zero_denominators_and_unmapped_file() -> None:
    report = analyze(
        {**PACKAGE, "loose.py": "pass\n"},
        config=CodeMetricsConfig(components=(ComponentConfig("alpha", ("src/pkg/a.py",)),)),
    )
    alpha = next(c for c in report.architecture.component_coupling if c.component == "alpha")
    assert alpha.instability is None
    assert alpha.internal_dependency_density is None
    assert alpha.internal_edge_share is None
    assert report.coverage.languages[0].files_without_module == ("loose.py",)


def test_compared_component_may_exist_on_one_side() -> None:
    after = {**PACKAGE, "src/pkg/plugins/__init__.py": "", "src/pkg/plugins/x.py": "pass\n"}
    config = CodeMetricsConfig(
        components=(
            ComponentConfig("core", ("src/pkg/a.py",)),
            ComponentConfig("plugins", ("src/pkg/plugins/*",)),
        )
    )
    comparison = compare(PACKAGE, after, config=config)
    added = comparison.structural_changes
    removed = compare(after, PACKAGE, config=config).structural_changes
    assert added.components_added == ("plugins",)
    assert removed.components_removed == ("plugins",)
    assert comparison.before.configuration.unmatched_patterns[0].model_dump() == {
        "component": "plugins", "pattern": "src/pkg/plugins/*"
    }
    assert comparison.after.configuration.unmatched_patterns == ()
    with pytest.raises(EmptyComponentPattern, match="missing"):
        compare(
            PACKAGE,
            after,
            config=CodeMetricsConfig(components=(ComponentConfig("gone", ("missing/*",)),)),
        )


def test_allow_unmatched_patterns_on_analyze_and_compare() -> None:
    config = CodeMetricsConfig(
        components=(
            ComponentConfig("present", ("src/pkg/a.py",)),
            ComponentConfig("missing", ("missing/*",)),
        ),
        allow_unmatched_patterns=True,
    )
    with pytest.raises(
        EmptyComponentPattern,
        match=r"configure components: component missing pattern 'missing/\*' matched zero modules",
    ):
        analyze(PACKAGE, config=CodeMetricsConfig(components=config.components))
    report = analyze(PACKAGE, config=config)
    assert report.schema_version == "assay-code-metrics-report/0.5.0"
    assert report.configuration.allow_unmatched_patterns is True
    expected = ({"component": "missing", "pattern": "missing/*"},)
    assert tuple(item.model_dump() for item in report.configuration.unmatched_patterns) == expected
    comparison = compare(PACKAGE, PACKAGE, config=config)
    assert comparison.schema_version == "assay-code-metrics-comparison/0.6.0"
    assert tuple(
        item.model_dump() for item in comparison.before.configuration.unmatched_patterns
    ) == expected
    assert tuple(
        item.model_dump() for item in comparison.after.configuration.unmatched_patterns
    ) == expected


@pytest.mark.parametrize("allow", [False, True])
def test_one_sided_pattern_resolution_is_reported_on_its_own_side(allow: bool) -> None:
    after = {**PACKAGE, "src/pkg/plugins/__init__.py": "", "src/pkg/plugins/x.py": "pass\n"}
    config = CodeMetricsConfig(
        components=(ComponentConfig("plugins", ("src/pkg/plugins/*",)),),
        allow_unmatched_patterns=allow,
    )
    comparison = compare(PACKAGE, after, config=config)
    assert comparison.before.configuration.unmatched_patterns[0].model_dump() == {
        "component": "plugins", "pattern": "src/pkg/plugins/*"
    }
    assert comparison.after.configuration.unmatched_patterns == ()


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
    version = result.schema_version.rsplit("/", 1)[1].rsplit(".", 1)[0]
    schema_path = (
        Path(__file__).parents[1]
        / "schemas"
        / f"assay-code-metrics-comparison-v{version}.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(result.model_dump(mode="json"))


def test_uncollapsed_direct_import_count(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeGraph:
        modules = {"pkg", "pkg.a"}

        def find_modules_directly_imported_by(self, module: str) -> set[str]:
            return {"ext.a", "ext.b"} if module == "pkg.a" else set()

    monkeypatch.setattr(graph.grimp, "build_graph", lambda *args, **kwargs: FakeGraph())
    report = analyze(
        {
            "src/pkg/__init__.py": "",
            "src/pkg/a.py": "import ext.a\nimport ext.b\n",
        }
    )
    assert report.existing_metrics.grimp_imports == 2
    assert len(report.architecture.graph.external_dependencies) == 1


def test_unicode_and_unimportable_names_do_not_abort_analysis() -> None:
    snapshot = {
        "pkg/__init__.py": "from .. import nothing\n",
        "pkg/café.py": "import pkg\n",
        "pkg/my-mod.py": "x = 1\n",
        "my-pkg/__init__.py": "",
    }
    report = analyze(snapshot)
    assert [entry.module for entry in report.architecture.graph.modules] == ["pkg", "pkg.café"]
    assert report.coverage.languages[0].files_without_module == (
        "my-pkg/__init__.py",
        "pkg/my-mod.py",
    )
    assert report.existing_metrics.mypy_errors is None
    result = compare(PACKAGE | {"pkg/__init__.py": ""}, snapshot)
    assert "pkg.café" in result.structural_changes.modules_added


@pytest.mark.parametrize("coding", ["latin-1", "no-such-codec"])
def test_non_utf8_coding_declaration_does_not_abort_analysis(coding: str) -> None:
    source = f"# -*- coding: {coding} -*-\nimport pkg\nname = 'café'\n"
    report = analyze({"pkg/__init__.py": "", "pkg/m.py": source})
    assert [entry.module for entry in report.architecture.graph.modules] == ["pkg", "pkg.m"]
    assert [(edge.importer, edge.imported) for edge in report.architecture.graph.edges] == [
        ("pkg.m", "pkg")
    ]
    assert report.existing_metrics.mypy_errors == 0
    plain_source = source.replace(f"coding: {coding}", "notes")
    plain = analyze({"pkg/__init__.py": "", "pkg/m.py": plain_source})
    assert report.existing_metrics.ruff_violations == plain.existing_metrics.ruff_violations


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            "#!/usr/bin/env python\n# coding: latin-1\r\nx = 1\n",
            "#!/usr/bin/env python\n# Coding: latin-1\r\nx = 1\n",
        ),
        ("# coding: utf-8\nx = 1\n", "# coding: utf-8\nx = 1\n"),
        # Python splits physical lines only at CR and LF, so the form feed
        # leaves the declaration on line two.
        ("# header\n\f# coding: latin-1\nx = 1\n", "# header\n\f# Coding: latin-1\nx = 1\n"),
        ("# header\r# coding: latin-1\rx = 1\r", "# header\r# Coding: latin-1\rx = 1\r"),
        # Grimp reads line two even inside a string; the string stays terminated.
        ('DOC = """\n# coding: latin-1"""\n', 'DOC = """\n# Coding: latin-1"""\n'),
        # U+2028 is not a physical line break, so nothing here starts a line.
        ('x = "a\u2028# coding: latin-1"\n', 'x = "a\u2028# coding: latin-1"\n'),
        ("# coding: latin-1 coding: cp1252\n", "# Coding: latin-1 Coding: cp1252\n"),
    ],
)
def test_utf8_source_disarms_only_foreign_declarations(source: str, expected: str) -> None:
    assert utf8_source(source) == expected
    ast.parse(utf8_source(source))


def test_coding_text_inside_a_string_is_analyzed() -> None:
    source = 'DOC = """\n# coding: latin-1"""\nimport pkg\n'
    report = analyze({"pkg/__init__.py": "", "pkg/m.py": source})
    assert [(edge.importer, edge.imported) for edge in report.architecture.graph.edges] == [
        ("pkg.m", "pkg")
    ]


def test_snapshot_of_only_unimportable_packages_is_measured() -> None:
    report = analyze({"my-pkg/__init__.py": "x = 1\n"})
    assert report.architecture.graph.modules == ()
    assert report.coverage.languages[0].files_without_module == ("my-pkg/__init__.py",)
    assert report.existing_metrics.mypy_errors == 0


def test_other_languages_leave_python_results_unchanged() -> None:
    mixed = {**PACKAGE, "web/app.ts": "export const x = 1;\n", "core/src/lib.rs": "mod a;\n"}
    python_only = analyze(PACKAGE)
    report = analyze(mixed)
    assert report.existing_metrics == python_only.existing_metrics
    graph = report.architecture.graph
    python_modules = tuple(entry for entry in graph.modules if entry.language == "python")
    assert python_modules == python_only.architecture.graph.modules
    assert graph.edges == python_only.architecture.graph.edges
    coverage = {entry.language: entry for entry in report.coverage.languages}
    assert coverage["python"] == python_only.coverage.languages[0]
    assert coverage["typescript"].modules_discovered == 1
    # Rust has no extractor yet, so its file is seen without a module.
    assert coverage["rust"].model_dump() == {
        "language": "rust",
        "files_seen": 1,
        "files_analyzed": 0,
        "modules_discovered": 0,
        "files_without_module": ("core/src/lib.rs",),
    }


def test_snapshot_without_python_has_null_python_metrics() -> None:
    typescript = {"web/app.ts": "export const x = 1;\n"}
    report = analyze(typescript)
    metrics = report.existing_metrics.model_dump()
    assert metrics.pop("maintainability_index") == {}
    assert set(metrics.values()) == {None}
    comparison = compare(typescript, PACKAGE)
    assert {entry.before for entry in comparison.deltas} == {None}
    assert {entry.delta for entry in comparison.deltas} == {None}
    assert comparison.new_code.new_lines == 1
    reverse = compare(PACKAGE, typescript)
    assert reverse.new_code.model_dump() == dict.fromkeys(
        ("new_lines", "new_duplicated_lines", "new_max_nesting_depth")
    )
    # The legacy mapping still counts a side without Python as zero.
    assert measure(typescript, PACKAGE)["radon.sloc"] == 1
