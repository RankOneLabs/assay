"""Best-effort discovery for stores without an explicit root object.

Discovery is deliberately weaker than verification.  It identifies objects by
their wire discriminators and parses the closed Assay wire types, but it never
turns an observed discriminator into producer attestation or a closure edge.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import ValidationError

from assay.models import (
    EvaluationFailure,
    ExecutionOutcome,
    ExecutionPlan,
    ReportConfig,
    RunManifest,
    StudySnapshot,
)
from assay.references import object_edges
from assay.review.model import (
    CostView,
    ExclusionView,
    JSONObject,
    ReadIssue,
    ReportSummary,
    RunSummary,
    StoreSummary,
)
from assay.schema_validation import schema_validators
from assay.store import ObjectRef, ObjectStore

CACHE_VERSION = 1
DEFAULT_MAX_OBJECTS = 10_000
DEFAULT_MAX_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class IndexedManifest:
    kind: Literal["manifest"]
    ref: str
    value: RunManifest


@dataclass(frozen=True, slots=True)
class IndexedPlan:
    kind: Literal["plan"]
    ref: str
    value: ExecutionPlan


@dataclass(frozen=True, slots=True)
class IndexedSnapshot:
    kind: Literal["snapshot"]
    ref: str
    value: StudySnapshot


@dataclass(frozen=True, slots=True)
class IndexedExecution:
    kind: Literal["execution"]
    ref: str
    value: ExecutionOutcome


@dataclass(frozen=True, slots=True)
class IndexedEvaluationFailure:
    kind: Literal["evaluation_failure"]
    ref: str
    value: EvaluationFailure


@dataclass(frozen=True, slots=True)
class IndexedEvidence:
    kind: Literal["evidence"]
    ref: str
    value: JSONObject
    run_id: str
    plan_ref: str


@dataclass(frozen=True, slots=True)
class IndexedOperating:
    kind: Literal["operating"]
    ref: str
    value: JSONObject


@dataclass(frozen=True, slots=True)
class IndexedReportConfig:
    kind: Literal["report_config"]
    ref: str
    value: ReportConfig


@dataclass(frozen=True, slots=True)
class IndexedReport:
    kind: Literal["report"]
    ref: str
    value: JSONObject


@dataclass(frozen=True, slots=True)
class IndexedOpaque:
    kind: Literal["opaque"]
    ref: str


@dataclass(frozen=True, slots=True)
class IndexedRun:
    run_key: str
    run_id: str
    plan_ref: str
    manifest_ref: str | None
    status: Literal["complete", "incomplete", "unmanifested"]
    execution_records: dict[str, tuple[str, ...]]
    evaluation_records: dict[str, tuple[str, ...]]
    operating_records: tuple[str, ...]
    conflicted_coordinates: tuple[str, ...]
    candidate_only: bool
    summary: RunSummary
    issues: tuple[ReadIssue, ...]


@dataclass(frozen=True, slots=True)
class ReviewIndex:
    root: str
    objects: tuple[IndexedObject, ...]
    runs: tuple[IndexedRun, ...]
    reports: tuple[ReportSummary, ...]
    issues: tuple[ReadIssue, ...]
    scan_incomplete: bool

    @property
    def store_summary(self) -> StoreSummary:
        return StoreSummary(
            self.root,
            tuple(run.summary for run in self.runs),
            self.reports,
            self.issues,
        )


type IndexedObject = (
    IndexedManifest
    | IndexedPlan
    | IndexedSnapshot
    | IndexedExecution
    | IndexedEvaluationFailure
    | IndexedEvidence
    | IndexedOperating
    | IndexedReportConfig
    | IndexedReport
    | IndexedOpaque
)


_WIRE_SCHEMAS = {
    "assay-run-manifest/0.1.0",
    "assay-execution-plan/0.1.0",
    "assay-study-snapshot/0.1.0",
    "assay-execution-outcome/0.1.0",
    "assay-evaluation-failure/0.1.0",
    "assay-report-config/0.1.0",
}


def _issue(ref: str, message: str, *, code: str = "malformed_object") -> ReadIssue:
    return ReadIssue(code, message, ref, None)


def _json_object(value: dict[str, Any]) -> JSONObject:
    # json.loads only constructs JSON-native values.  This cast-through helper
    # keeps the untrusted document intact while satisfying the recursive alias.
    return value


def _parse_wire(ref: str, schema: str, value: dict[str, Any]) -> IndexedObject | ReadIssue:
    try:
        if schema == "assay-run-manifest/0.1.0":
            return IndexedManifest("manifest", ref, RunManifest.model_validate(value))
        if schema == "assay-execution-plan/0.1.0":
            return IndexedPlan("plan", ref, ExecutionPlan.model_validate(value))
        if schema == "assay-study-snapshot/0.1.0":
            return IndexedSnapshot("snapshot", ref, StudySnapshot.model_validate(value))
        if schema == "assay-execution-outcome/0.1.0":
            return IndexedExecution("execution", ref, ExecutionOutcome.model_validate(value))
        if schema == "assay-evaluation-failure/0.1.0":
            parsed = EvaluationFailure.model_validate(value)
            return IndexedEvaluationFailure("evaluation_failure", ref, parsed)
        parsed_config = ReportConfig.model_validate(value)
        return IndexedReportConfig("report_config", ref, parsed_config)
    except (ValidationError, TypeError, ValueError) as error:
        return _issue(ref, f"malformed {schema}: {error}")


def classify_object(ref: ObjectRef | str, raw_bytes: bytes) -> IndexedObject | ReadIssue:
    """Classify verified bytes without consulting other objects; never raise."""
    ref_text = str(ref)
    try:
        ObjectRef(ref_text)
    except (TypeError, ValueError) as error:
        return _issue(ref_text, str(error), code="invalid_object_ref")
    try:
        value = json.loads(raw_bytes)
    except (UnicodeDecodeError, ValueError):
        return IndexedOpaque("opaque", ref_text)
    if not isinstance(value, dict):
        return IndexedOpaque("opaque", ref_text)

    schema_version = value.get("schema_version")
    if isinstance(schema_version, str) and schema_version in _WIRE_SCHEMAS:
        return _parse_wire(ref_text, schema_version, value)

    record_schema = value.get("record_schema")
    if not isinstance(record_schema, str):
        return IndexedOpaque("opaque", ref_text)
    if record_schema == "assay-report/0.1.0":
        config_ref = value.get("config_ref")
        manifest_refs = value.get("manifest_refs")
        if not isinstance(config_ref, str) or not isinstance(manifest_refs, list) or any(
            not isinstance(item, str) for item in manifest_refs
        ):
            return _issue(ref_text, "malformed report discriminator fields")
        try:
            ObjectRef(config_ref)
            for item in manifest_refs:
                ObjectRef(item)
        except ValueError as error:
            return _issue(ref_text, f"malformed report: {error}")
        return IndexedReport("report", ref_text, _json_object(value))
    if record_schema.startswith("paa-evidence-record/"):
        payload = value.get("payload")
        if not isinstance(payload, dict):
            return _issue(ref_text, "malformed evidence: payload must be an object")
        run_id = payload.get("run_id")
        plan_ref = payload.get("plan_ref")
        if not isinstance(run_id, str) or not isinstance(plan_ref, str):
            return _issue(ref_text, "malformed evidence: run_id and plan_ref must be strings")
        try:
            ObjectRef(plan_ref)
        except ValueError as error:
            return _issue(ref_text, f"malformed evidence: {error}")
        return IndexedEvidence("evidence", ref_text, _json_object(value), run_id, plan_ref)
    if record_schema.startswith("paa-operating-record/"):
        sources = value.get("source_references")
        if not isinstance(sources, list) or any(not isinstance(item, str) for item in sources):
            return _issue(ref_text, "malformed operating record: invalid source_references")
        try:
            for item in sources:
                ObjectRef(item)
        except ValueError as error:
            return _issue(ref_text, f"malformed operating record: {error}")
        return IndexedOperating("operating", ref_text, _json_object(value))
    return IndexedOpaque("opaque", ref_text)


def _empty_cost(issues: tuple[ReadIssue, ...] = ()) -> CostView:
    return CostView("unavailable", {}, {}, {}, 0, None, None, bool(issues), issues)


def _cost(operating_refs: Sequence[str], by_ref: dict[str, IndexedObject]) -> CostView:
    counts: dict[str, int] = {}
    amounts: dict[str, float] = {}
    attempts = 0
    issues: list[ReadIssue] = []
    for ref in operating_refs:
        item = by_ref.get(ref)
        if not isinstance(item, IndexedOperating):
            issues.append(
                ReadIssue("invalid_accounting", "accounting object is unavailable", ref, None)
            )
            continue
        price = item.value.get("price")
        coverage = "unavailable"
        if isinstance(price, dict):
            amount = price.get("amount")
            currency = price.get("currency")
            if (
                not isinstance(amount, int | float)
                or isinstance(amount, bool)
                or not isinstance(currency, str)
            ):
                issues.append(
                    ReadIssue("invalid_accounting", "invalid accounting price", ref, None)
                )
                continue
            coverage = "measured"
            amounts[currency] = amounts.get(currency, 0.0) + float(amount)
        elif price is not None:
            issues.append(ReadIssue("invalid_accounting", "invalid accounting price", ref, None))
            continue
        counts[coverage] = counts.get(coverage, 0) + 1
        attempts += 1
    observed = set(counts)
    coverage_value: Literal["measured", "estimated", "unavailable", "mixed"]
    if not observed:
        coverage_value = "unavailable"
    elif len(observed) > 1:
        coverage_value = "mixed"
    else:
        only = next(iter(observed))
        coverage_value = "measured" if only == "measured" else "unavailable"
    return CostView(
        coverage_value,
        counts,
        amounts,
        {},
        attempts,
        None,
        None,
        bool(issues),
        tuple(issues),
    )


def _coordinate(item: IndexedObject) -> tuple[str, str] | None:
    if isinstance(item, IndexedExecution):
        return ("execution", item.value.coordinate.id)
    if isinstance(item, IndexedEvaluationFailure):
        return ("evaluation", item.value.coordinate.id)
    if isinstance(item, IndexedEvidence):
        payload = item.value.get("payload")
        if not isinstance(payload, dict):
            return None
        cell_id = payload.get("cell_id")
        evaluator_id = payload.get("evaluator_id")
        evaluator_repeat = payload.get("evaluator_repeat")
        if (
            not isinstance(cell_id, str)
            or not isinstance(evaluator_id, str)
            or not isinstance(evaluator_repeat, int)
            or isinstance(evaluator_repeat, bool)
            or evaluator_repeat < 0
        ):
            return None
        return ("evaluation", f"{cell_id}:{evaluator_id}:e{evaluator_repeat}")
    return None


def _record_run(item: IndexedObject) -> tuple[str, str] | None:
    if isinstance(item, IndexedExecution | IndexedEvaluationFailure):
        return (item.value.run_id, item.value.plan_ref)
    if isinstance(item, IndexedEvidence):
        return (item.run_id, item.plan_ref)
    return None


def _maps(
    records: list[IndexedObject],
) -> tuple[dict[str, tuple[str, ...]], dict[str, tuple[str, ...]], tuple[str, ...]]:
    execution: dict[str, list[str]] = {}
    evaluation: dict[str, list[str]] = {}
    for item in records:
        coordinate = _coordinate(item)
        if coordinate is None:
            continue
        role, key = coordinate
        target = execution if role == "execution" else evaluation
        target.setdefault(key, []).append(item.ref)
    executions = {key: tuple(sorted(refs)) for key, refs in sorted(execution.items())}
    evaluations = {key: tuple(sorted(refs)) for key, refs in sorted(evaluation.items())}
    conflicts = tuple(
        sorted(
            key
            for mapping in (executions, evaluations)
            for key, refs in mapping.items()
            if len(refs) > 1
        )
    )
    return executions, evaluations, conflicts


def _context(
    plan_ref: str,
    by_ref: dict[str, IndexedObject],
) -> tuple[ExecutionPlan | None, StudySnapshot | None, tuple[ReadIssue, ...]]:
    plan_item = by_ref.get(plan_ref)
    if not isinstance(plan_item, IndexedPlan):
        return None, None, (_issue(plan_ref, "run plan is unavailable", code="missing_plan"),)
    snapshot_item = by_ref.get(plan_item.value.snapshot_ref)
    if not isinstance(snapshot_item, IndexedSnapshot):
        issue = _issue(
            plan_item.value.snapshot_ref,
            "run snapshot is unavailable",
            code="missing_snapshot",
        )
        return plan_item.value, None, (issue,)
    return plan_item.value, snapshot_item.value, ()


def _run_summary(
    *,
    run_key: str,
    run_id: str,
    manifest_ref: str | None,
    plan_ref: str,
    status: Literal["complete", "incomplete", "unmanifested"],
    plan: ExecutionPlan | None,
    snapshot: StudySnapshot | None,
    execution: dict[str, tuple[str, ...]],
    evaluation: dict[str, tuple[str, ...]],
    operating_refs: Sequence[str],
    by_ref: dict[str, IndexedObject],
    issues: tuple[ReadIssue, ...],
) -> RunSummary:
    good_execution = [refs[0] for refs in execution.values() if len(refs) == 1]
    good_evaluation = [refs[0] for refs in evaluation.values() if len(refs) == 1]
    conflicts_execution = sum(len(refs) > 1 for refs in execution.values())
    conflicts_evaluation = sum(len(refs) > 1 for refs in evaluation.values())
    execution_values = [by_ref.get(ref) for ref in good_execution]
    evaluation_values = [by_ref.get(ref) for ref in good_evaluation]
    execution_succeeded = sum(
        isinstance(item, IndexedExecution) and item.value.status == "succeeded"
        for item in execution_values
    )
    execution_failed = sum(
        isinstance(item, IndexedExecution) and item.value.status == "failed"
        for item in execution_values
    )
    evaluation_succeeded = sum(isinstance(item, IndexedEvidence) for item in evaluation_values)
    evaluation_failed = sum(
        isinstance(item, IndexedEvaluationFailure) for item in evaluation_values
    )
    terminal_values = [*execution_values, *evaluation_values]
    started = sorted(
        item.value.started_at
        for item in terminal_values
        if isinstance(item, IndexedExecution | IndexedEvaluationFailure)
    )
    completed = sorted(
        item.value.completed_at
        for item in terminal_values
        if isinstance(item, IndexedExecution | IndexedEvaluationFailure)
    )
    return RunSummary(
        run_key=run_key,
        run_id=run_id,
        manifest_ref=manifest_ref,
        plan_ref=plan_ref,
        snapshot_ref=plan.snapshot_ref if plan is not None else None,
        status=status,
        subjects=len(snapshot.subjects) if snapshot is not None else None,
        arms=tuple(arm.id for arm in snapshot.arms) if snapshot is not None else None,
        worker_repeats=plan.worker_repeats if plan is not None else None,
        concurrency=plan.concurrency if plan is not None else None,
        jig_revision=plan.jig_revision if plan is not None else None,
        assay_version=plan.assay_version if plan is not None else None,
        started_at=started[0] if started else None,
        completed_at=completed[-1] if completed else None,
        cells_total=len(plan.cells) if plan is not None else None,
        cells_succeeded=execution_succeeded,
        cells_failed=execution_failed,
        cells_missing=(len(plan.cells) - len(execution)) if plan is not None else None,
        cells_invalid=len(good_execution) - execution_succeeded - execution_failed,
        cells_conflicted=conflicts_execution,
        evaluations_total=len(plan.evaluations) if plan is not None else None,
        evaluations_succeeded=evaluation_succeeded,
        evaluations_failed=evaluation_failed,
        evaluations_missing=(len(plan.evaluations) - len(evaluation)) if plan is not None else None,
        evaluations_invalid=len(good_evaluation) - evaluation_succeeded - evaluation_failed,
        evaluations_conflicted=conflicts_evaluation,
        exclusions=(
            tuple(
                ExclusionView(
                    item.subject_id,
                    item.arm_id,
                    item.classification,
                    item.reason,
                    manifest_ref,
                )
                for item in plan.exclusions
            )
            if plan is not None
            else ()
        ),
        cost=_cost(operating_refs, by_ref),
        issues=issues,
    )


def _manifest_run(
    item: IndexedManifest,
    by_ref: dict[str, IndexedObject],
    store: ObjectStore,
) -> IndexedRun:
    manifest = item.value
    plan, snapshot, context_issues = _context(manifest.plan_ref, by_ref)
    execution: dict[str, tuple[str, ...]] = {
        key: (ref,) for key, ref in sorted(manifest.execution_records.items())
    }
    evaluation: dict[str, tuple[str, ...]] = {
        key: (ref,) for key, ref in sorted(manifest.evaluation_records.items())
    }
    operating_refs = tuple(sorted(manifest.operating_records.values()))
    referenced_records = [
        candidate
        for ref in (*manifest.execution_records.values(), *manifest.evaluation_records.values())
        if (candidate := by_ref.get(ref)) is not None
    ]
    referenced_operating = [
        candidate
        for ref in manifest.operating_records.values()
        if isinstance((candidate := by_ref.get(ref)), IndexedOperating)
    ]
    validation_issues = _validate_paa_records(
        referenced_records, referenced_operating, plan, snapshot, store
    )
    run_issues = (*context_issues, *validation_issues)
    summary = _run_summary(
        run_key=item.ref,
        run_id=manifest.run_id,
        manifest_ref=item.ref,
        plan_ref=manifest.plan_ref,
        status=manifest.status,
        plan=plan,
        snapshot=snapshot,
        execution=execution,
        evaluation=evaluation,
        operating_refs=operating_refs,
        by_ref=by_ref,
        issues=run_issues,
    )
    return IndexedRun(
        item.ref,
        manifest.run_id,
        manifest.plan_ref,
        item.ref,
        manifest.status,
        execution,
        evaluation,
        operating_refs,
        (),
        False,
        summary,
        run_issues,
    )


def _validate_paa_records(
    records: list[IndexedObject],
    operating: Sequence[IndexedOperating],
    plan: ExecutionPlan | None,
    snapshot: StudySnapshot | None,
    store: ObjectStore,
) -> tuple[ReadIssue, ...]:
    issues: list[ReadIssue] = []
    if plan is None or snapshot is None:
        return ()
    try:
        validators = schema_validators(store, snapshot)
    except (OSError, ValueError) as error:
        return (ReadIssue("candidate_only", f"cannot validate loose records: {error}", None, None),)
    declarations = {item.id: item for item in snapshot.evaluators}
    for item in (*records, *operating):
        try:
            if isinstance(item, IndexedEvidence):
                validators[snapshot.evidence_schema_ref].validate(item.value)
                payload = item.value.get("payload")
                evaluator_id = payload.get("evaluator_id") if isinstance(payload, dict) else None
                if not isinstance(evaluator_id, str) or evaluator_id not in declarations:
                    raise ValueError("evidence names an unknown evaluator")
                validator = validators[declarations[evaluator_id].payload_schema_ref]
                validator.validate(item.value)
            elif isinstance(item, IndexedOperating):
                validators[snapshot.operating_schema_ref].validate(item.value)
        except Exception as error:
            issues.append(
                ReadIssue(
                    "record_schema_validation",
                    f"record does not validate against the pinned schema: {error}",
                    item.ref,
                    None,
                )
            )
    return tuple(issues)


def _loose_run(
    key: tuple[str, str],
    records: list[IndexedObject],
    operating: list[IndexedOperating],
    by_ref: dict[str, IndexedObject],
    store: ObjectStore,
) -> IndexedRun:
    run_id, plan_ref = key
    run_key = f"unmanifested:{run_id}:{plan_ref}"
    execution, evaluation, conflicts = _maps(records)
    plan, snapshot, context_issues = _context(plan_ref, by_ref)
    validation_issues = _validate_paa_records(records, operating, plan, snapshot, store)
    issues = (*context_issues, *validation_issues)
    summary = _run_summary(
        run_key=run_key,
        run_id=run_id,
        manifest_ref=None,
        plan_ref=plan_ref,
        status="unmanifested",
        plan=plan,
        snapshot=snapshot,
        execution=execution,
        evaluation=evaluation,
        operating_refs=tuple(item.ref for item in operating),
        by_ref=by_ref,
        issues=issues,
    )
    return IndexedRun(
        run_key,
        run_id,
        plan_ref,
        None,
        "unmanifested",
        execution,
        evaluation,
        tuple(sorted(item.ref for item in operating)),
        conflicts,
        bool(context_issues or validation_issues),
        summary,
        issues,
    )


def _report_summary(item: IndexedReport, by_ref: dict[str, IndexedObject]) -> ReportSummary:
    config_ref = item.value["config_ref"]
    assert isinstance(config_ref, str)
    config_item = by_ref.get(config_ref)
    if not isinstance(config_item, IndexedReportConfig):
        issue = _issue(config_ref, "report configuration is unavailable", code="missing_config")
        return ReportSummary(item.ref, config_ref, "scalar", "", None, None, None, False,
                             "report configuration is unavailable", (), (issue,))
    config = config_item.value
    return ReportSummary(
        item.ref,
        config_ref,
        config.metric,
        config.evaluator_id,
        config.reference_arm,
        config.candidates,
        config.engine_version,
        True,
        None,
        config.manifest_refs,
        (),
    )


def _cache_key(objects: Path) -> tuple[dict[str, int] | None, tuple[ReadIssue, ...]]:
    count = 0
    newest = 0
    try:
        with os.scandir(objects) as entries:
            for entry in entries:
                count += 1
                try:
                    newest = max(newest, entry.stat(follow_symlinks=False).st_mtime_ns)
                except OSError as error:
                    return None, (ReadIssue("object_stat", str(error), None, None),)
    except FileNotFoundError:
        return {"count": 0, "newest_mtime_ns": 0}, ()
    except OSError as error:
        return None, (ReadIssue("root_unreadable", str(error), None, None),)
    return {"count": count, "newest_mtime_ns": newest}, ()


def _cache_object(item: IndexedObject | ReadIssue) -> JSONObject:
    if isinstance(item, ReadIssue):
        return {
            "kind": "issue",
            "code": item.code,
            "message": item.message,
            "ref": item.ref,
            "coordinate_id": item.coordinate_id,
        }
    if isinstance(item, IndexedOpaque):
        return {"kind": "opaque", "ref": item.ref}
    if isinstance(
        item,
        IndexedManifest
        | IndexedPlan
        | IndexedSnapshot
        | IndexedExecution
        | IndexedEvaluationFailure
        | IndexedReportConfig,
    ):
        value: object = item.value.model_dump(mode="json")
    else:
        value = item.value
    return cast(JSONObject, {"kind": item.kind, "ref": item.ref, "value": value})


def _cached_object(value: object) -> IndexedObject | ReadIssue:
    if not isinstance(value, dict):
        raise ValueError("cached object entry must be an object")
    kind = value.get("kind")
    if kind == "issue":
        code, message, ref, coordinate = (
            value.get("code"),
            value.get("message"),
            value.get("ref"),
            value.get("coordinate_id"),
        )
        if (
            not isinstance(code, str)
            or not isinstance(message, str)
            or (ref is not None and not isinstance(ref, str))
            or (coordinate is not None and not isinstance(coordinate, str))
        ):
            raise ValueError("invalid cached issue")
        return ReadIssue(code, message, ref, coordinate)
    ref = value.get("ref")
    if not isinstance(ref, str):
        raise ValueError("cached object ref must be a string")
    ObjectRef(ref)
    if kind == "opaque":
        return IndexedOpaque("opaque", ref)
    document = value.get("value")
    if not isinstance(document, dict):
        raise ValueError("cached classified value must be an object")
    raw = json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode()
    item = classify_object(ref, raw)
    if isinstance(item, ReadIssue) or item.kind != kind:
        raise ValueError("cached classification is invalid")
    return item


def _read_cache(root: Path, key: dict[str, int]) -> list[IndexedObject | ReadIssue] | None:
    try:
        value = json.loads((root / "review-index.json").read_bytes())
        if (
            not isinstance(value, dict)
            or value.get("version") != CACHE_VERSION
            or value.get("key") != key
            or not isinstance(value.get("objects"), list)
        ):
            return None
        return [_cached_object(item) for item in value["objects"]]
    except (OSError, UnicodeDecodeError, ValueError, TypeError):
        return None


def _write_cache(root: Path, key: dict[str, int], items: list[IndexedObject | ReadIssue]) -> None:
    payload = {
        "version": CACHE_VERSION,
        "key": key,
        "objects": [_cache_object(item) for item in items],
    }
    temporary: str | None = None
    try:
        root.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".review-index-", suffix=".tmp", dir=root)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, root / "review-index.json")
        temporary = None
    except OSError:
        # Read-only stores remain fully browseable; caching is optional.
        pass
    finally:
        if temporary is not None:
            with suppress(OSError):
                os.unlink(temporary)


def _scan(
    store: ObjectStore,
    *,
    max_objects: int | None,
    max_bytes: int | None,
) -> tuple[list[IndexedObject | ReadIssue], bool, dict[str, int] | None]:
    key, key_issues = _cache_key(store.objects)
    if key is None:
        return list(key_issues), False, None
    items: list[IndexedObject | ReadIssue] = []
    total_bytes = 0
    incomplete = False
    try:
        with os.scandir(store.objects) as entries:
            ordered = sorted(entries, key=lambda entry: entry.name)
    except FileNotFoundError:
        return [], False, key
    except OSError as error:
        return [ReadIssue("root_unreadable", str(error), None, None)], False, key
    for position, entry in enumerate(ordered):
        if max_objects is not None and position >= max_objects:
            incomplete = True
            break
        ref = "sha256:" + entry.name
        try:
            ObjectRef(ref)
        except ValueError as error:
            items.append(ReadIssue("invalid_object_filename", str(error), ref, None))
            continue
        try:
            if not entry.is_file(follow_symlinks=False):
                raise OSError("object entry is not a regular file")
            size = entry.stat(follow_symlinks=False).st_size
            if max_bytes is not None and total_bytes + size > max_bytes:
                incomplete = True
                break
            raw = store.read_bytes(ref)
            total_bytes += len(raw)
            items.append(classify_object(ref, raw))
        except Exception as error:
            items.append(ReadIssue("object_read", str(error), ref, None))
    if incomplete:
        items.append(
            ReadIssue(
                "scan_incomplete",
                "object discovery stopped at its object or byte budget",
                None,
                None,
            )
        )
    return items, incomplete, key


def _reachable_roots(
    objects: tuple[IndexedObject, ...],
) -> tuple[set[str], tuple[ReadIssue, ...]]:
    reachable: set[str] = set()
    issues: list[ReadIssue] = []
    by_ref = {item.ref: item for item in objects}
    pending = [
        (item.ref, "auto")
        for item in objects
        if isinstance(item, IndexedManifest | IndexedReport)
    ]
    seen: set[tuple[str, str]] = set()
    while pending:
        ref, role = pending.pop()
        if (ref, role) in seen:
            continue
        seen.add((ref, role))
        reachable.add(ref)
        item = by_ref.get(ref)
        if item is None or isinstance(item, IndexedOpaque):
            continue
        if isinstance(
            item,
            IndexedManifest
            | IndexedPlan
            | IndexedSnapshot
            | IndexedExecution
            | IndexedEvaluationFailure
            | IndexedReportConfig,
        ):
            value: object = item.value.model_dump(mode="json")
        else:
            value = item.value
        try:
            pending.extend(object_edges(value, role))
        except Exception as error:
            issues.append(ReadIssue("closure_read", str(error), ref, None))
    return reachable, tuple(issues)


def _attach_loose_operating(
    store: ObjectStore,
    records: Sequence[IndexedObject],
    operating: list[IndexedOperating],
) -> tuple[dict[tuple[str, str], list[IndexedOperating]], tuple[ReadIssue, ...]]:
    terminal_by_ref = {item.ref: item for item in records}
    claims: dict[str, list[IndexedOperating]] = {}
    issues: list[ReadIssue] = []
    for item in operating:
        sources = item.value.get("source_references")
        assert isinstance(sources, list)
        terminal_sources = [source for source in sources if source in terminal_by_ref]
        if len(terminal_sources) != 1:
            issues.append(
                ReadIssue(
                    "orphan_accounting",
                    "operating record has no unique terminal source",
                    item.ref,
                    None,
                )
            )
            continue
        claims.setdefault(terminal_sources[0], []).append(item)
    grouped: dict[tuple[str, str], list[IndexedOperating]] = {}
    for terminal_ref, claimants in claims.items():
        terminal = terminal_by_ref[terminal_ref]
        run = _record_run(terminal)
        coordinate = _coordinate(terminal)
        if run is None or coordinate is None or len(claimants) != 1:
            issues.append(
                ReadIssue(
                    "duplicate_accounting",
                    "terminal has ambiguous accounting",
                    terminal_ref,
                    coordinate[1] if coordinate else None,
                )
            )
            continue
        item = claimants[0]
        sources = item.value["source_references"]
        assert isinstance(sources, list)
        provenance: list[dict[str, Any]] = []
        for source in sources:
            if not isinstance(source, str):
                continue
            if source == terminal_ref:
                continue
            try:
                candidate = json.loads(store.read_bytes(source))
            except Exception:
                continue
            if isinstance(candidate, dict) and "run_id" in candidate and "attempt" in candidate:
                provenance.append(candidate)
        expected_attempt = f"worker:{coordinate[1]}"
        if coordinate[0] != "execution":
            expected_attempt = f"evaluator:{coordinate[1]}"
        valid = (
            len(provenance) == 1
            and provenance[0].get("run_id") == run[0]
            and provenance[0].get("attempt") == expected_attempt
        )
        if not valid:
            issues.append(
                ReadIssue(
                    "orphan_accounting",
                    "accounting provenance does not match its terminal",
                    item.ref,
                    coordinate[1],
                )
            )
            continue
        grouped.setdefault(run, []).append(item)
    attached = {item.ref for values in grouped.values() for item in values}
    attached_terminals = {
        source
        for item in attached
        for source, claimants in claims.items()
        if any(claim.ref == item for claim in claimants)
    }
    for terminal_ref in terminal_by_ref.keys() - attached_terminals:
        coordinate = _coordinate(terminal_by_ref[terminal_ref])
        issues.append(
            ReadIssue(
                "missing_accounting",
                "terminal record has no attributable accounting",
                terminal_ref,
                coordinate[1] if coordinate else None,
            )
        )
    return grouped, tuple(issues)


def build_index(
    store: ObjectStore,
    *,
    refresh: bool = False,
    max_objects: int = DEFAULT_MAX_OBJECTS,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> ReviewIndex:
    """Discover and group store objects, using a dispensable sibling cache."""
    key, key_issues = _cache_key(store.objects)
    cached = None if refresh or key is None else _read_cache(store.root, key)
    incomplete = False
    if cached is None:
        limits = (None, None) if refresh else (max_objects, max_bytes)
        items, incomplete, scanned_key = _scan(
            store,
            max_objects=limits[0],
            max_bytes=limits[1],
        )
        if scanned_key is not None and not incomplete:
            _write_cache(store.root, scanned_key, items)
    else:
        items = cached
    objects = tuple(item for item in items if not isinstance(item, ReadIssue))
    issues = [*key_issues, *(item for item in items if isinstance(item, ReadIssue))]
    by_ref = {item.ref: item for item in objects}
    reachable, closure_issues = _reachable_roots(objects)
    issues.extend(closure_issues)

    manifests = [item for item in objects if isinstance(item, IndexedManifest)]
    claimed = {
        ref
        for item in manifests
        for ref in (
            *item.value.execution_records.values(),
            *item.value.evaluation_records.values(),
            *item.value.operating_records.values(),
        )
    }
    terminal = [
        item
        for item in objects
        if isinstance(item, IndexedExecution | IndexedEvaluationFailure | IndexedEvidence)
        and item.ref not in claimed
        and item.ref not in reachable
    ]
    loose: dict[tuple[str, str], list[IndexedObject]] = {}
    for item in terminal:
        run = _record_run(item)
        coordinate = _coordinate(item)
        if run is None or coordinate is None:
            issues.append(
                ReadIssue(
                    "candidate_only",
                    "terminal candidate lacks a valid coordinate",
                    item.ref,
                    None,
                )
            )
            continue
        loose.setdefault(run, []).append(item)
    operating = [
        item
        for item in objects
        if isinstance(item, IndexedOperating)
        and item.ref not in claimed
        and item.ref not in reachable
    ]
    loose_operating, accounting_issues = _attach_loose_operating(store, terminal, operating)
    issues.extend(accounting_issues)
    runs = [*(_manifest_run(item, by_ref, store) for item in manifests)]
    runs.extend(
        _loose_run(key_value, records, loose_operating.get(key_value, []), by_ref, store)
        for key_value, records in loose.items()
    )
    reports = tuple(
        sorted(
            (_report_summary(item, by_ref) for item in objects if isinstance(item, IndexedReport)),
            key=lambda report: report.report_ref,
        )
    )
    return ReviewIndex(
        str(store.root),
        tuple(sorted(objects, key=lambda item: item.ref)),
        tuple(sorted(runs, key=lambda run: run.run_key)),
        reports,
        tuple(issues),
        incomplete,
    )


def discover_store(
    store: ObjectStore,
    *,
    refresh: bool = False,
    max_objects: int = DEFAULT_MAX_OBJECTS,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> StoreSummary:
    """Return the JSON-facing store summary for discovery clients."""
    return build_index(
        store,
        refresh=refresh,
        max_objects=max_objects,
        max_bytes=max_bytes,
    ).store_summary
