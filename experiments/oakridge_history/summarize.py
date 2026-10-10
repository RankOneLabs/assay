"""Build deterministic tables from stored reports, comparisons, and metadata."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any

from assay.code_metrics.models import CodeMetricsComparisonV6, CodeMetricsReportV5

from .config import Err, load_components, load_scope, load_snapshots
from .guards import check_union_coverage

METRICS = (
    "radon_sloc", "radon_lloc", "radon_cc", "radon_halstead_volume",
    "complexipy_cognitive", "grimp_imports", "ruff_violations", "ruff_magic_values",
    "mypy_errors", "jscpd_clones", "jscpd_duplicated_lines",
    "maintainability_index_mean",
)
SYSTEM_COLUMNS = (
    "snapshot_id", "commit_sha", "date", "pr_number", "resolved_include_paths",
    "files_seen", "files_analyzed", "modules_discovered", "files_without_module",
    "module_count", "edge_count", "unmatched_patterns", "cycle_count",
    "modules_in_cycles", *METRICS,
)
COMPONENT_COLUMNS = ("snapshot_id", "component", "component_module_count")
COVERAGE_COLUMNS = (
    "snapshot_id", "language", "files_seen", "files_analyzed",
    "modules_discovered", "files_without_module",
)
PAIR_COLUMNS = (
    "before_snapshot_id", "after_snapshot_id", "modules_added", "modules_removed",
    "edges_added", "edges_removed", "components_added", "components_removed",
    "cycles_created", "cycles_resolved", "cross_component_edges_added",
    "cross_component_edges_removed", "new_lines", "new_duplicated_lines",
    "new_max_nesting_depth",
)


def _csv(path: Path, columns: tuple[str, ...], rows: list[dict[str, Any]]) -> None:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: _cell(row.get(key)) for key in columns})
    path.write_text(stream.getvalue(), encoding="utf-8")


def _cell(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (tuple, list)):
        return ";".join(str(item) for item in value)
    return value


def _presence(metadata: dict[str, Any], report: CodeMetricsReportV5, scope: Any) -> str:
    paths = set(metadata["archived_include_paths"])
    implementations = sorted({root.implementation for root in scope.implementation_roots
                              if root.include_path in paths})
    languages = sorted(item.language for item in report.coverage.languages if item.files_seen)
    implementation_label = ", ".join(implementations) or "none"
    language_label = ", ".join(languages) or "none"
    return f"implementations: {implementation_label}; languages: {language_label}"


def summarize(output: Path) -> None:
    snapshots = load_snapshots()
    scope = load_scope()
    components = load_components()
    for result in (snapshots, scope, components):
        if isinstance(result, Err):
            raise RuntimeError(f"{result.error.file}: {result.error.key}: {result.error.detail}")
    assert not isinstance(snapshots, Err)
    assert not isinstance(scope, Err)
    assert not isinstance(components, Err)
    # Assay stores each component's patterns sorted.
    expected_components = {item.name: tuple(sorted(item.patterns)) for item in components.value}
    reports: dict[str, CodeMetricsReportV5] = {}
    metadata: dict[str, dict[str, Any]] = {}
    system_rows: list[dict[str, Any]] = []
    component_rows: list[dict[str, Any]] = []
    coverage_rows: list[dict[str, Any]] = []
    for spec in snapshots.value:
        directory = output / "snapshots" / spec.id
        report = CodeMetricsReportV5.model_validate_json(
            (directory / "code-metrics.json").read_bytes()
        )
        meta: dict[str, Any] = json.loads((directory / "metadata.json").read_bytes())
        if meta["commit_sha"] != spec.sha:
            raise RuntimeError(
                f"{spec.id}: stored result is for {meta['commit_sha']}, manifest pins {spec.sha}"
            )
        if dict(report.configuration.components) != expected_components:
            raise RuntimeError(f"{spec.id}: stored result used a different component config")
        reports[spec.id] = report
        metadata[spec.id] = meta
        coverage = report.coverage.languages
        component_counts = {entry.component: entry.module_count
                            for entry in report.architecture.component_coupling}
        base = {
            "snapshot_id": spec.id, "commit_sha": meta["commit_sha"],
            "date": meta["author_date"][:10], "pr_number": meta["pr_number"],
            "resolved_include_paths": meta["archived_include_paths"],
            "files_seen": sum(item.files_seen for item in coverage),
            "files_analyzed": sum(item.files_analyzed for item in coverage),
            "modules_discovered": sum(item.modules_discovered for item in coverage),
            "files_without_module": sum(len(item.files_without_module) for item in coverage),
            "module_count": report.architecture.module_count,
            "edge_count": report.architecture.first_party_edge_count,
            "unmatched_patterns": tuple(
                item.pattern for item in report.configuration.unmatched_patterns
            ),
            "cycle_count": report.architecture.cycles.cyclic_scc_count,
            "modules_in_cycles": report.architecture.cycles.cyclic_module_count,
            **{metric: getattr(report.existing_metrics, metric) for metric in METRICS},
        }
        system_rows.append(base)
        for component, count in sorted(component_counts.items()):
            component_rows.append({"snapshot_id": spec.id, "component": component,
                                   "component_module_count": count})
        for language in coverage:
            coverage_rows.append({
                "snapshot_id": spec.id, "language": language.language,
                "files_seen": language.files_seen, "files_analyzed": language.files_analyzed,
                "modules_discovered": language.modules_discovered,
                "files_without_module": len(language.files_without_module),
            })
    failures = check_union_coverage(
        components.value, scope.value,
        (tuple(item.pattern for item in reports[spec.id].configuration.unmatched_patterns)
         for spec in snapshots.value),
    )
    if failures:
        raise RuntimeError(f"union coverage guard: {failures[0].pattern}: {failures[0].detail}")
    lines = [
        "# Oakridge history summary", "",
        "Deltas are descriptive; code presence and parser coverage can change between snapshots.",
        "",
    ]
    for before, after in zip(snapshots.value, snapshots.value[1:], strict=False):
        comparison = CodeMetricsComparisonV6.model_validate_json(
            (output / "comparisons" / f"{before.id}--{after.id}.json").read_bytes()
        )
        if (comparison.before, comparison.after) != (reports[before.id], reports[after.id]):
            raise RuntimeError(
                f"{before.id} → {after.id}: comparison does not match stored reports"
            )
        changes = comparison.structural_changes
        row: dict[str, Any] = {
            "before_snapshot_id": before.id, "after_snapshot_id": after.id,
            **{key: len(getattr(changes, key)) for key in PAIR_COLUMNS[2:12]},
            **{key: getattr(comparison.new_code, key) for key in PAIR_COLUMNS[12:]},
        }
        lines.extend((
            f"## {before.id} → {after.id}", "",
            f"- Before: {_presence(metadata[before.id], reports[before.id], scope.value)}",
            f"- After: {_presence(metadata[after.id], reports[after.id], scope.value)}",
            f"- Modules: +{row['modules_added']} / -{row['modules_removed']}; "
            f"edges: +{row['edges_added']} / -{row['edges_removed']}.",
            f"- Components: +{row['components_added']} / -{row['components_removed']}; "
            f"cycles: +{row['cycles_created']} / -{row['cycles_resolved']}.",
            f"- Cross-component edges: +{row['cross_component_edges_added']} / "
            f"-{row['cross_component_edges_removed']}.",
            f"- New code: lines {_cell(row['new_lines'])}, duplicated lines "
            f"{_cell(row['new_duplicated_lines'])}, maximum nesting depth "
            f"{_cell(row['new_max_nesting_depth'])}.",
            "", "| Metric | Before | After | Delta |", "| --- | ---: | ---: | ---: |",
            *(f"| {item.metric} | {_cell(item.before)} | {_cell(item.after)} | "
              f"{_cell(item.delta)} |"
              for item in comparison.deltas), "",
        ))
    summary = output / "summary"
    summary.mkdir(parents=True, exist_ok=True)
    _csv(summary / "system.csv", SYSTEM_COLUMNS, system_rows)
    _csv(summary / "components.csv", COMPONENT_COLUMNS, component_rows)
    _csv(summary / "coverage.csv", COVERAGE_COLUMNS, coverage_rows)
    (output / "summary.md").write_text("\n".join(lines), encoding="utf-8")
