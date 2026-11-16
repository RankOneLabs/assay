"""Typed retained evidence. Archive parsing and replay exceptions stop at this boundary."""

from __future__ import annotations

import json
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, NewType

from pydantic import BaseModel, ConfigDict

from assay.models import ExecutionOutcome
from assay.store import ObjectStore
from code_extension.config import RunConfiguration
from code_extension.diagnose import TYPECHECK
from code_extension.fact_shapes.cells import FactId, RepositoryPath, Shape
from code_extension.fixture import materialize
from code_extension.ledger import _evaluation_detail, _Output, _Trace
from code_extension.metrics import artifact_bytes
from code_extension.reachability import plan_rows
from code_extension.run import _plan_dir
from code_extension.status import _manifest

VariantId = NewType("VariantId", str)
type Assessment = Literal["complete", "incomplete", "unsure"]


@dataclass(frozen=True)
class HolderSpec:
    paths: tuple[RepositoryPath, ...]
    fact_lines: tuple[str, ...]


@dataclass(frozen=True)
class Fact:
    id: FactId
    titles: tuple[str, ...]
    shape: Shape
    holder: HolderSpec


@dataclass(frozen=True)
class Variant:
    id: VariantId
    facts: tuple[Fact, ...]


class Wire(BaseModel):
    model_config = ConfigDict(extra="ignore")


class ToolCall(Wire):
    name: str
    arguments: dict[str, object] | None = None
    returned_text: str | None = None


class Submission(Wire):
    self_assessed_verdict: Assessment | None = None


class Turn(Wire):
    tool_calls: tuple[ToolCall, ...] = ()
    submission: Submission | None = None


class Event(Wire):
    kind: str
    cause: str | None = None
    error: str | None = None


class Trajectory(Wire):
    turns: tuple[Turn, ...] = ()
    events: tuple[Event, ...] = ()


class Group(Wire):
    status: str
    stdout: str = ""
    stderr: str = ""


class Preflight(Wire):
    status: str
    cause: str | None = None


class Evaluator(Wire):
    groups: dict[str, Group]
    preflight: Preflight | None = None


@dataclass(frozen=True)
class Attempt:
    cell: str
    variant: Variant
    stop: str
    terminal: str
    verdict: str | None
    outcome: str
    evaluator: Evaluator | None
    patch: str
    calls: tuple[ToolCall, ...]
    self_assessed_verdict: Assessment | None
    image_digest: str
    request_timeout: bool


@dataclass(frozen=True)
class ReadError:
    operation: str
    cell: str
    detail: str


@dataclass(frozen=True)
class Ok[T]:
    value: T


@dataclass(frozen=True)
class Err:
    error: ReadError


type Result[T] = Ok[T] | Err


def assemble(
    row: Mapping[str, object],
    variant: Variant,
    evaluator: Evaluator | None,
    patch: str,
    trajectory: Trajectory,
    image_digest: str,
) -> Attempt:
    """Assemble evidence without IO, excluding submission and all later calls."""
    calls: list[ToolCall] = []
    assessment: Assessment | None = None
    submitted = False
    for turn in trajectory.turns:
        if submitted:
            break
        if turn.submission is not None:
            assessment = turn.submission.self_assessed_verdict
        for call in turn.tool_calls:
            if call.name == "submit_output":
                submitted = True
                break
            calls.append(call)
    verdict = row.get("verdict")
    return Attempt(
        str(row["cell"]),
        variant,
        str(row["stop"]),
        str(row["terminal"]),
        str(verdict) if verdict is not None else None,
        str(row["outcome"]),
        evaluator,
        patch,
        tuple(calls),
        assessment,
        image_digest,
        any(
            e.kind == "stopped"
            and e.cause == "transport_failure"
            and e.error
            in {
                "TimeoutException",
                "ReadTimeout",
                "WriteTimeout",
                "ConnectTimeout",
                "PoolTimeout",
            }
            for e in trajectory.events
        ),
    )


def read_attempts(
    store_path: Path,
    plan_digest: str,
    variants: Mapping[str, Variant],
) -> Result[tuple[Attempt, ...]]:
    """Read each dispatched attempt using the existing archive readers, never checkout data."""
    cell = ""
    operation = "plan_rows"
    try:
        rows = plan_rows(store_path, plan_digest)
        store = ObjectStore(store_path)
        directory = _plan_dir(store, plan_digest)
        config = RunConfiguration.load(directory / "config.json")
        journal = directory / "attempts.jsonl"
        records = (
            [json.loads(line) for line in journal.read_text().splitlines()]
            if journal.exists()
            else []
        )
        found = _manifest(store, config, records)
        attempts: list[Attempt] = []
        for row in rows:
            cell = str(row["cell"])
            operation = "retained_attempt"
            evaluator = None
            patch = ""
            trajectory = Trajectory()
            if found is not None and cell in found[1].execution_records:
                manifest = found[1]
                execution = ExecutionOutcome.model_validate_json(
                    store.read_bytes(manifest.execution_records[cell])
                )
                detail, _ = _evaluation_detail(cell, manifest, store)
                if detail is not None:
                    evaluator = Evaluator.model_validate_json(
                        store.read_bytes(detail.evaluator_record_ref)
                    )
                refs: dict[str, str] = {}
                if execution.trace_ref:
                    refs = _Trace.model_validate_json(
                        store.read_bytes(execution.trace_ref)
                    ).artifact_refs
                patch_ref: str | None
                trajectory_ref: str | None
                if execution.output_ref:
                    output = _Output.model_validate_json(store.read_bytes(execution.output_ref))
                    patch_ref, trajectory_ref = output.patch_ref, output.raw_trajectory_ref
                else:
                    patch_ref = refs.get("stopped/candidate.patch") or refs.get("candidate.patch")
                    trajectory_ref = refs.get("trajectory.json") or refs.get(
                        "stopped/trajectory.json"
                    )
                if patch_ref:
                    patch = artifact_bytes(store, patch_ref).decode("utf-8")
                if trajectory_ref:
                    trajectory = Trajectory.model_validate_json(
                        artifact_bytes(store, trajectory_ref)
                    )
            attempts.append(
                assemble(row, variants[cell], evaluator, patch, trajectory, config.image_digest)
            )
        return Ok(tuple(attempts))
    except Exception as error:
        return Err(ReadError(operation, cell, str(error)))


type Runner = Callable[[str, Path, Sequence[str]], str]


def replay_typecheck(
    attempt: Attempt,
    repository: Mapping[str, str],
    runner: Runner,
) -> Result[str | None]:
    """Replay only typecheck failures on the retained variant plus patch in its pinned image."""
    preflight = attempt.evaluator.preflight if attempt.evaluator else None
    if preflight is None or not (preflight.cause or "").startswith("typecheck_"):
        return Ok(None)
    try:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            materialize(root, repository, attempt.patch)
            return Ok(runner(attempt.image_digest, root, TYPECHECK))
    except Exception as error:
        return Err(ReadError("replay_typecheck", attempt.cell, str(error)))
