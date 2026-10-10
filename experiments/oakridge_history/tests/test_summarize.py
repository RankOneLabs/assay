from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from assay.canonical import canonical_json
from assay.code_metrics import CodeMetricsConfig, analyze, compare
from assay.code_metrics.components import ComponentConfig
from oakridge_history import summarize as summary_module
from oakridge_history.config import Ok
from oakridge_history.model import ComponentSpec, ImplementationRoot, ScopeSpec, SnapshotSpec


def _store(
    output: Path, specs: tuple[SnapshotSpec, ...], config: CodeMetricsConfig,
    comparison_config: CodeMetricsConfig | None = None,
) -> None:
    report = analyze({}, config=config)
    comparison = compare({}, {}, config=comparison_config or config)
    for spec in specs:
        directory = output / "snapshots" / spec.id
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "code-metrics.json").write_bytes(
            canonical_json(report.model_dump(mode="json"))
        )
        (directory / "metadata.json").write_text(json.dumps({
            "commit_sha": spec.sha, "author_date": "2026-01-01T00:00:00+00:00",
            "pr_number": spec.pr_number, "archived_include_paths": [],
        }))
    pairs = output / "comparisons"
    pairs.mkdir(exist_ok=True)
    for before, after in zip(specs, specs[1:], strict=False):
        (pairs / f"{before.id}--{after.id}.json").write_bytes(
            canonical_json(comparison.model_dump(mode="json"))
        )


def test_summarize_reads_stored_files_and_checks_union(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    specs = tuple(SnapshotSpec(f"s{i}", f"{i:040x}", None, i, "event", "reason")
                  for i in range(1, 7))
    root = ImplementationRoot("kbbl/core/", "kbbl", "kbbl/core")
    scope = ScopeSpec(("kbbl/core",), (), (root,))
    component = ComponentSpec("role", ("kbbl/core/role/**",))
    empty = CodeMetricsConfig(allow_unmatched_patterns=True)
    config = CodeMetricsConfig(components=(ComponentConfig("role", component.patterns),),
                               allow_unmatched_patterns=True)
    monkeypatch.setattr(summary_module, "load_snapshots", lambda: Ok(specs))
    monkeypatch.setattr(summary_module, "load_scope", lambda: Ok(scope))
    monkeypatch.setattr(summary_module, "load_components", lambda: Ok(()))
    _store(tmp_path, specs, empty)
    summary_module.summarize(tmp_path)
    assert sorted(p.name for p in (tmp_path / "summary").iterdir()) == [
        "components.csv", "coverage.csv", "system.csv",
    ]
    with (tmp_path / "summary/system.csv").open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 6
    assert rows[0]["radon_sloc"] == ""
    assert "implementations: none; languages: none" in (tmp_path / "summary.md").read_text()
    monkeypatch.setattr(summary_module, "load_components", lambda: Ok((component,)))
    with pytest.raises(RuntimeError, match="s1: stored result used a different component config"):
        summary_module.summarize(tmp_path)
    _store(tmp_path, specs, config)
    with pytest.raises(RuntimeError, match="union coverage guard: kbbl/core/role"):
        summary_module.summarize(tmp_path)


def test_summarize_rejects_stale_stored_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    specs = tuple(SnapshotSpec(f"s{i}", f"{i:040x}", None, i, "event", "reason")
                  for i in range(1, 3))
    scope = ScopeSpec((), (), ())
    empty = CodeMetricsConfig(allow_unmatched_patterns=True)
    monkeypatch.setattr(summary_module, "load_scope", lambda: Ok(scope))
    monkeypatch.setattr(summary_module, "load_components", lambda: Ok(()))
    _store(tmp_path, specs, empty)
    repinned = (specs[0], SnapshotSpec("s2", "f" * 40, None, 2, "event", "reason"))
    monkeypatch.setattr(summary_module, "load_snapshots", lambda: Ok(repinned))
    with pytest.raises(RuntimeError, match=f"s2: stored result is for {specs[1].sha}"):
        summary_module.summarize(tmp_path)
    monkeypatch.setattr(summary_module, "load_snapshots", lambda: Ok(specs))
    other = CodeMetricsConfig(clone_min_lines=7, allow_unmatched_patterns=True)
    _store(tmp_path, specs, empty, comparison_config=other)
    with pytest.raises(RuntimeError, match="s1 → s2: comparison does not match stored reports"):
        summary_module.summarize(tmp_path)
