"""Read-only Oakridge measurement runner.

``snapshot_directory`` is imported from ``assay.code_metrics.cli_snapshot``;
that helper is not exported by ``assay.code_metrics.__all__``.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from assay.canonical import canonical_json
from assay.code_metrics import CodeMetricsConfig, analyze, compare
from assay.code_metrics.cli_snapshot import snapshot_directory
from assay.code_metrics.models import Snapshot
from oakridge_history.config import (
    Err,
    load_code_metrics_config,
    load_components,
    load_scope,
    load_snapshots,
)
from oakridge_history.extract import archive_commit
from oakridge_history.git_resolve import ResolvedCommit, resolve_commit
from oakridge_history.guards import check_containment, check_pairwise_overlap, check_rooting
from oakridge_history.metadata import build_metadata
from oakridge_history.model import ComponentSpec, ScopeSpec, SnapshotSpec
from oakridge_history.summarize import summarize

OUTPUT = Path(__file__).with_name("results")


def _load_snapshot(
    repo: Path, spec: SnapshotSpec, scope: ScopeSpec
) -> tuple[Snapshot, ResolvedCommit, tuple[str, ...]]:
    resolved = resolve_commit(repo, spec, scope)
    if isinstance(resolved, Err):
        raise RuntimeError(
            f"{resolved.error.snapshot_id} {resolved.error.sha}: {resolved.error.detail}"
        )
    with tempfile.TemporaryDirectory(prefix="oakridge-archive-") as temporary:
        target = Path(temporary) / "tree"
        extracted = archive_commit(repo, resolved.value, target)
        if isinstance(extracted, Err):
            raise RuntimeError(f"{spec.id} {spec.sha}: {extracted.error.detail}")
        snapshot, exclusions = snapshot_directory(target, exclude=scope.exclude_globs)
    return snapshot, resolved.value, exclusions


def run_snapshot(
    repo: Path, spec: SnapshotSpec, scope: ScopeSpec,
    config: CodeMetricsConfig, components: tuple[ComponentSpec, ...], output: Path,
) -> Snapshot:
    snapshot, commit, exclusions = _load_snapshot(repo, spec, scope)
    report = analyze(snapshot, config=config)
    unmatched = tuple(item.pattern for item in report.configuration.unmatched_patterns)
    failures = check_containment(components, scope, commit.archived_include_paths, unmatched)
    if failures:
        failure = failures[0]
        raise RuntimeError(f"{spec.id}: containment guard: {failure.pattern}: {failure.detail}")
    metadata = build_metadata(commit, scope, exclusions, report)
    destination = output / "snapshots" / spec.id
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "code-metrics.json").write_bytes(canonical_json(report.model_dump(mode="json")))
    (destination / "metadata.json").write_bytes(canonical_json(metadata))
    return snapshot


def run(repo: Path, selected: tuple[str, ...], output: Path = OUTPUT) -> None:
    snapshots = load_snapshots()
    scope = load_scope()
    config = load_code_metrics_config()
    components = load_components()
    for result in (snapshots, scope, config, components):
        if isinstance(result, Err):
            raise RuntimeError(f"{result.error.file}: {result.error.key}: {result.error.detail}")
    assert not isinstance(snapshots, Err)
    assert not isinstance(scope, Err)
    assert not isinstance(config, Err)
    assert not isinstance(components, Err)
    failures = (*check_rooting(components.value, scope.value),
                *check_pairwise_overlap(components.value))
    if failures:
        raise RuntimeError(f"pattern guard: {failures[0].pattern}: {failures[0].detail}")
    by_id = {item.id: item for item in snapshots.value}
    unknown = set(selected) - by_id.keys()
    if unknown:
        raise RuntimeError(f"unknown snapshot id: {sorted(unknown)[0]}")
    chosen = selected or tuple(by_id)
    cache: dict[str, Snapshot] = {}
    for snapshot_id in chosen:
        spec = by_id[snapshot_id]
        cache[snapshot_id] = run_snapshot(
            repo, spec, scope.value, config.value, components.value, output
        )
    for before, after in zip(snapshots.value, snapshots.value[1:], strict=False):
        if before.id not in chosen and after.id not in chosen:
            continue
        if not all((output / "snapshots" / item.id / "code-metrics.json").exists()
                   for item in (before, after)):
            continue
        for spec in (before, after):
            if spec.id not in cache:
                cache[spec.id] = _load_snapshot(repo, spec, scope.value)[0]
        comparison = compare(cache[before.id], cache[after.id], config=config.value)
        target = output / "comparisons"
        target.mkdir(parents=True, exist_ok=True)
        (target / f"{before.id}--{after.id}.json").write_bytes(
            canonical_json(comparison.model_dump(mode="json"))
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--oakridge", type=Path)
    parser.add_argument("--snapshot", action="append", default=[])
    parser.add_argument("--summarize", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.summarize:
            if args.oakridge or args.snapshot:
                parser.error("--summarize cannot be combined with --oakridge or --snapshot")
            summarize(OUTPUT)
        else:
            if args.oakridge is None:
                parser.error("--oakridge is required unless --summarize is used")
            run(args.oakridge, tuple(args.snapshot))
    except (RuntimeError, OSError, ValueError, json.JSONDecodeError,
            subprocess.CalledProcessError) as error:
        print(f"oakridge history: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
