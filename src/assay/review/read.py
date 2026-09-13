"""Verified, operation-scoped projections for the review UI and static exporter.

Discovery answers which roots may be opened.  This module answers what a root
means: every public operation creates one verification session and all child
objects are read through it.  Failures are converted to reference-scoped view
issues so that one damaged child does not hide the rest of a run or report.
"""

from __future__ import annotations

import difflib
import json
import re
from dataclasses import replace
from typing import Any, Literal, cast

from pydantic import ValidationError

from assay._version import __version__
from assay.canonical import canonical_json, digest_bytes
from assay.models import (
    EvaluationFailure,
    ExecutionOutcome,
    ExecutionPlan,
    ReportConfig,
    RunManifest,
    StudySnapshot,
)
from assay.references import object_edges
from assay.report_engine import ReportError, build_report, summarize_operating
from assay.review.index import IndexedRun, ReviewIndex
from assay.review.model import (
    ArmView,
    CellDetail,
    CellSummary,
    ComparisonView,
    CostView,
    DiffView,
    EvaluationView,
    EvaluatorView,
    ExclusionView,
    InputView,
    JSONObject,
    ObjectPreview,
    PairView,
    PlannedCostView,
    ReadIssue,
    RecomputeResult,
    ReportDetail,
    ReportSummary,
    RunDetail,
    RunSummary,
    StoreSummary,
    SubjectView,
    VerdictSummary,
    VerificationResult,
)
from assay.review.model import (
    VerificationFailure as ViewVerificationFailure,
)
from assay.store import ObjectIntegrityError, ObjectStore, verification_session
from assay.verify import verify_bundle, verify_manifest, verify_report

MAX_PREVIEW_BYTES = 8 * 1024 * 1024
MAX_DIFF_BYTES = 256 * 1024
MAX_DIFF_LINES = 5_000


class ReadError(ValueError):
    """An unreadable requested root (children instead produce ReadIssue values)."""


def _issue(ref: str | None, code: str, message: str, coordinate: str | None = None) -> ReadIssue:
    # Never copy OSError text: ObjectStore embeds its absolute path in it.
    return ReadIssue(code, message, ref, coordinate)


def _error_issue(ref: str, error: Exception, coordinate: str | None = None) -> ReadIssue:
    if isinstance(error, FileNotFoundError):
        return _issue(ref, "missing_object", f"referenced object is missing: {ref}", coordinate)
    if isinstance(error, ObjectIntegrityError):
        return _issue(ref, "integrity_error", f"object failed its digest check: {ref}", coordinate)
    return _issue(
        ref, "invalid_record", f"object cannot be read as a recognized record: {ref}", coordinate
    )


def _json(session: ObjectStore, ref: str) -> Any:
    data = session.read_bytes(ref)
    value = json.loads(data)
    if canonical_json(value) != data:
        raise ValueError("noncanonical JSON")
    return value


def _safe_json(
    session: ObjectStore, ref: str, coordinate: str | None = None
) -> tuple[Any | None, tuple[ReadIssue, ...]]:
    try:
        return _json(session, ref), ()
    except (OSError, ObjectIntegrityError, UnicodeDecodeError, ValueError, TypeError) as error:
        return None, (_error_issue(ref, error, coordinate),)


def _model(
    session: ObjectStore, ref: str, model: type[Any], *, root: bool = False
) -> tuple[Any | None, tuple[ReadIssue, ...]]:
    value, issues = _safe_json(session, ref)
    if issues:
        if root:
            raise ReadError(issues[0].message)
        return None, issues
    try:
        return model.model_validate(value), ()
    except (ValidationError, TypeError, ValueError):
        issue = _issue(ref, "invalid_record", f"object is not a valid {model.__name__}: {ref}")
        if root:
            raise ReadError(issue.message) from None
        return None, (issue,)


def preview(session: ObjectStore, ref: str) -> ObjectPreview:
    """Return the bounded review preview for one verified object."""
    try:
        raw = session.read_bytes(ref)
    except (OSError, ObjectIntegrityError, ValueError) as error:
        issue = _error_issue(ref, error)
        return ObjectPreview(ref, "unavailable", None, None, False, (issue,))
    truncated = len(raw) > MAX_PREVIEW_BYTES
    bounded = raw[:MAX_PREVIEW_BYTES]
    try:
        value = json.loads(raw) if not truncated else None
        text = (
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
            if value is not None
            else bounded.decode("utf-8", "replace")
        )
        kind: Literal["json", "text", "binary", "unavailable"] = (
            "json" if value is not None else "text"
        )
    except (UnicodeDecodeError, ValueError):
        try:
            text = bounded.decode("utf-8")
            kind = "text"
        except UnicodeDecodeError:
            text, kind = None, "binary"
    issues: tuple[ReadIssue, ...] = ()
    if truncated:
        text = (text or "") + "\n\n[preview truncated at 8 MiB]"
        issues = (_issue(ref, "preview_truncated", "object preview was truncated at 8 MiB"),)
    return ObjectPreview(ref, kind, text, len(raw), truncated, issues)


def _input(session: ObjectStore, ref: str | None) -> InputView:
    if ref is None:
        return InputView("unavailable", None, None, None)
    object_preview = preview(session, ref)
    if object_preview.kind == "unavailable" or object_preview.truncated:
        return InputView(
            "unavailable" if object_preview.kind == "unavailable" else "generic",
            None,
            None,
            object_preview,
        )
    value, _ = _safe_json(session, ref)
    if (
        isinstance(value, dict)
        and isinstance(value.get("task"), dict)
        and isinstance(value.get("repository"), dict)
    ):
        task, repository = value["task"], value["repository"]
        instruction = task.get("instruction")
        files = (
            repository
            if all(isinstance(k, str) and isinstance(v, str) for k, v in repository.items())
            else None
        )
        return InputView(
            "consistency",
            instruction if isinstance(instruction, str) else None,
            cast(dict[str, str] | None, files),
            object_preview,
        )
    return InputView("generic", None, None, object_preview)


def _source(session: ObjectStore, ref: str | None) -> tuple[str | None, ObjectPreview | None]:
    if ref is None:
        return None, None
    object_preview = preview(session, ref)
    if object_preview.truncated or object_preview.kind == "unavailable":
        return None, object_preview
    value, _ = _safe_json(session, ref)
    if isinstance(value, str):
        return value, object_preview
    if isinstance(value, dict) and isinstance(value.get("source"), str):
        return value["source"], object_preview
    return None, object_preview


def _empty_cost(*issues: ReadIssue, partial: bool = True) -> CostView:
    return CostView("unavailable", {}, {}, {}, 0, None, None, partial, tuple(issues))


def _cost(
    session: ObjectStore,
    refs: tuple[str, ...],
    expected: int | None,
    partial: bool,
    expected_keys: set[str] | None = None,
) -> CostView:
    usable: list[str] = []
    issues: list[ReadIssue] = []
    seen: set[tuple[str, str]] = set()
    for ref in refs:
        value, read_issues = _safe_json(session, ref)
        if read_issues:
            issues.extend(read_issues)
            continue
        try:
            if (
                not isinstance(value, dict)
                or not isinstance(value.get("record_schema"), str)
                or value["record_schema"].split("/")[0] != "paa-operating-record"
            ):
                raise ValueError
            details = []
            for source in value.get("source_references", []):
                detail, detail_issues = _safe_json(session, source)
                if detail_issues:
                    raise ValueError
                if isinstance(detail, dict) and "attempt" in detail and "coverage" in detail:
                    details.append(detail)
            if (
                len(details) != 1
                or not isinstance(details[0].get("run_id"), str)
                or not isinstance(details[0].get("attempt"), str)
            ):
                raise ValueError
            key = (details[0]["run_id"], details[0]["attempt"])
            if expected_keys is not None and key[1] not in expected_keys:
                continue
            if key in seen:
                issues.append(
                    _issue(
                        ref,
                        "conflicting_accounting",
                        "accounting record overlaps an observed attempt",
                    )
                )
                continue
            seen.add(key)
            usable.append(ref)
        except (TypeError, ValueError):
            issues.append(
                _issue(
                    ref,
                    "invalid_accounting",
                    "accounting record has invalid or ambiguous provenance",
                )
            )
    try:
        summary = summarize_operating(session, usable)
    except (ReportError, KeyError, TypeError, ValueError) as error:
        issues.append(
            _issue(
                None,
                "accounting_summary",
                f"usable accounting records could not be summarized: {type(error).__name__}",
            )
        )
        summary = {
            "coverage": "unavailable",
            "coverage_counts": {},
            "amounts": {},
            "by_stage_arm": {},
            "attempts": 0,
        }
    attempts = int(summary["attempts"])
    unaccounted = None if expected is None else max(0, expected - attempts)
    coverage = str(summary["coverage"])
    if attempts == 0:
        coverage = "unavailable"
    elif issues or (unaccounted or 0) > 0:
        coverage = "mixed"
    return CostView(
        cast(Any, coverage),
        dict(summary["coverage_counts"]),
        dict(summary["amounts"]),
        cast(JSONObject, summary["by_stage_arm"]),
        attempts,
        expected,
        unaccounted,
        partial or bool(issues) or unaccounted is None or (unaccounted or 0) > 0,
        tuple(issues),
    )


class ReviewReader:
    """Resolve review views.  Create a new instance for each request/export."""

    def __init__(self, store: ObjectStore, index: ReviewIndex) -> None:
        self.store = verification_session(store)
        self.index = index

    def _run(self, run_key: str) -> IndexedRun:
        try:
            return next(run for run in self.index.runs if run.run_key == run_key)
        except StopIteration:
            raise KeyError(run_key) from None

    def store_summary(self) -> StoreSummary:
        runs = tuple(self.run(item.run_key).summary for item in self.index.runs)
        reports: list[ReportSummary] = []
        issues = list(self.index.issues)
        for item in self.index.reports:
            try:
                reports.append(self.report(item.report_ref).summary)
            except ReadError:
                issues.append(
                    _issue(item.report_ref, "invalid_record", "report root is unreadable")
                )
        return StoreSummary(self.index.root, runs, tuple(reports), tuple(issues))

    def _context(
        self, run: IndexedRun
    ) -> tuple[RunManifest | None, ExecutionPlan | None, StudySnapshot | None, list[ReadIssue]]:
        issues: list[ReadIssue] = []
        manifest = None
        if run.manifest_ref:
            manifest, found = _model(self.store, run.manifest_ref, RunManifest, root=True)
            issues.extend(found)
        plan, found = _model(self.store, run.plan_ref, ExecutionPlan)
        issues.extend(found)
        snapshot = None
        if plan is not None:
            snapshot, found = _model(self.store, plan.snapshot_ref, StudySnapshot)
            issues.extend(found)
        return manifest, plan, snapshot, issues

    def run(self, run_key: str) -> RunDetail:
        run = self._run(run_key)
        manifest, plan, snapshot, issues = self._context(run)
        executions = run.execution_records
        evaluations = run.evaluation_records
        cells: list[CellSummary] = []
        if plan is not None:
            for coordinate in plan.cells:
                cells.append(
                    self._cell_summary(
                        run,
                        coordinate.id,
                        coordinate.subject_id,
                        coordinate.arm_id,
                        coordinate.worker_repeat,
                        plan,
                        snapshot,
                    )
                )
            present = {cell.cell_id for cell in cells}
            for exclusion in plan.exclusions:
                for worker_repeat in range(plan.worker_repeats):
                    cell_id = f"{exclusion.subject_id}:{exclusion.arm_id}:w{worker_repeat}"
                    if cell_id not in present:
                        cells.append(
                            self._cell_summary(
                                run,
                                cell_id,
                                exclusion.subject_id,
                                exclusion.arm_id,
                                worker_repeat,
                                plan,
                                snapshot,
                            )
                        )
        else:
            for cell_id in sorted(executions):
                match = re.fullmatch(r"(.+):(.+):w([0-9]+)", cell_id)
                if match:
                    cells.append(
                        self._cell_summary(
                            run, cell_id, match[1], match[2], int(match[3]), None, snapshot
                        )
                    )
        summary = self._summary(run, manifest, plan, snapshot, cells, issues)
        subjects = (
            ()
            if snapshot is None
            else tuple(SubjectView(x.id, x.label, x.digest, x.partition) for x in snapshot.subjects)
        )
        arms = (
            ()
            if snapshot is None
            else tuple(
                ArmView(
                    x.id,
                    str(x.worker["id"]),
                    str(x.worker["version"]),
                    tuple(sorted(x.intervention)),
                )
                for x in snapshot.arms
            )
        )
        evaluators = (
            ()
            if snapshot is None
            else tuple(
                EvaluatorView(
                    x.id, cast(JSONObject, x.identity), x.repeats, _categories(x.configuration)
                )
                for x in snapshot.evaluators
            )
        )
        estimate = (
            None
            if plan is None
            else PlannedCostView(
                plan.cost_estimate.amount, plan.cost_estimate.currency, plan.cost_estimate.coverage
            )
        )
        missing = (
            manifest.missing_coordinates
            if manifest is not None
            else (
                None
                if plan is None
                else tuple(
                    sorted(
                        ({x.id for x in plan.cells} - executions.keys())
                        | ({x.id for x in plan.evaluations} - evaluations.keys())
                    )
                )
            )
        )
        return RunDetail(summary, subjects, arms, evaluators, tuple(cells), missing, estimate)

    def _cell_summary(
        self,
        run: IndexedRun,
        cell_id: str,
        subject: str,
        arm: str,
        repeat: int,
        plan: ExecutionPlan | None,
        snapshot: StudySnapshot | None,
    ) -> CellSummary:
        exclusion = None
        if plan is not None:
            item = next(
                (x for x in plan.exclusions if x.subject_id == subject and x.arm_id == arm), None
            )
            if item is not None:
                exclusion = ExclusionView(
                    subject, arm, item.classification, item.reason, run.manifest_ref
                )
        refs = run.execution_records.get(cell_id, ())
        issues: list[ReadIssue] = []
        status: Any = "excluded" if exclusion else "missing"
        error_type = error_message = None
        if len(refs) > 1:
            status = "conflicted"
            issues.append(
                _issue(
                    None,
                    "conflicting_records",
                    "multiple execution records claim this coordinate",
                    cell_id,
                )
            )
        elif refs:
            outcome, found = _model(self.store, refs[0], ExecutionOutcome)
            issues.extend(replace(x, coordinate_id=cell_id) for x in found)
            if outcome is None:
                status = "invalid"
            elif (
                outcome.run_id != run.run_id
                or outcome.plan_ref != run.plan_ref
                or outcome.coordinate.id != cell_id
            ):
                status = "invalid"
                issues.append(
                    _issue(
                        refs[0],
                        "invalid_record",
                        "execution record does not match its run coordinate",
                        cell_id,
                    )
                )
            else:
                status, error_type, error_message = (
                    outcome.status,
                    outcome.error_type,
                    outcome.error_message,
                )
        verdicts = self._verdict_summaries(run, cell_id, plan, snapshot)
        return CellSummary(
            cell_id,
            subject,
            arm,
            repeat,
            status,
            error_type,
            error_message,
            refs,
            exclusion,
            verdicts,
            tuple(issues),
        )

    def _evaluation(
        self, run: IndexedRun, cell_id: str, evaluator_id: str, repeat: int
    ) -> EvaluationView:
        coordinate = f"{cell_id}:{evaluator_id}:e{repeat}"
        refs = run.evaluation_records.get(coordinate, ())
        if len(refs) > 1:
            issue = _issue(
                None,
                "conflicting_records",
                "multiple evaluation records claim this coordinate",
                coordinate,
            )
            return EvaluationView(
                run.run_key,
                cell_id,
                coordinate,
                evaluator_id,
                repeat,
                "conflicted",
                refs,
                None,
                (),
                None,
                None,
                (),
                None,
                (issue,),
            )
        if not refs:
            return EvaluationView(
                run.run_key,
                cell_id,
                coordinate,
                evaluator_id,
                repeat,
                "missing",
                (),
                None,
                (),
                None,
                None,
                (),
                None,
                (),
            )
        value, issues = _safe_json(self.store, refs[0], coordinate)
        if value is None or not isinstance(value, dict):
            return EvaluationView(
                run.run_key,
                cell_id,
                coordinate,
                evaluator_id,
                repeat,
                "invalid",
                refs,
                None,
                (),
                None,
                None,
                (),
                None,
                issues,
            )
        if value.get("schema_version") == "assay-evaluation-failure/0.1.0":
            try:
                failure = EvaluationFailure.model_validate(value)
                status: Literal["missing", "failed"] = (
                    "missing" if failure.error_type == "AmbiguousStructure" else "failed"
                )
                return EvaluationView(
                    run.run_key,
                    cell_id,
                    coordinate,
                    evaluator_id,
                    repeat,
                    status,
                    refs,
                    None,
                    (),
                    failure.error_type,
                    failure.error_message,
                    (() if failure.trace_ref is None else (failure.trace_ref,)),
                    None,
                    (),
                )
            except ValidationError:
                pass
        if isinstance(value.get("record_schema"), str):
            payload, verdict = value.get("payload"), value.get("verdict")
            if isinstance(payload, dict) and isinstance(verdict, dict):
                detail_refs = tuple(x for x in payload.get("detail_refs", ()) if isinstance(x, str))
                detail: Any = None
                detail_issues: list[ReadIssue] = []
                if detail_refs:
                    values = []
                    for ref in detail_refs:
                        item, found = _safe_json(self.store, ref, coordinate)
                        detail_issues.extend(found)
                        if item is not None:
                            values.append(item)
                    detail = values[0] if len(values) == 1 else values
                reasons = verdict.get("reason_codes", ())
                return EvaluationView(
                    run.run_key,
                    cell_id,
                    coordinate,
                    evaluator_id,
                    repeat,
                    "succeeded",
                    refs,
                    cast(Any, verdict.get("value")),
                    tuple(x for x in reasons if isinstance(x, str)),
                    None,
                    None,
                    detail_refs,
                    cast(Any, detail),
                    tuple(detail_issues),
                )
        issue = _issue(
            refs[0], "invalid_record", "evaluation record has an unrecognized shape", coordinate
        )
        return EvaluationView(
            run.run_key,
            cell_id,
            coordinate,
            evaluator_id,
            repeat,
            "invalid",
            refs,
            None,
            (),
            None,
            None,
            (),
            None,
            (issue,),
        )

    def _verdict_summaries(
        self,
        run: IndexedRun,
        cell_id: str,
        plan: ExecutionPlan | None,
        snapshot: StudySnapshot | None,
    ) -> tuple[VerdictSummary, ...]:
        declared = {x.id: x for x in snapshot.evaluators} if snapshot else {}
        evaluator_ids = (
            sorted({x.evaluator_id for x in plan.evaluations if x.cell_id == cell_id})
            if plan
            else sorted(
                {
                    key.split(":")[-2]
                    for key in run.evaluation_records
                    if key.startswith(cell_id + ":")
                }
            )
        )
        result = []
        for evaluator_id in evaluator_ids:
            repeats = (
                sorted(
                    x.evaluator_repeat
                    for x in plan.evaluations
                    if x.cell_id == cell_id and x.evaluator_id == evaluator_id
                )
                if plan
                else sorted(
                    int(key.rsplit(":e", 1)[1])
                    for key in run.evaluation_records
                    if key.startswith(f"{cell_id}:{evaluator_id}:e")
                )
            )
            views = [self._evaluation(run, cell_id, evaluator_id, n) for n in repeats]
            values = tuple(x.verdict for x in views)
            known = [x.verdict for x in views if x.status == "succeeded"]
            agreed = (
                None
                if not views or any(x.status != "succeeded" for x in views)
                else len(set(map(repr, known))) <= 1
            )
            failures = tuple(_evaluation_label(x) for x in views if x.status != "succeeded")
            categories = (
                _categories(declared[evaluator_id].configuration)
                if evaluator_id in declared
                else None
            )
            result.append(
                VerdictSummary(
                    evaluator_id,
                    values,
                    tuple(x.status for x in views),
                    failures,
                    agreed,
                    categories,
                )
            )
        return tuple(result)

    def _summary(
        self,
        run: IndexedRun,
        manifest: RunManifest | None,
        plan: ExecutionPlan | None,
        snapshot: StudySnapshot | None,
        cells: list[CellSummary],
        context_issues: list[ReadIssue],
    ) -> RunSummary:
        eval_views = (
            [
                self._evaluation(run, e.cell_id, e.evaluator_id, e.evaluator_repeat)
                for e in plan.evaluations
            ]
            if plan
            else []
        )
        terminals = []
        terminal_keys: set[str] = set()
        unknown_terminal = False
        for c in cells:
            if c.status in ("succeeded", "failed"):
                terminals.append(c.cell_id)
                terminal_keys.add("worker:" + c.cell_id)
            elif c.status in ("invalid", "conflicted"):
                unknown_terminal = True
        for e in eval_views:
            if e.status in ("succeeded", "failed") and e.error_type != "ExecutionUnavailable":
                terminals.append(e.coordinate_id)
                terminal_keys.add("evaluator:" + e.coordinate_id)
            elif e.status in ("invalid", "conflicted"):
                unknown_terminal = True
        expected = None if unknown_terminal else len(terminals)
        cost = _cost(
            self.store,
            run.operating_records,
            expected,
            run.status != "complete",
            None if unknown_terminal else terminal_keys,
        )
        statuses = [x.status for x in cells]
        eval_statuses = [x.status for x in eval_views]
        timestamps = []
        for refs in run.execution_records.values():
            if len(refs) == 1:
                outcome, _ = _model(self.store, refs[0], ExecutionOutcome)
                if outcome:
                    timestamps.append((outcome.started_at, outcome.completed_at))
        exclusions = (
            ()
            if plan is None
            else tuple(
                ExclusionView(x.subject_id, x.arm_id, x.classification, x.reason, run.manifest_ref)
                for x in plan.exclusions
            )
        )
        issues = tuple(
            (
                *context_issues,
                *(i for c in cells for i in c.issues),
                *(i for evaluation in eval_views for i in evaluation.issues),
                *cost.issues,
            )
        )
        return RunSummary(
            run.run_key,
            run.run_id,
            run.manifest_ref,
            run.plan_ref,
            None if plan is None else plan.snapshot_ref,
            run.status,
            None if snapshot is None else len(snapshot.subjects),
            None if snapshot is None else tuple(x.id for x in snapshot.arms),
            None if plan is None else plan.worker_repeats,
            None if plan is None else plan.concurrency,
            None if plan is None else plan.jig_revision,
            None if plan is None else plan.assay_version,
            min((x[0] for x in timestamps), default=None),
            max((x[1] for x in timestamps), default=None),
            None if plan is None else len(plan.cells),
            statuses.count("succeeded"),
            statuses.count("failed"),
            None if plan is None else statuses.count("missing"),
            statuses.count("invalid"),
            statuses.count("conflicted"),
            None if plan is None else len(plan.evaluations),
            eval_statuses.count("succeeded"),
            eval_statuses.count("failed"),
            None if plan is None else eval_statuses.count("missing"),
            eval_statuses.count("invalid"),
            eval_statuses.count("conflicted"),
            exclusions,
            cost,
            issues,
        )

    def cell(self, run_key: str, cell_id: str) -> CellDetail:
        detail = self.run(run_key)
        summary = next((x for x in detail.cells if x.cell_id == cell_id), None)
        if summary is None:
            raise KeyError(cell_id)
        run = self._run(run_key)
        refs = run.execution_records.get(cell_id, ())
        outcome = None
        if len(refs) == 1:
            outcome, _ = _model(self.store, refs[0], ExecutionOutcome)
        plan, _ = _model(self.store, run.plan_ref, ExecutionPlan)
        input_ref = (
            outcome.input_ref
            if outcome
            else next(
                (
                    x.realization_ref
                    for x in (plan.cells if isinstance(plan, ExecutionPlan) else ())
                    if x.id == cell_id
                ),
                None,
            )
        )
        output_text, output_preview = _source(self.store, outcome.output_ref if outcome else None)
        trace_preview = (
            preview(self.store, outcome.trace_ref) if outcome and outcome.trace_ref else None
        )
        recorded_prompt = None
        if outcome and outcome.trace_ref and trace_preview and not trace_preview.truncated:
            trace, _ = _safe_json(self.store, outcome.trace_ref)
            if isinstance(trace, dict) and isinstance(trace.get("prompt"), str):
                recorded_prompt = trace["prompt"]
        plan = cast(ExecutionPlan | None, plan)
        coordinates = (
            tuple(
                (item.evaluator_id, item.evaluator_repeat)
                for item in plan.evaluations
                if item.cell_id == cell_id
            )
            if plan is not None
            else tuple(
                (key.rsplit(":", 2)[-2], int(key.rsplit(":e", 1)[1]))
                for key in run.evaluation_records
                if key.startswith(cell_id + ":")
            )
        )
        evaluations = tuple(
            self._evaluation(run, cell_id, evaluator_id, repeat)
            for evaluator_id, repeat in coordinates
        )
        return CellDetail(
            summary,
            input_ref,
            _input(self.store, input_ref),
            outcome.output_ref if outcome else None,
            output_text,
            output_preview,
            outcome.trace_ref if outcome else None,
            trace_preview,
            recorded_prompt,
            outcome.trace_ref if recorded_prompt and outcome else None,
            evaluations,
            outcome.started_at if outcome else None,
            outcome.completed_at if outcome else None,
        )

    def pair(
        self,
        run_key: str,
        subject_id: str,
        reference_arm: str | None = None,
        candidate_arm: str | None = None,
    ) -> PairView:
        run_detail = self.run(run_key)
        arms = [x.id for x in run_detail.arms]
        reference_arm = reference_arm or next(
            (x for x in ("reference", "clean") if x in arms),
            arms[0] if arms else "reference",
        )
        candidate_arm = candidate_arm or next(
            (x for x in ("candidate", "inconsistent") if x in arms),
            next((x for x in arms if x != reference_arm), "candidate"),
        )
        refs = sorted(
            (
                x
                for x in run_detail.cells
                if x.subject_id == subject_id and x.arm_id == reference_arm
            ),
            key=lambda x: x.worker_repeat,
        )
        candidates = sorted(
            (
                x
                for x in run_detail.cells
                if x.subject_id == subject_id and x.arm_id == candidate_arm
            ),
            key=lambda x: x.worker_repeat,
        )
        repeat_count = run_detail.summary.worker_repeats or max(
            [x.worker_repeat + 1 for x in (*refs, *candidates)], default=0
        )
        ref_by = {x.worker_repeat: x for x in refs}
        candidate_by = {x.worker_repeat: x for x in candidates}
        ref_details = tuple(
            self.cell(run_key, ref_by[n].cell_id)
            if n in ref_by
            else _placeholder(run_key, subject_id, reference_arm, n)
            for n in range(repeat_count)
        )
        candidate_details = tuple(
            self.cell(run_key, candidate_by[n].cell_id)
            if n in candidate_by
            else _placeholder(run_key, subject_id, candidate_arm, n)
            for n in range(repeat_count)
        )
        snapshot = (
            _model(self.store, run_detail.summary.snapshot_ref, StudySnapshot)[0]
            if run_detail.summary.snapshot_ref
            else None
        )
        realizations = (
            {(x.subject_id, x.arm_id): x.artifact_ref for x in snapshot.realizations}
            if snapshot
            else {}
        )
        treatment = _diff_input(
            self.store,
            realizations.get((subject_id, reference_arm)),
            realizations.get((subject_id, candidate_arm)),
        )
        output_diffs = tuple(
            _diff(a.output_text, b.output_text, a.output_ref, b.output_ref)
            for a, b in zip(ref_details, candidate_details, strict=True)
        )
        label = next((x.label for x in run_detail.subjects if x.id == subject_id), None)
        return PairView(
            run_key,
            subject_id,
            label,
            reference_arm,
            candidate_arm,
            ref_details,
            candidate_details,
            treatment,
            output_diffs,
            (),
        )

    def report(self, report_ref: str) -> ReportDetail:
        value, issues = _safe_json(self.store, report_ref)
        if issues or not isinstance(value, dict):
            raise ReadError(issues[0].message if issues else "report root is not an object")
        report = cast(JSONObject, value)
        config_ref = value.get("config_ref")
        if not isinstance(config_ref, str):
            raise ReadError("report has no valid config_ref")
        config, config_issues = _model(self.store, config_ref, ReportConfig)
        summary = _report_summary(report_ref, value, config_ref, config, config_issues)
        comparisons = tuple(
            _comparison(x, config) for x in value.get("comparisons", []) if isinstance(x, dict)
        )
        exclusions = tuple(
            ExclusionView(
                str(x.get("subject_id", "")),
                str(x.get("arm_id", "")),
                str(x.get("classification", "")),
                str(x.get("reason", "")),
                cast(str | None, x.get("manifest_ref")),
            )
            for x in value.get("exclusions", [])
            if isinstance(x, dict)
        )
        costs = _persisted_cost(value.get("costs"), tuple(config_issues))
        missingness = (
            cast(JSONObject, value.get("missingness", {}))
            if isinstance(value.get("missingness", {}), dict)
            else {}
        )
        labels = (
            {str(k): str(v) for k, v in value.get("subject_labels", {}).items()}
            if isinstance(value.get("subject_labels"), dict)
            else {}
        )
        return ReportDetail(summary, report, comparisons, missingness, exclusions, costs, labels)

    def recompute(self, report_ref: str) -> RecomputeResult:
        detail = self.report(report_ref)
        stored = digest_bytes(canonical_json(detail.report))
        if not detail.summary.recomputable:
            return RecomputeResult(
                "unsupported", None, stored, None, detail.summary.recompute_disabled_reason
            )
        config = ReportConfig.model_validate(_json(self.store, detail.summary.config_ref))
        try:
            value = build_report(self.store, config)
            digest = digest_bytes(canonical_json(value))
            return RecomputeResult(
                "matched" if digest == stored else "mismatched",
                digest == stored,
                stored,
                digest,
                None,
            )
        except Exception as error:
            return RecomputeResult(
                "failed", None, stored, None, f"recomputation failed: {type(error).__name__}"
            )

    def ambiguities(self) -> tuple[EvaluationView, ...]:
        result: list[EvaluationView] = []
        for run in self.index.runs:
            detail = self.run(run.run_key)
            for cell in detail.cells:
                result.extend(
                    item
                    for item in self.cell(run.run_key, cell.cell_id).evaluations
                    if item.error_type == "AmbiguousStructure"
                )
        return tuple(result)


def _categories(configuration: Any) -> tuple[str, ...] | None:
    if isinstance(configuration, dict):
        value = configuration.get("categories")
        if isinstance(value, (list, tuple)) and all(isinstance(x, str) for x in value):
            return tuple(value)
    return None


def _evaluation_label(value: EvaluationView) -> str:
    if value.error_type == "AmbiguousStructure":
        return "Missing evidence: ambiguous structure"
    if value.error_type == "ExecutionUnavailable":
        return "Execution unavailable"
    if value.status == "failed":
        return value.error_type or "Evaluation failed"
    return value.status.capitalize()


def _placeholder(run_key: str, subject: str, arm: str, repeat: int) -> CellDetail:
    summary = CellSummary(
        f"{subject}:{arm}:w{repeat}", subject, arm, repeat, "missing", None, None, (), None, (), ()
    )
    return CellDetail(
        summary,
        None,
        InputView("unavailable", None, None, None),
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        (),
        None,
        None,
    )


def _diff(
    left: str | None, right: str | None, left_ref: str | None, right_ref: str | None
) -> DiffView:
    if left is None or right is None:
        return DiffView(
            left_ref, right_ref, left, right, None, "source is unavailable on one or both sides"
        )
    if (
        len(left.encode()) > MAX_DIFF_BYTES
        or len(right.encode()) > MAX_DIFF_BYTES
        or len(left.splitlines()) > MAX_DIFF_LINES
        or len(right.splitlines()) > MAX_DIFF_LINES
    ):
        return DiffView(
            left_ref,
            right_ref,
            left,
            right,
            None,
            "diff suppressed: source exceeds 256 KiB or 5,000 lines",
        )
    unified = "".join(
        difflib.unified_diff(
            left.splitlines(True),
            right.splitlines(True),
            fromfile=left_ref or "left",
            tofile=right_ref or "right",
            n=3,
        )
    )
    return DiffView(left_ref, right_ref, left, right, unified, None)


def _diff_input(session: ObjectStore, left_ref: str | None, right_ref: str | None) -> DiffView:
    def project(ref: str | None) -> str | None:
        if ref is None:
            return None
        value, issues = _safe_json(session, ref)
        if issues or not isinstance(value, dict):
            return None
        task, repository = value.get("task"), value.get("repository")
        if not isinstance(task, dict) or not isinstance(repository, dict):
            return None
        parts = [str(task.get("instruction", ""))]
        for path in sorted(repository):
            if isinstance(path, str) and isinstance(repository[path], str):
                parts.extend((f"\n--- {path} ---\n", repository[path]))
        return "".join(parts)

    return _diff(project(left_ref), project(right_ref), left_ref, right_ref)


def _report_summary(
    ref: str,
    report: dict[str, Any],
    config_ref: str,
    config: ReportConfig | None,
    issues: tuple[ReadIssue, ...],
) -> ReportSummary:
    manifests = tuple(x for x in report.get("manifest_refs", ()) if isinstance(x, str))
    if config is None:
        return ReportSummary(
            ref,
            config_ref,
            cast(Any, report.get("metric", "scalar")),
            str(report.get("evaluator_id", "")),
            cast(Any, report.get("reference_arm")),
            cast(
                Any,
                tuple(report["candidates"]) if isinstance(report.get("candidates"), list) else None,
            ),
            None,
            False,
            "report configuration is missing or invalid",
            manifests,
            issues,
        )
    reason = (
        None
        if config.engine_version == __version__
        else f"report engine {config.engine_version} is unsupported by {__version__}"
    )
    return ReportSummary(
        ref,
        config_ref,
        config.metric,
        config.evaluator_id,
        config.reference_arm,
        config.candidates,
        config.engine_version,
        reason is None,
        reason,
        config.manifest_refs,
        issues,
    )


def _comparison(value: dict[str, Any], config: ReportConfig | None) -> ComparisonView:
    metric = config.metric if config else value.get("metric")
    kind = (
        "numeric"
        if metric == "scalar"
        or (metric == "ordinal" and config and config.ordinal_mapping is not None)
        else metric
        if metric in ("ordinal", "classification")
        else "unknown"
    )
    reference = str(
        value.get("reference", value.get("reference_arm", config.reference_arm if config else ""))
    )
    candidate = str(value.get("candidate", value.get("candidate_arm", "")))
    return ComparisonView(cast(Any, kind), reference, candidate, cast(JSONObject, dict(value)))


def _persisted_cost(value: Any, issues: tuple[ReadIssue, ...]) -> CostView:
    if not isinstance(value, dict):
        return _empty_cost(*issues)
    return CostView(
        cast(Any, value.get("coverage", "unavailable")),
        {str(k): int(v) for k, v in value.get("coverage_counts", {}).items()},
        {str(k): float(v) for k, v in value.get("amounts", {}).items()},
        cast(JSONObject, value.get("by_stage_arm", {})),
        int(value.get("attempts", 0)),
        None,
        None,
        bool(issues) or value.get("coverage") != "measured",
        issues,
    )


def read_run(store: ObjectStore, index: ReviewIndex, run_key: str) -> RunDetail:
    return ReviewReader(store, index).run(run_key)


def read_store(store: ObjectStore, index: ReviewIndex) -> StoreSummary:
    return ReviewReader(store, index).store_summary()


def read_cell(store: ObjectStore, index: ReviewIndex, run_key: str, cell_id: str) -> CellDetail:
    return ReviewReader(store, index).cell(run_key, cell_id)


def read_pair(
    store: ObjectStore,
    index: ReviewIndex,
    run_key: str,
    subject_id: str,
    reference_arm: str | None = None,
    candidate_arm: str | None = None,
) -> PairView:
    return ReviewReader(store, index).pair(run_key, subject_id, reference_arm, candidate_arm)


def read_report(store: ObjectStore, index: ReviewIndex, report_ref: str) -> ReportDetail:
    return ReviewReader(store, index).report(report_ref)


def recompute_report(store: ObjectStore, index: ReviewIndex, report_ref: str) -> RecomputeResult:
    return ReviewReader(store, index).recompute(report_ref)


def read_ambiguities(store: ObjectStore, index: ReviewIndex) -> tuple[EvaluationView, ...]:
    return ReviewReader(store, index).ambiguities()


def verify(
    store: ObjectStore, root_ref: str, scope: Literal["root", "bundle"] = "root"
) -> VerificationResult:
    """Dispatch current verification or perform honest closure-only legacy checks."""
    session = verification_session(store)
    value, issues = _safe_json(session, root_ref)
    if issues or not isinstance(value, dict):
        failure = ViewVerificationFailure(
            issues[0].code if issues else "invalid_record",
            issues[0].message if issues else "root is not an object",
        )
        return VerificationResult(scope, root_ref, "failed", (), (failure,), None)
    closure_refs, closure_failures = closure(session, root_ref)
    if closure_failures:
        return VerificationResult(scope, root_ref, "failed", (), tuple(closure_failures), None)
    if value.get("record_schema") != "assay-report/0.1.0":
        failures = (
            verify_bundle(session, root_ref)
            if scope == "bundle"
            else verify_manifest(session, root_ref)
        )
        non_incomplete = tuple(x for x in failures if x.code != "incomplete_run")
        status: Literal["passed", "failed", "partial"] = (
            "failed" if non_incomplete else "partial" if failures else "passed"
        )
        return VerificationResult(
            scope,
            root_ref,
            status,
            ("digest", "schema", "reference closure", "plan completeness"),
            tuple(ViewVerificationFailure(x.code, x.message) for x in non_incomplete),
            None,
        )
    config_ref = value.get("config_ref")
    if not isinstance(config_ref, str):
        return VerificationResult(
            scope,
            root_ref,
            "failed",
            (),
            (
                ViewVerificationFailure(
                    "missing_config", "report has no valid configuration reference"
                ),
            ),
            None,
        )
    config, config_issues = _model(session, config_ref, ReportConfig)
    if config is None:
        return VerificationResult(
            scope,
            root_ref,
            "failed",
            (),
            tuple(ViewVerificationFailure(x.code, x.message) for x in config_issues),
            None,
        )
    if config.engine_version == __version__:
        failures = (
            verify_bundle(session, root_ref)
            if scope == "bundle"
            else verify_report(session, root_ref)
        )
        return VerificationResult(
            scope,
            root_ref,
            "failed" if failures else "passed",
            ("digest", "schema", "reference closure", "report recomputation"),
            tuple(ViewVerificationFailure(x.code, x.message) for x in failures),
            None,
        )
    if scope == "bundle" and not closure_failures:
        actual = {
            "sha256:" + p.name
            for p in session.objects.iterdir()
            if p.is_file() and re.fullmatch(r"[0-9a-f]{64}", p.name)
        }
        if actual != closure_refs:
            closure_failures.append(
                ViewVerificationFailure(
                    "bundle_closure", "bundle object set differs from the reachable closure"
                )
            )
    if closure_failures:
        return VerificationResult(scope, root_ref, "failed", (), tuple(closure_failures), None)
    reason = f"report recomputation is unsupported for engine {config.engine_version}"
    return VerificationResult(
        scope,
        root_ref,
        "partial",
        (
            "digest",
            "canonical JSON",
            "recognized schemas",
            "reference closure",
            *(("bundle object set",) if scope == "bundle" else ()),
        ),
        (),
        reason,
    )


def closure(
    session: ObjectStore, root_ref: str
) -> tuple[set[str], list[ViewVerificationFailure]]:
    """Walk a root closure and return stable reference-attributed failures."""
    pending: list[tuple[str, str, str | None]] = [(root_ref, "auto", None)]
    seen: set[tuple[str, str]] = set()
    refs: set[str] = set()
    failures: list[ViewVerificationFailure] = []
    while pending:
        ref, role, referrer = pending.pop()
        if (ref, role) in seen:
            continue
        seen.add((ref, role))
        refs.add(ref)
        try:
            raw = session.read_bytes(ref)
        except (OSError, ObjectIntegrityError, ValueError) as error:
            issue = _error_issue(ref, error)
            failures.append(
                ViewVerificationFailure(
                    issue.code, f"{issue.message}; referenced by {referrer or 'root'}"
                )
            )
            continue
        try:
            value = json.loads(raw)
        except (UnicodeDecodeError, ValueError):
            if role == "data":
                continue
            failures.append(
                ViewVerificationFailure(
                    "invalid_record",
                    f"recognized object is not canonical JSON: {ref}; "
                    f"referenced by {referrer or 'root'}",
                )
            )
            continue
        try:
            if canonical_json(value) != raw:
                raise ValueError
            for child, child_role in object_edges(value, role):
                pending.append((child, child_role, ref))
        except (TypeError, ValueError):
            failures.append(
                ViewVerificationFailure(
                    "invalid_record", f"recognized references are invalid in {ref}"
                )
            )
    return refs, failures
