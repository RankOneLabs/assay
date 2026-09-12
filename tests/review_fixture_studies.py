from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from review_fixture import HOSTILE_TEXT, contracts

from assay._version import __version__
from assay.canonical import canonical_json, digest_bytes
from assay.execution import (
    EvaluationFailed,
    EvaluationResult,
    EvaluationSuccess,
    RunSucceeded,
    WorkerResult,
    WorkerSuccess,
    execute_plan,
)
from assay.investigations.consistency import (
    CATEGORIES,
    EXPERIMENT_TASKS,
    StructuralEvaluator,
    materialize_consistency,
)
from assay.models import (
    Arm,
    EvaluationCoordinate,
    EvaluatorDeclaration,
    Realization,
    ReportConfig,
    StatisticalProfile,
    StudySnapshot,
    Subject,
)
from assay.planning import compile_plan
from assay.report_engine import build_report, persist_report
from assay.store import ObjectStore
from assay.verify import export_bundle, verify_bundle, verify_manifest, verify_snapshot


@dataclass(frozen=True)
class ReviewStudies:
    store: ObjectStore
    report_configs: dict[str, ReportConfig]
    reports: dict[str, dict[str, Any]]
    report_refs: dict[str, str]
    report_bundles: dict[str, ObjectStore]
    stale_config_ref: str
    stale_report_ref: str


class StudyWorker:
    def configuration(self, arm_id: str) -> dict[str, Any]:
        del arm_id
        return {"id": "review-study", "version": "1", "offline": True}

    async def run(self, *, input_value: Any, arm_id: str) -> WorkerResult:
        return WorkerSuccess(
            {
                "index": input_value["index"],
                "arm": arm_id,
                "source": "generated review study output: " + HOSTILE_TEXT,
            }
        )


class NumericEvaluator:
    def configuration(self) -> dict[str, Any]:
        return {"id": "numeric-review", "version": "1"}

    async def evaluate(
        self, *, input_value: Any, output: Any, coordinate: EvaluationCoordinate
    ) -> EvaluationResult:
        del input_value, coordinate
        if output["arm"] == "candidate" and output["index"] == 0:
            return EvaluationFailed("DescriptiveOnly", "numeric fixture gap: " + HOSTILE_TEXT)
        return EvaluationSuccess(float(output["index"] + (output["arm"] == "candidate")))


class LabelEvaluator:
    def configuration(self) -> dict[str, Any]:
        return {"id": "label-review", "version": "1"}

    async def evaluate(
        self, *, input_value: Any, output: Any, coordinate: EvaluationCoordinate
    ) -> EvaluationResult:
        del input_value, coordinate
        return EvaluationSuccess("good" if output["arm"] == "candidate" else "bad")


class ConsistencyWorker:
    def configuration(self, arm_id: str) -> dict[str, Any]:
        del arm_id
        return {"id": "review-consistency", "version": "1", "offline": True}

    async def run(self, *, input_value: Any, arm_id: str) -> WorkerResult:
        task_id = input_value["task"]["id"]
        task = next(task for task in EXPERIMENT_TASKS if task.id == task_id)
        source = task.reused_source if arm_id == "clean" else task.duplicated_source
        return WorkerSuccess({"source": source})


def _publish(store: ObjectStore, value: Any) -> str:
    return str(store.publish_json(value))


def _payload_schema(schema_id: str, verdict: dict[str, Any]) -> dict[str, Any]:
    ref = {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"}
    fields: dict[str, Any] = {
        key: {"type": "string", "minLength": 1}
        for key in ("run_id", "cell_id", "evaluator_id", "arm_id")
    }
    fields.update(
        plan_ref=ref,
        base_subject_ref=ref,
        worker_repeat={"type": "integer", "minimum": 0},
        evaluator_repeat={"type": "integer", "minimum": 0},
        detail_refs={"type": "array", "items": ref, "uniqueItems": True},
    )
    return {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "$id": schema_id,
        "allOf": [
            {"$ref": "https://paa.dev/paa-evidence-record.schema.json"},
            {
                "properties": {
                    "verdict": {"properties": {"value": verdict}},
                    "payload": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": list(fields),
                        "properties": fields,
                    },
                }
            },
        ],
    }


def _identity(name: str, basis_ref: str) -> dict[str, Any]:
    return {
        "property": name,
        "target": "output",
        "technique": "deterministic",
        "evaluation_basis": {"kind": "rubric", "ref": basis_ref},
        "epistemic_status": "proxy",
        "version": "1",
        "authority": "advisory",
    }


def _study_snapshot(store: ObjectStore, schemas: dict[str, dict[str, Any]]) -> StudySnapshot:
    worker = StudyWorker()
    arms = tuple(
        Arm(id=arm, worker=worker.configuration(arm), intervention={"variant": arm})
        for arm in ("reference", "candidate")
    )
    subjects = []
    realizations = []
    for index in range(10):
        subject_id = f"review-subject-{index:02d}"
        label = f"Study subject {index}" + (": " + HOSTILE_TEXT if index == 0 else "")
        payload_ref = _publish(store, {"index": index, "label": "good"})
        subjects.append(
            Subject(
                id=subject_id,
                label=label,
                digest=payload_ref,
                partition="review",
                payload_ref=payload_ref,
            )
        )
        for arm in arms:
            artifact_ref = _publish(store, {"index": index, "arm": arm.id})
            realizations.append(
                Realization(
                    subject_id=subject_id,
                    arm_id=arm.id,
                    digest=artifact_ref,
                    artifact_ref=artifact_ref,
                )
            )

    numeric_basis = _publish(store, {"rubric": "numeric review score"})
    label_basis = _publish(store, {"rubric": "bad or good review label"})
    numeric_identity = _identity("review_score", numeric_basis)
    label_identity = _identity("review_classification", label_basis)
    numeric_schema = _payload_schema(
        "https://assay.test/review-numeric-v1.json", {"type": "number"}
    )
    label_schema = _payload_schema(
        "https://assay.test/review-label-v1.json", {"enum": ["bad", "good"]}
    )
    evaluators = (
        EvaluatorDeclaration(
            id="label",
            identity=label_identity,
            payload_schema=label_schema["$id"],
            payload_schema_ref=_publish(store, label_schema),
            basis_ref=label_basis,
            configuration=LabelEvaluator().configuration(),
            repeats=1,
        ),
        EvaluatorDeclaration(
            id="numeric",
            identity=numeric_identity,
            payload_schema=numeric_schema["$id"],
            payload_schema_ref=_publish(store, numeric_schema),
            basis_ref=numeric_basis,
            configuration=NumericEvaluator().configuration(),
            repeats=1,
        ),
    )
    task = {
        "task": "review_fixture_study",
        "version": 1,
        "description": "Offline scalar, ordinal, and classification review material",
        "boundary": {"input": "fixture subject", "output": "fixture result"},
        "initial_position": "manual",
        "deployment": "shadow",
        "evaluators": [numeric_identity, label_identity],
        "position_policy": {"manual": "offline", "hitl": "blocking"},
        "promotion": {
            "from": "manual",
            "to": "hitl",
            "report": "review report",
            "window": {"kind": "cases", "size": 10},
            "execution": "operator_approval",
        },
        "demotion": {
            "from": "hitl",
            "to": "manual",
            "trigger": "operator_decision",
            "window": {"kind": "cases", "size": 1},
        },
    }
    return StudySnapshot(
        subjects=tuple(subjects),
        arms=arms,
        realizations=tuple(realizations),
        evaluators=evaluators,
        paa_task_ref=_publish(store, task),
        task_schema_ref=_publish(store, schemas["paa-task"]),
        evidence_schema_ref=_publish(store, schemas["paa-evidence-record"]),
        operating_schema_ref=_publish(store, schemas["paa-operating-record"]),
        pricing_catalog_ref=_publish(store, {"prices": [], "coverage": "unavailable"}),
    )


async def _run(
    store: ObjectStore,
    snapshot: StudySnapshot,
    workers: dict[str, Any],
    evaluators: dict[str, Any],
    revision: str,
) -> RunSucceeded:
    verify_snapshot(store, snapshot)
    snapshot_ref = _publish(store, snapshot.model_dump(mode="json"))
    plan = compile_plan(
        snapshot,
        snapshot_ref=snapshot_ref,
        worker_repeats=1,
        jig_revision=revision,
        concurrency=4,
    )
    plan_bytes = canonical_json(plan.model_dump(mode="json"))
    result = await execute_plan(
        plan_bytes=plan_bytes,
        authorization=digest_bytes(plan_bytes),
        snapshot=snapshot,
        store=store,
        workers=workers,
        evaluators=evaluators,
    )
    if not isinstance(result, RunSucceeded) or verify_manifest(store, str(result.manifest_ref)):
        raise AssertionError(f"review study did not complete: {result}")
    return result


async def _execute_study(store: ObjectStore, schemas: dict[str, dict[str, Any]]) -> RunSucceeded:
    snapshot = _study_snapshot(store, schemas)
    worker = StudyWorker()
    return await _run(
        store,
        snapshot,
        {arm.id: worker for arm in snapshot.arms},
        {"label": LabelEvaluator(), "numeric": NumericEvaluator()},
        "review-study",
    )


async def _execute_consistency(
    store: ObjectStore, schemas: dict[str, dict[str, Any]]
) -> RunSucceeded:
    worker = ConsistencyWorker()
    evaluator = StructuralEvaluator()
    snapshot = materialize_consistency(
        store,
        worker_configuration=worker.configuration("clean"),
        evaluator=evaluator,
        schemas=schemas,
        tasks=EXPERIMENT_TASKS,
        evaluator_repeats=1,
    )
    return await _run(
        store,
        snapshot,
        {"clean": worker, "inconsistent": worker},
        {"abstraction": evaluator},
        "review-consistency",
    )


def _records(result: RunSucceeded, evaluator_id: str) -> tuple[str, ...]:
    marker = f":{evaluator_id}:e"
    return tuple(
        sorted(
            ref
            for coordinate, ref in result.manifest.evaluation_records.items()
            if marker in coordinate
        )
    )


def _config(result: RunSucceeded, evaluator_id: str, metric: Any, **updates: Any) -> ReportConfig:
    return ReportConfig(
        manifest_refs=(str(result.manifest_ref),),
        record_refs=_records(result, evaluator_id),
        reference_arm="reference",
        candidates=("candidate",),
        evaluator_id=evaluator_id,
        metric=metric,
        scalar_direction="higher_is_better" if metric == "scalar" else None,
        evaluator_repeat_aggregation="mean" if metric == "scalar" else "majority",
        worker_repeat_aggregation="mean" if metric == "scalar" else "majority",
        categories=() if metric == "scalar" else ("bad", "good"),
        positive_label="good" if metric == "classification" else None,
        statistical_profile=StatisticalProfile(seed=17, bootstrap_samples=100),
        engine_version=__version__,
    ).model_copy(update=updates)


async def materialize_review_studies(store: ObjectStore, bundle_root: Path) -> ReviewStudies:
    """Populate one store with every report shape consumed by review clients."""
    schemas = contracts()
    general = await _execute_study(store, schemas)
    consistency = await _execute_consistency(store, schemas)
    configs = {
        "scalar": _config(general, "numeric", "scalar"),
        "mapped_ordinal": _config(
            general,
            "label",
            "ordinal",
            scalar_direction="higher_is_better",
            ordinal_mapping={"bad": 0.0, "good": 1.0},
            evaluator_repeat_aggregation="median",
            worker_repeat_aggregation="median",
        ),
        "classification": _config(general, "label", "classification"),
        "unmapped_ordinal": ReportConfig(
            manifest_refs=(str(consistency.manifest_ref),),
            record_refs=_records(consistency, "abstraction"),
            reference_arm="clean",
            candidates=("inconsistent",),
            evaluator_id="abstraction",
            metric="ordinal",
            categories=CATEGORIES,
            evaluator_repeat_aggregation="median",
            worker_repeat_aggregation="median",
            statistical_profile=StatisticalProfile(seed=23, bootstrap_samples=100),
            engine_version=__version__,
        ),
    }
    reports = {name: build_report(store, config) for name, config in configs.items()}
    report_refs = {name: str(persist_report(store, config)) for name, config in configs.items()}
    bundles = {}
    for name, report_ref in report_refs.items():
        bundle = export_bundle(store, report_ref, bundle_root / name)
        if verify_bundle(bundle, report_ref):
            raise AssertionError(f"{name} report bundle does not verify")
        bundles[name] = bundle

    stale_config = configs["scalar"].model_copy(
        update={"engine_version": __version__ + "-stale"}
    )
    stale_config_ref = _publish(store, stale_config.model_dump(mode="json"))
    stale_report = json.loads(store.read_bytes(report_refs["scalar"]))
    stale_report["config_ref"] = stale_config_ref
    stale_report_ref = _publish(store, stale_report)
    return ReviewStudies(
        store,
        report_configs=configs,
        reports=reports,
        report_refs=report_refs,
        report_bundles=bundles,
        stale_config_ref=stale_config_ref,
        stale_report_ref=stale_report_ref,
    )


@pytest.fixture
async def review_studies(tmp_path: Path) -> ReviewStudies:
    return await materialize_review_studies(
        ObjectStore(tmp_path / "study-store"), tmp_path / "study-bundles"
    )
