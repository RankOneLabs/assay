"""Rust module graphs from Cargo manifests and tree-sitter parses."""

import pytest
from code_metrics_fixtures import stub_jscpd

from assay.code_metrics import analyze, compare
from assay.code_metrics.api import CodeMetricsConfig
from assay.code_metrics.components import ComponentConfig
from assay.code_metrics.errors import AnalyzerFailed
from assay.code_metrics.rust import extract_rust_graph

# A virtual workspace of two packages whose crate names differ from their
# directories, the way a workspace commonly names crates.
WORKSPACE = {
    "Cargo.toml": '[workspace]\nmembers = ["crates/model", "crates/cli"]\n',
    "crates/model/Cargo.toml": (
        '[package]\nname = "workflow-model"\nversion = "0.1.0"\n\n[dependencies]\nserde = "1"\n'
    ),
    "crates/model/src/lib.rs": (
        "pub mod values;\n"
        "mod store;\n"
        '#[path = "legacy/old_names.rs"]\nmod names;\n'
        "pub use values::Value;\n"
        "#[cfg(test)]\nmod tests {\n    use super::*;\n    use crate::store::Store;\n}\n"
    ),
    "crates/model/src/values.rs": (
        "use serde::Serialize;\n"
        "#[derive(Serialize)]\npub struct Value;\n"
        "pub fn names() -> Vec<String> { Vec::new() }\n"
    ),
    "crates/model/src/store/mod.rs": "mod disk;\npub struct Store;\n",
    "crates/model/src/store/disk.rs": (
        "use super::super::values;\n"
        'pub fn save() { values::names(); std::fs::write("x", "y").ok(); }\n'
    ),
    "crates/model/src/legacy/old_names.rs": "pub fn all() {}\n",
    "crates/model/src/orphan.rs": "pub fn unused() {}\n",
    "crates/model/tests/semantics.rs": "use workflow_model::Value;\n",
    "crates/cli/Cargo.toml": (
        '[package]\nname = "workflow-cli"\nversion = "0.1.0"\n\n'
        '[dependencies]\nworkflow-model = { path = "../model" }\n'
    ),
    "crates/cli/src/main.rs": (
        "mod codegen;\nuse crate::codegen as generate;\nfn main() { generate::emit(); }\n"
    ),
    "crates/cli/src/codegen.rs": (
        "pub fn emit() { let _ = vec![workflow_model::values::names()]; }\n"
    ),
}


@pytest.fixture(autouse=True)
def stub_clones(monkeypatch: pytest.MonkeyPatch) -> None:
    stub_jscpd(monkeypatch)


def _rust(snapshot: dict[str, str]) -> tuple[dict[str, str], dict[str, str]]:
    return (
        {path: text for path, text in snapshot.items() if path.endswith(".rs")},
        {path: text for path, text in snapshot.items() if path.endswith("Cargo.toml")},
    )


def test_rust_modules_follow_mod_declarations_from_each_target() -> None:
    extraction = extract_rust_graph(*_rust(WORKSPACE))
    assert [entry.module for entry in extraction.graph.modules] == [
        "crates/cli/src/codegen.rs",
        "crates/cli/src/main.rs",
        "crates/model/src/legacy/old_names.rs",
        "crates/model/src/lib.rs",
        "crates/model/src/store/disk.rs",
        "crates/model/src/store/mod.rs",
        "crates/model/src/values.rs",
        "crates/model/tests/semantics.rs",
    ]
    assert {entry.language for entry in extraction.graph.modules} == {"rust"}
    assert extraction.coverage.files_without_module == ("crates/model/src/orphan.rs",)


def test_rust_edges_resolve_paths_to_the_files_that_hold_them() -> None:
    graph = extract_rust_graph(*_rust(WORKSPACE)).graph
    assert [(edge.importer, edge.imported) for edge in graph.edges] == [
        # A crate named by its manifest name, inside a macro's tokens.
        ("crates/cli/src/codegen.rs", "crates/model/src/values.rs"),
        # A path through a `use` alias of a module.
        ("crates/cli/src/main.rs", "crates/cli/src/codegen.rs"),
        # A re-export, and an inline test module's `use crate::...`; its
        # `use super::*` names its own file and adds no edge.
        ("crates/model/src/lib.rs", "crates/model/src/store/mod.rs"),
        ("crates/model/src/lib.rs", "crates/model/src/values.rs"),
        ("crates/model/src/store/disk.rs", "crates/model/src/values.rs"),
        # A test target naming its package's library.
        ("crates/model/tests/semantics.rs", "crates/model/src/lib.rs"),
    ]
    # Only declared dependencies and sysroot crates are external; `Vec::new`
    # names neither.
    assert [(item.module, item.package) for item in graph.external_dependencies] == [
        ("crates/model/src/store/disk.rs", "std"),
        ("crates/model/src/values.rs", "serde"),
    ]


def test_rust_reports_components_cycles_and_tool_versions() -> None:
    cyclic = {
        "Cargo.toml": '[package]\nname = "app"\nversion = "0.1.0"\n',
        "src/lib.rs": "mod a;\nmod b;\n",
        "src/a.rs": "use crate::b::g;\npub fn f() {}\n",
        "src/b.rs": "pub fn g() { crate::a::f(); }\n",
    }
    config = CodeMetricsConfig(components=(ComponentConfig("core", ("src/*.rs",)),))
    report = analyze(cyclic, config=config)
    assert report.architecture.cycles.largest_cyclic_scc_size == 2
    assert report.coverage.languages[1].modules_discovered == 3
    assert report.versions.tools["tree-sitter-rust"] == "0.24.2"
    after = {**cyclic, "src/b.rs": "pub fn g() {}\n"}
    result = compare(cyclic, after, config=config)
    assert result.structural_changes.cycles_resolved == (("src/a.rs", "src/b.rs"),)
    assert "tree-sitter" not in analyze({"pkg/__init__.py": ""}).versions.tools


def test_rust_without_a_manifest_has_no_modules() -> None:
    extraction = extract_rust_graph({"src/lib.rs": "mod a;\n", "src/a.rs": ""}, {})
    assert extraction.graph.modules == ()
    assert extraction.coverage.files_without_module == ("src/a.rs", "src/lib.rs")


def test_unparsable_manifest_is_an_analyzer_failure() -> None:
    with pytest.raises(AnalyzerFailed, match="parse Cargo.toml"):
        extract_rust_graph({"src/lib.rs": ""}, {"Cargo.toml": "[package\n"})
