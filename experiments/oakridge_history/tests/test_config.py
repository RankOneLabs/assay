from __future__ import annotations

from pathlib import Path

from assay.cli import _code_metrics_config
from oakridge_history.config import (
    Err,
    Ok,
    load_code_metrics_config,
    load_components,
    load_scope,
    load_snapshots,
)


def test_committed_inputs_load_and_match_assay_cli() -> None:
    snapshots = load_snapshots()
    scope = load_scope()
    components = load_components()
    config = load_code_metrics_config()
    assert isinstance(snapshots, Ok)
    assert isinstance(scope, Ok)
    assert isinstance(components, Ok)
    assert isinstance(config, Ok)
    assert len(snapshots.value) == 6
    assert snapshots.value[-1].provisional
    assert len(scope.value.implementation_roots) == 5
    assert config.value.allow_unmatched_patterns
    config_path = Path(__file__).parents[1] / "code-metrics.yaml"
    assert config.value == _code_metrics_config(str(config_path))


def test_loader_returns_contextual_error(tmp_path: Path) -> None:
    path = tmp_path / "snapshots.yaml"
    path.write_text("snapshots:\n  - id: broken\n", encoding="utf-8")
    result = load_snapshots(path)
    assert isinstance(result, Err)
    assert result.error.file == str(path)
    assert result.error.key == "snapshots[0].sha"
    assert result.error.detail


def test_missing_file_returns_error(tmp_path: Path) -> None:
    result = load_scope(tmp_path / "missing.yaml")
    assert isinstance(result, Err)
    assert result.error.key == "$"


def test_unknown_snapshot_field_is_rejected(tmp_path: Path) -> None:
    source = Path(__file__).parents[1] / "snapshots.yaml"
    path = tmp_path / "snapshots.yaml"
    path.write_text(
        source.read_text(encoding="utf-8").replace("provisional: true", "provisonal: true"),
        encoding="utf-8",
    )
    result = load_snapshots(path)
    assert isinstance(result, Err)
    assert result.error.file == str(path)
    assert result.error.key == "snapshots[5].provisonal"
    assert "unknown" in result.error.detail


def test_unknown_implementation_root_field_is_rejected(tmp_path: Path) -> None:
    source = Path(__file__).parents[1] / "scope.yaml"
    path = tmp_path / "scope.yaml"
    path.write_text(
        source.read_text(encoding="utf-8").replace(
            "post_rewrite_only: true", "post_rewite_only: true"
        ),
        encoding="utf-8",
    )
    result = load_scope(path)
    assert isinstance(result, Err)
    assert result.error.file == str(path)
    assert result.error.key == "implementation_roots[4].post_rewite_only"
    assert "unknown" in result.error.detail
