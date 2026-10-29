"""Offline code diff and retained-trace measures for extension attempts."""

from __future__ import annotations

import base64
import contextlib
import shutil
import subprocess
import tempfile
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict
from workflow_edit.metrics import metrics_config

from assay.canonical import digest_bytes
from assay.code_metrics import compare
from assay.code_metrics.cli_snapshot import snapshot_directory
from assay.code_metrics.models import CodeMetricsComparisonV7
from assay.store import ObjectStore
from code_extension.ledger import AttemptRow


class _Wire(BaseModel):
    model_config = ConfigDict(extra="ignore")


class _RawArtifact(_Wire):
    schema_version: Literal["assay-pier-raw-artifact/0.1.0"]
    checksum: str
    byte_length: int
    content_base64: str


class _ToolCall(_Wire):
    name: str
    arguments: dict[str, object] | None = None
    exit_code: int | None = None


class _Submission(_Wire):
    self_assessed_verdict: Literal["complete", "incomplete", "unsure"] | None = None
    checks_performed: str | None = None
    remaining_work: str | None = None


class _Turn(_Wire):
    tool_calls: tuple[_ToolCall, ...] = ()
    submission: _Submission | None = None


class _Event(_Wire):
    kind: str
    turn: int | str | None = None


class _Trajectory(_Wire):
    turns: tuple[_Turn, ...] = ()
    events: tuple[_Event, ...] = ()


@dataclass(frozen=True)
class TraceMeasures:
    tool_usage: tuple[tuple[str, int], ...]
    files_inspected: tuple[str, ...]
    retries: int
    self_assessed_verdict: Literal["complete", "incomplete", "unsure"] | None
    self_report_agrees: bool | None
    checks_performed: str | None
    remaining_work: str | None


@dataclass(frozen=True)
class DiffMeasures:
    comparison: CodeMetricsComparisonV7
    changed_paths: tuple[str, ...]
    unnecessary_paths: tuple[str, ...]
    added_lines: int
    removed_lines: int


@dataclass(frozen=True)
class SecondaryMeasures:
    diff: DiffMeasures | None
    duration_seconds: float | None
    prompt_tokens: float | None
    completion_tokens: float | None
    cost_amount: float | None
    cost_currency: str | None
    cost_coverage: str
    tool_usage: tuple[tuple[str, int], ...]
    files_inspected: tuple[str, ...]
    retries: int
    self_assessed_verdict: Literal["complete", "incomplete", "unsure"] | None
    self_report_agrees: bool | None
    trace_available: bool = False


class InvalidPatch(ValueError):
    """A retained partial artifact is not an applicable unified git patch."""


def artifact_bytes(store: ObjectStore, ref: str) -> bytes:
    """Open a retained Pier envelope and verify its original bytes."""
    artifact = _RawArtifact.model_validate_json(store.read_bytes(ref))
    payload = base64.b64decode(artifact.content_base64, validate=True)
    if len(payload) != artifact.byte_length or digest_bytes(payload) != artifact.checksum:
        raise ValueError("retained artifact bytes differ from their checksum")
    return payload


def measure_pair(
    before: Path, after: Path, *, dependencies: Path | None = None,
    expected_change_paths: frozenset[str] = frozenset(),
) -> DiffMeasures:
    """Measure two local trees; the locked toolchain must have been installed earlier."""
    before_snapshot, _ = snapshot_directory(before)
    after_snapshot, _ = snapshot_directory(after)
    comparison = compare(
        before_snapshot, after_snapshot, config=metrics_config(dependencies)
    )
    changed = tuple(sorted(
        path for path in before_snapshot.keys() | after_snapshot.keys()
        if before_snapshot.get(path) != after_snapshot.get(path)
    ))
    return DiffMeasures(
        comparison, changed,
        tuple(path for path in changed if path not in expected_change_paths),
        comparison.patch.added_lines, comparison.patch.removed_lines,
    )


def measure_patch(
    fixture_tree: Path, patch: bytes, *, dependencies: Path | None = None,
    expected_change_paths: frozenset[str] = frozenset(),
) -> DiffMeasures:
    """Apply a retained patch to a copy of a committed fixture tree; never fetch."""
    if patch and not patch.startswith(b"diff --git "):
        raise InvalidPatch("retained patch lacks a git diff header")
    with tempfile.TemporaryDirectory() as temporary:
        before = Path(temporary) / "before"
        after = Path(temporary) / "after"
        shutil.copytree(fixture_tree, before)
        shutil.copytree(fixture_tree, after)
        if patch:
            subprocess.run(
                ["git", "apply", "--allow-empty", "-"], cwd=after,
                input=patch, capture_output=True, check=True,
            )
        return measure_pair(
            before, after, dependencies=dependencies,
            expected_change_paths=expected_change_paths,
        )


def trace_measures(trajectory_bytes: bytes, *, passed: bool | None) -> TraceMeasures:
    trajectory = _Trajectory.model_validate_json(trajectory_bytes)
    calls = [call for turn in trajectory.turns for call in turn.tool_calls]
    tools = Counter(call.name for call in calls)
    inspected = {
        path for call in calls if call.name == "read_file" and call.arguments is not None
        for path in (call.arguments.get("path"),)
        if isinstance(path, str)
    }
    requests = Counter(
        str(event.turn) for event in trajectory.events if event.kind == "model_request"
    )
    retries = sum(max(0, count - 1) for count in requests.values())
    submissions = [turn.submission for turn in trajectory.turns if turn.submission is not None]
    self_report = submissions[-1] if submissions else None
    assessment = self_report.self_assessed_verdict if self_report else None
    agrees = None
    if assessment in ("complete", "incomplete") and passed is not None:
        agrees = (assessment == "complete") == passed
    return TraceMeasures(
        tuple(sorted(tools.items())), tuple(sorted(inspected)), retries,
        assessment, agrees,
        self_report.checks_performed if self_report else None,
        self_report.remaining_work if self_report else None,
    )


def measure_attempt(
    row: AttemptRow, store: ObjectStore, *, fixture_tree: Path,
    dependencies: Path | None = None, expected_change_paths: frozenset[str] = frozenset(),
) -> SecondaryMeasures:
    """Combine retained patch, trace and accounting without grading the attempt."""
    patch = (
        artifact_bytes(store, row.reference.patch_ref)
        if row.reference.patch_ref is not None else None
    )
    diff = None
    if patch is not None:
        with contextlib.suppress(subprocess.CalledProcessError, InvalidPatch):
            diff = measure_patch(
                fixture_tree, patch, dependencies=dependencies,
                expected_change_paths=expected_change_paths,
            )
    trace = None
    if row.reference.raw_trajectory_ref is not None:
        trace = trace_measures(
            artifact_bytes(store, row.reference.raw_trajectory_ref),
            passed=row.passed if row.verdict is not None else None,
        )
    usage: Mapping[str, float | None] = row.accounting.usage or {}
    return SecondaryMeasures(
        diff, row.duration_seconds,
        usage.get("prompt_tokens"), usage.get("completion_tokens"),
        row.accounting.amount, row.accounting.currency, row.accounting.coverage,
        trace.tool_usage if trace else (), trace.files_inspected if trace else (),
        trace.retries if trace else 0,
        trace.self_assessed_verdict if trace else None,
        trace.self_report_agrees if trace else None,
        trace is not None,
    )
