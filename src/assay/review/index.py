"""Best-effort discovery for stores without an explicit root object.

Discovery is deliberately weaker than verification.  It identifies objects by
their wire discriminators and parses the closed Assay wire types, but it never
turns an observed discriminator into producer attestation or a closure edge.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import ValidationError

from assay.models import (
    EvaluationFailure,
    ExecutionOutcome,
    ExecutionPlan,
    ReportConfig,
    RunManifest,
    StudySnapshot,
)
from assay.review.model import JSONObject, ReadIssue
from assay.store import ObjectRef


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
