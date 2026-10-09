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


def test_summarize_reads_stored_files_and_checks_union(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    specs = tuple(SnapshotSpec(f"s{i}", f"{i:040x}", None, i, "event", "reason")
                  for i in range(1, 7))
    root = ImplementationRoot("kbbl/core/", "kbbl", "kbbl/core")
    scope = ScopeSpec(("kbbl/core",), (), (root,))
    component = ComponentSpec("role", ("kbbl/core/role/**",))
    config = CodeMetricsConfig(components=(ComponentConfig("role", component.patterns),),
                               allow_unmatched_patterns=True)
    report = analyze({}, config=config)
    comparison = compare({}, {}, config=config)
    monkeypatch.setattr(summary_module, "load_snapshots", lambda: Ok(specs))
    monkeypatch.setattr(summary_module, "load_scope", lambda: Ok(scope))
    monkeypatch.setattr(summary_module, "load_components", lambda: Ok(()))
    for spec in specs:
        directory = tmp_path / "snapshots" / spec.id
        directory.mkdir(parents=True)
        (directory / "code-metrics.json").write_bytes(
            canonical_json(report.model_dump(mode="json"))
        )
        (directory / "metadata.json").write_text(json.dumps({
            "commit_sha": spec.sha, "author_date": "2026-01-01T00:00:00+00:00",
            "pr_number": spec.pr_number, "archived_include_paths": [],
        }))
    pairs = tmp_path / "comparisons"
    pairs.mkdir()
    for before, after in zip(specs, specs[1:], strict=False):
        (pairs / f"{before.id}--{after.id}.json").write_bytes(
            canonical_json(comparison.model_dump(mode="json"))
        )
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
    with pytest.raises(RuntimeError, match="union coverage guard: kbbl/core/role"):
        summary_module.summarize(tmp_path)
