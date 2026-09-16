"""Offline schema, lineage, content closure, and plan completeness verification."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from assay.canonical import canonical_json, digest_bytes
from assay.models import (
    EvaluationFailure,
    ExecutionOutcome,
    ReportConfig,
    RunManifest,
    StudySnapshot,
    parse_execution_plan,
)
from assay.planning import require_runtime_closure, validate_plan_snapshot
from assay.references import object_edges, walk_closure
from assay.references import reference_closure as reference_closure
from assay.schema_validation import SUPPORTED_CONTRACTS as SUPPORTED_CONTRACTS
from assay.schema_validation import schema_validators
from assay.store import ObjectRef, ObjectStore, verification_session


@dataclass(frozen=True, slots=True)
class VerificationFailure:
    code: str
    message: str


def _json(store: ObjectStore, ref: str, expected_schema: str | None = None) -> Any:
    data = store.read_bytes(ref)
    value = json.loads(data)
    if canonical_json(value) != data:
        raise ValueError(f"noncanonical JSON at {ref}")
    if expected_schema is not None and (
        not isinstance(value, dict) or value.get("schema_version") != expected_schema
    ):
        raise ValueError(f"missing or incorrect wire schema identity at {ref}")
    return value


def validate_schema_document(
    store: ObjectStore, snapshot: StudySnapshot, schema_ref: str, document: Any
) -> None:
    """Validate pinned schemas without network retrieval."""
    schema_validators(store, snapshot)[schema_ref].validate(document)


def verify_snapshot(store: ObjectStore, snapshot: StudySnapshot) -> None:
    """Raise for incomplete materialization or task/evaluator/schema mismatches."""
    store = verification_session(store)
    snapshot = StudySnapshot.model_validate(snapshot.model_dump(mode="json"))
    walk_closure(store, object_edges(snapshot.model_dump(mode="json")))
    for realization in snapshot.realizations:
        _json(store, realization.artifact_ref)
    task = _json(store, snapshot.paa_task_ref)
    validate_schema_document(store, snapshot, snapshot.task_schema_ref, task)
    scopes = task.get("scopes")
    if (scopes is None and snapshot.paa_scope is not None) or (
        scopes is not None and snapshot.paa_scope not in scopes
    ):
        raise ValueError("snapshot scope is not declared by the task")
    for evaluator in snapshot.evaluators:
        if evaluator.identity not in task["evaluators"]:
            raise ValueError(f"evaluator {evaluator.id} is not declared by the pinned task")
        payload_schema = _json(store, evaluator.payload_schema_ref)
        if payload_schema["$id"] != evaluator.payload_schema:
            raise ValueError(f"payload schema identity mismatch for {evaluator.id}")


def _check_timestamps(record: dict[str, Any]) -> None:
    values = [
        datetime.fromisoformat(record["timestamps"][name].replace("Z", "+00:00"))
        for name in ("started_at", "completed_at", "recorded_at")
    ]
    if any(value.utcoffset() is None for value in values) or values != sorted(values):
        raise ValueError("record timestamps must be timezone-aware and ordered")


def verify_manifest(store: ObjectStore, manifest_ref: str) -> tuple[VerificationFailure, ...]:
    store = verification_session(store)
    failures: list[VerificationFailure] = []
    try:
        manifest = RunManifest.model_validate(
            _json(store, manifest_ref, "assay-run-manifest/0.1.0")
        )
        plan = parse_execution_plan(_json(store, manifest.plan_ref))
        snapshot = StudySnapshot.model_validate(
            _json(store, plan.snapshot_ref, "assay-study-snapshot/0.1.0")
        )
        validate_plan_snapshot(plan, snapshot)
        verify_snapshot(store, snapshot)
        require_runtime_closure(store, plan)
        reference_closure(store, (manifest_ref,))
        task = _json(store, snapshot.paa_task_ref)
        validators = schema_validators(store, snapshot)
    except Exception as error:
        return (VerificationFailure("manifest_context", str(error)),)
    cells = {cell.id: cell for cell in plan.cells}
    evaluations = {item.id: item for item in plan.evaluations}
    actual_execution = set(manifest.execution_records)
    actual_evaluation = set(manifest.evaluation_records)
    if actual_execution - cells.keys():
        failures.append(VerificationFailure("execution_coordinates", "unplanned executions"))
    if actual_evaluation - evaluations.keys():
        failures.append(VerificationFailure("evaluation_coordinates", "unplanned evaluations"))
    outcomes: dict[str, ExecutionOutcome] = {}
    outcome: ExecutionOutcome | None
    for key, ref in manifest.execution_records.items():
        try:
            outcome = ExecutionOutcome.model_validate(
                _json(store, ref, "assay-execution-outcome/0.1.0")
            )
            if outcome.coordinate != cells.get(key):
                raise ValueError("execution coordinate does not match manifest and plan")
            if outcome.run_id != manifest.run_id or outcome.plan_ref != manifest.plan_ref:
                raise ValueError("execution belongs to a different run or plan")
            for artifact in (outcome.input_ref, outcome.output_ref, outcome.trace_ref):
                if artifact is not None:
                    _json(store, artifact)
            outcomes[key] = outcome
        except Exception as error:
            failures.append(VerificationFailure("execution_record", f"{key}: {error}"))
    declarations = {item.id: item for item in snapshot.evaluators}
    subjects = {item.id: item for item in snapshot.subjects}
    arms = {item.id: item for item in snapshot.arms}
    expected_operating = {f"worker:{key}" for key in outcomes}
    unavailable_evaluations: set[str] = set()
    for key, ref in manifest.evaluation_records.items():
        try:
            coordinate = evaluations[key]
            record = _json(store, ref)
            outcome = outcomes.get(coordinate.cell_id)
            if outcome is None:
                raise ValueError("evaluation has no valid execution record")
            if record.get("schema_version") == "assay-evaluation-failure/0.1.0":
                failure = EvaluationFailure.model_validate(record)
                if failure.coordinate != coordinate:
                    raise ValueError("failure coordinate differs from manifest and plan")
                if failure.run_id != manifest.run_id or failure.plan_ref != manifest.plan_ref:
                    raise ValueError("evaluation failure belongs to another run or plan")
                if failure.trace_ref is not None:
                    _json(store, failure.trace_ref)
                if outcome.status == "failed" and failure.error_type != "ExecutionUnavailable":
                    raise ValueError("failed worker must produce an explicit unavailable skip")
                if outcome.status == "failed":
                    unavailable_evaluations.add(key)
                if outcome.status == "succeeded":
                    expected_operating.add(f"evaluator:{key}")
                continue
            if outcome.status != "succeeded":
                raise ValueError("evidence cannot evaluate a failed worker")
            declaration = declarations[coordinate.evaluator_id]
            expected_operating.add(f"evaluator:{key}")
            validators[snapshot.evidence_schema_ref].validate(record)
            validators[declaration.payload_schema_ref].validate(record)
            cell = cells[coordinate.cell_id]
            arm = arms[cell.arm_id]
            if record["record_id"] != f"{manifest.run_id}:{key}":
                raise ValueError("evidence record identity differs from run and coordinate")
            if record["task"] != task["task"] or record["declaration_version"] != task["version"]:
                raise ValueError("evidence task/version differs from pinned task")
            if record["scope"] != snapshot.paa_scope or record["evaluator"] != declaration.identity:
                raise ValueError("evidence scope/evaluator differs from declaration")
            if record["payload_schema"] != declaration.payload_schema:
                raise ValueError("evidence payload schema differs from declaration")
            if record["subject"] != {
                "kind": "run",
                "id": f"{manifest.run_id}:{coordinate.cell_id}",
            }:
                raise ValueError("evidence subject differs from cell")
            if record["boundary"] != {
                "input_ref": outcome.input_ref,
                "output_ref": outcome.output_ref,
            }:
                raise ValueError("evidence boundary differs from execution")
            expected_worker = {
                "id": arm.worker["id"],
                "version": arm.worker["version"],
                "configuration_ref": digest_bytes(canonical_json(arm.worker)),
            }
            if record.get("worker") != expected_worker:
                raise ValueError("evidence worker differs from authorized worker")
            expected_payload = {
                "run_id": manifest.run_id,
                "plan_ref": manifest.plan_ref,
                "cell_id": coordinate.cell_id,
                "evaluator_id": coordinate.evaluator_id,
                "arm_id": cell.arm_id,
                "base_subject_ref": subjects[cell.subject_id].digest,
                "worker_repeat": cell.worker_repeat,
                "evaluator_repeat": coordinate.evaluator_repeat,
            }
            if any(
                record["payload"].get(name) != value for name, value in expected_payload.items()
            ):
                raise ValueError("evidence payload coordinates differ from manifest and plan")
            if manifest.execution_records[coordinate.cell_id] not in record["source_references"]:
                raise ValueError("evidence omits its execution source")
            evidence_sources = {str(ObjectRef(ref)) for ref in record["source_references"]}
            details = record["payload"].get("detail_refs")
            if not isinstance(details, list):
                raise ValueError("evidence detail_refs must be an array of object references")
            detail_refs = {str(ObjectRef(ref)) for ref in details}
            required_sources = {
                manifest.execution_records[coordinate.cell_id],
                snapshot.paa_task_ref,
                expected_worker["configuration_ref"],
                declaration.basis_ref,
                *detail_refs,
            }
            if not required_sources <= evidence_sources:
                raise ValueError(
                    "evidence omits authoritative task/configuration/basis/detail sources"
                )
            for detail_ref in detail_refs:
                _json(store, detail_ref)
            if record["producer"] != {"id": "assay", "version": plan.assay_version}:
                raise ValueError("evidence producer differs from plan")
            _check_timestamps(record)
        except Exception as error:
            failures.append(VerificationFailure("evaluation_record", f"{key}: {error}"))
    missing_operating = expected_operating - manifest.operating_records.keys()
    if (
        manifest.operating_records.keys() - expected_operating
        or missing_operating - set(manifest.missing_coordinates)
    ):
        failures.append(
            VerificationFailure("operating_coordinates", "attempt accounting is incomplete")
        )
    for key, ref in manifest.operating_records.items():
        try:
            record = _json(store, ref)
            validators[snapshot.operating_schema_ref].validate(record)
            for source in record["source_references"]:
                ObjectRef(source)
            if "components" in record:
                raise ValueError("component prices are unsupported; provide complete attempt price")
            role, _, coordinate_id = key.partition(":")
            sources = (
                manifest.execution_records if role == "worker" else manifest.evaluation_records
            )
            if role not in ("worker", "evaluator") or coordinate_id not in sources:
                raise ValueError("operating record does not identify a recorded attempt")
            if sources[coordinate_id] not in record["source_references"]:
                raise ValueError("operating record omits its terminal attempt source")
            if record["record_id"] != f"{manifest.run_id}:{key}":
                raise ValueError("operating identity differs from run and coordinate")
            if record["subject"] != {"kind": "run", "id": f"{manifest.run_id}:{key}"}:
                raise ValueError("operating subject differs from run and coordinate")
            if role == "worker":
                declared_worker = arms[cells[coordinate_id].arm_id].worker
                configuration = declared_worker
                worker_identity = {
                    "id": declared_worker["id"],
                    "version": declared_worker["version"],
                }
            else:
                evaluator = declarations[evaluations[coordinate_id].evaluator_id]
                configuration = evaluator.configuration
                worker_identity = {"id": evaluator.id, "version": evaluator.identity["version"]}
            config_ref = digest_bytes(canonical_json(configuration))
            if record["worker"] != {**worker_identity, "configuration_ref": config_ref}:
                raise ValueError("operating worker/configuration differs from declared attempt")
            required_sources = {sources[coordinate_id], config_ref, snapshot.pricing_catalog_ref}
            if not required_sources <= set(record["source_references"]):
                raise ValueError("operating sources omit pinned attempt/configuration/pricing")
            detail_refs = set(record["source_references"]) - required_sources
            if len(detail_refs) != 1:
                raise ValueError("operating attempt needs exactly one accounting provenance object")
            detail = _json(store, next(iter(detail_refs)))
            coverage = detail.get("coverage")
            if coverage not in {"measured", "estimated", "unavailable", "mixed", "uncertain"}:
                raise ValueError("invalid accounting coverage")
            if detail != {
                "run_id": manifest.run_id,
                "attempt": key,
                "coverage": coverage,
                "pricing_catalog_ref": snapshot.pricing_catalog_ref,
                "pricing_assumptions": snapshot.pricing_assumptions,
                "configuration_ref": config_ref,
            }:
                raise ValueError(
                    "accounting provenance differs from run/attempt/configuration/pricing"
                )
            if record["price"] is not None and coverage in ("unavailable", "uncertain"):
                raise ValueError("available price cannot have unavailable or uncertain coverage")
            if record["price"] is None and coverage not in ("unavailable", "uncertain"):
                raise ValueError("missing price must have unavailable or uncertain coverage")
            if (
                record["task"] != task["task"]
                or record["declaration_version"] != task["version"]
                or record["scope"] != snapshot.paa_scope
            ):
                raise ValueError("operating record belongs to another task/version/scope")
            _check_timestamps(record)
        except Exception as error:
            failures.append(VerificationFailure("operating_record", f"{key}: {error}"))
    # Failed workers are not graded, but every planned evaluation still needs an
    # explicit unavailable terminal record; omissions cannot masquerade as skips.
    required_evaluation = set(evaluations)
    missing = tuple(
        sorted(
            (cells.keys() - actual_execution)
            | (required_evaluation - actual_evaluation)
            | missing_operating
            | unavailable_evaluations
        )
    )
    if manifest.missing_coordinates != missing:
        failures.append(VerificationFailure("missing_coordinates", "missing list is inconsistent"))
    if manifest.status != ("incomplete" if missing else "complete"):
        failures.append(VerificationFailure("manifest_status", "status misstates completeness"))
    if missing:
        failures.append(
            VerificationFailure("incomplete_run", "run has missing planned coordinates")
        )
    if manifest.interruption_ref is not None:
        try:
            if manifest.status != "incomplete":
                raise ValueError("a cleanup interruption cannot accompany a complete run")
            interruption = _json(store, manifest.interruption_ref)
            if (
                interruption.get("schema_version") != "assay-cleanup-interruption/0.1.0"
                or interruption.get("run_id") != manifest.run_id
            ):
                raise ValueError("cleanup interruption identity differs from this run")
        except Exception as error:
            failures.append(VerificationFailure("cleanup_interruption", str(error)))
    return tuple(failures)


def verify_report(store: ObjectStore, report_ref: str) -> tuple[VerificationFailure, ...]:
    from assay.report_engine import build_report

    store = verification_session(store)
    try:
        report = _json(store, report_ref)
        config = ReportConfig.model_validate(
            _json(store, report["config_ref"], "assay-report-config/0.1.0")
        )
        reference_closure(store, (report_ref,))
        if report != build_report(store, config):
            raise ValueError("report differs from recomputation using pinned inputs")
        return ()
    except Exception as error:
        return (VerificationFailure("report_recomputation", str(error)),)


def verify_bundle(store: ObjectStore, root_ref: str) -> tuple[VerificationFailure, ...]:
    """An exported bundle contains exactly the root's reference closure."""
    store = verification_session(store)
    try:
        root = _json(store, root_ref)
        failures = (
            verify_report(store, root_ref)
            if root.get("record_schema") == "assay-report/0.1.0"
            else verify_manifest(store, root_ref)
        )
        expected = reference_closure(store, (root_ref,))
        actual: set[str] = set()
        for path in store.objects.iterdir():
            if not path.is_file() or re.fullmatch(r"[0-9a-f]{64}", path.name) is None:
                raise ValueError(f"unexpected bundle entry: {path.name}")
            actual.add(f"sha256:{path.name}")
        if actual != expected:
            return (
                *failures,
                VerificationFailure("bundle_closure", "bundle contains extra objects"),
            )
        return failures
    except Exception as error:
        return (VerificationFailure("bundle_integrity", str(error)),)


def export_bundle(store: ObjectStore, root_ref: str, destination: Path | str) -> ObjectStore:
    """Copy a verified root's exact object closure into an empty directory.

    A manifest that is honestly ``incomplete`` (unstarted cells, evaluations
    unavailable because their worker failed, or missing operating records)
    is still self-consistent, recoverable partial evidence — its
    ``incomplete_run`` flag is informational, not a corruption signal, so it
    does not block export. Any other verification failure does.
    """
    store = verification_session(store)
    root = _json(store, root_ref)
    failures = (
        verify_report(store, root_ref)
        if root.get("record_schema") == "assay-report/0.1.0"
        else verify_manifest(store, root_ref)
    )
    blocking = tuple(failure for failure in failures if failure.code != "incomplete_run")
    if blocking:
        raise ValueError(f"cannot export invalid root: {blocking}")
    destination = Path(destination)
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("bundle destination must be empty")
    target = ObjectStore(destination)
    for ref in sorted(reference_closure(store, (root_ref,))):
        target.publish_bytes(store.read_bytes(ref))
    return target
