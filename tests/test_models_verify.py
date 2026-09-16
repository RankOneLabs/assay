"""Adversarial checks for governed models and offline verification."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import paa_contracts
import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError
from test_execution import execution_fixture

from assay.canonical import canonical_json, digest_bytes
from assay.execution import RunSucceeded, execute_plan
from assay.models import (
    CellCoordinate,
    ExecutionPlan,
    PriceEstimate,
    ReportConfig,
    RuntimeProfile,
    StudySnapshot,
)
from assay.planning import compile_plan, compile_plan_v2, validate_plan_snapshot
from assay.schema_export import plan_schema_registry
from assay.store import ObjectRef, ObjectStore
from assay.verify import (
    SUPPORTED_CONTRACTS,
    export_bundle,
    verify_bundle,
    verify_manifest,
    verify_snapshot,
)


@pytest.mark.parametrize("bad", ["sha256:" + "g" * 64, "sha256:" + "/" * 64, "https://mutable"])
def test_references_reject_nonhash_and_path_values(tmp_path: Path, bad: str) -> None:
    with pytest.raises(ValueError):
        ObjectRef(bad)
    with pytest.raises(ValueError):
        ObjectStore(tmp_path).read_bytes(bad)
    with pytest.raises(ValidationError):
        CellCoordinate(subject_id="s", arm_id="a", worker_repeat=0, realization_ref=bad)


@pytest.mark.parametrize("subject,arm", [("s:a", "b"), ("s", "a:b"), ("", "a")])
def test_coordinate_identifiers_cannot_collide(subject: str, arm: str) -> None:
    with pytest.raises(ValidationError):
        CellCoordinate(
            subject_id=subject, arm_id=arm, worker_repeat=0, realization_ref="sha256:" + "0" * 64
        )


def test_models_reject_duplicate_and_inconsistent_grid(tmp_path: Path) -> None:
    fixture = execution_fixture(ObjectStore(tmp_path))
    snapshot = fixture.snapshot.model_dump(mode="json")
    snapshot["subjects"].append(snapshot["subjects"][0])
    with pytest.raises(ValidationError, match="unique"):
        StudySnapshot.model_validate(snapshot)
    snapshot = fixture.snapshot.model_dump(mode="json")
    snapshot["subjects"][1]["digest"] = snapshot["subjects"][0]["digest"]
    with pytest.raises(ValidationError, match="digests must be unique"):
        StudySnapshot.model_validate(snapshot)
    plan = json.loads(fixture.plan_bytes)
    plan["cells"].append(plan["cells"][0])
    with pytest.raises(ValidationError, match="duplicate"):
        ExecutionPlan.model_validate(plan)
    plan = ExecutionPlan.model_validate_json(fixture.plan_bytes)
    with pytest.raises(ValueError, match="compilation"):
        validate_plan_snapshot(plan.model_copy(update={"cells": ()}), fixture.snapshot)
    with pytest.raises(ValueError, match="snapshot_ref"):
        compile_plan(
            fixture.snapshot,
            snapshot_ref="sha256:" + "0" * 64,
            worker_repeats=1,
            jig_revision="revision",
        )


def test_generated_snapshot_schema_rejects_nested_invalid_and_unknown_fields(
    tmp_path: Path,
) -> None:
    fixture = execution_fixture(ObjectStore(tmp_path))
    path = Path(__file__).resolve().parents[1] / "schemas/assay-study-snapshot.schema.json"
    schema = json.loads(path.read_text())
    validator = Draft202012Validator(schema)
    document = fixture.snapshot.model_dump(mode="json")
    validator.validate(document)
    document["subjects"][0]["surprise"] = True
    assert not validator.is_valid(document)
    document = fixture.snapshot.model_dump(mode="json")
    document["realizations"][0]["artifact_ref"] = "https://mutable.example/latest"
    assert not validator.is_valid(document)
    document = fixture.snapshot.model_dump(mode="json")
    document["evaluators"][0]["identity"]["target"] = "unknown"
    assert not validator.is_valid(document)


def test_generated_plan_schemas_validate_each_pinned_version_only(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    fixture = execution_fixture(store)
    root = Path(__file__).resolve().parents[1] / "schemas"
    v1_validator = Draft202012Validator(
        json.loads((root / "assay-execution-plan-v0.1.schema.json").read_text())
    )
    v2_validator = Draft202012Validator(
        json.loads((root / "assay-execution-plan-v0.2.schema.json").read_text())
    )

    v1_document = json.loads(fixture.plan_bytes)
    v1_validator.validate(v1_document)
    assert not v2_validator.is_valid(v1_document)

    study = fixture.snapshot
    runtime = RuntimeProfile(
        id="pier", version="1.0.0", configuration_ref=str(store.publish_json({"x": 1}))
    )
    v2_plan = compile_plan_v2(
        study,
        snapshot_ref=str(store.publish_json(study.model_dump(mode="json"))),
        worker_repeats=1,
        runtime=runtime,
    )
    v2_document = v2_plan.model_dump(mode="json")
    v2_validator.validate(v2_document)
    assert not v1_validator.is_valid(v2_document)

    for document in (v1_document, v2_document):
        without_version = {k: v for k, v in document.items() if k != "schema_version"}
        assert not v1_validator.is_valid(without_version)
        assert not v2_validator.is_valid(without_version)
    mismatched_v1 = {**v1_document, "schema_version": "assay-execution-plan/0.2.0"}
    mismatched_v2 = {**v2_document, "schema_version": "assay-execution-plan/0.1.0"}
    assert not v1_validator.is_valid(mismatched_v1)
    assert not v2_validator.is_valid(mismatched_v2)


def test_root_plan_schema_validates_each_pinned_version_through_its_registry(
    tmp_path: Path,
) -> None:
    """A validator loading only the root document must resolve its oneOf refs offline."""
    store = ObjectStore(tmp_path)
    fixture = execution_fixture(store)
    root = Path(__file__).resolve().parents[1] / "schemas"
    union = Draft202012Validator(
        json.loads((root / "assay-execution-plan.schema.json").read_text()),
        registry=plan_schema_registry(),
    )

    v1_document = json.loads(fixture.plan_bytes)
    union.validate(v1_document)

    study = fixture.snapshot
    runtime = RuntimeProfile(
        id="pier", version="1.0.0", configuration_ref=str(store.publish_json({"x": 1}))
    )
    v2_plan = compile_plan_v2(
        study,
        snapshot_ref=str(store.publish_json(study.model_dump(mode="json"))),
        worker_repeats=1,
        runtime=runtime,
    )
    union.validate(v2_plan.model_dump(mode="json"))

    assert not union.is_valid({k: v for k, v in v1_document.items() if k != "schema_version"})


def test_normative_contract_hashes_match_pinned_conformance_package() -> None:
    for field, name in [
        ("task_schema_ref", "paa-task"),
        ("evidence_schema_ref", "paa-evidence-record"),
        ("operating_schema_ref", "paa-operating-record"),
    ]:
        assert (
            digest_bytes(canonical_json(paa_contracts.load_schema(name)))
            == SUPPORTED_CONTRACTS[field]
        )


def test_snapshot_rejects_unknown_evaluator_and_permissive_contract(tmp_path: Path) -> None:
    fixture = execution_fixture(ObjectStore(tmp_path))
    snapshot = fixture.snapshot.model_dump(mode="json")
    snapshot["evaluators"][0]["identity"]["version"] = "undeclared"
    with pytest.raises(ValueError, match="not declared"):
        verify_snapshot(fixture.store, StudySnapshot.model_validate(snapshot))
    snapshot = fixture.snapshot.model_dump(mode="json")
    snapshot["task_schema_ref"] = str(
        fixture.store.publish_json({"$id": "https://paa.dev/paa-task.schema.json"})
    )
    with pytest.raises(ValueError, match="unsupported"):
        verify_snapshot(fixture.store, StudySnapshot.model_validate(snapshot))


async def _run(tmp_path: Path) -> tuple[ObjectStore, RunSucceeded]:
    store = ObjectStore(tmp_path)
    fixture = execution_fixture(store, subject_ids=("ok",), worker_repeats=1, evaluator_repeats=1)
    result = await execute_plan(**fixture.arguments)
    assert isinstance(result, RunSucceeded), result
    assert verify_manifest(store, str(result.manifest_ref)) == ()
    return store, result


async def test_forged_record_cannot_pass_integrity_only_verification(tmp_path: Path) -> None:
    store, result = await _run(tmp_path)
    manifest = result.manifest.model_dump(mode="json")
    key = next(iter(manifest["execution_records"]))
    manifest["execution_records"][key] = str(store.publish_json({"bogus": True}))
    ref = str(store.publish_json(manifest))
    assert any(item.code == "execution_record" for item in verify_manifest(store, ref))


@pytest.mark.parametrize("kind", ["run", "coordinate", "verdict", "task", "sources", "timestamp"])
async def test_evidence_tampering_rejected(tmp_path: Path, kind: str) -> None:
    store, result = await _run(tmp_path)
    manifest = result.manifest.model_dump(mode="json")
    key, original = next(iter(manifest["evaluation_records"].items()))
    record = json.loads(store.read_bytes(original))
    if kind == "run":
        record["payload"]["run_id"] = "other-run"
    elif kind == "coordinate":
        record["payload"]["worker_repeat"] = 42
    elif kind == "verdict":
        record["verdict"]["value"] = 2.0
    elif kind == "task":
        record["task"] = "unknown_task"
    elif kind == "sources":
        record["source_references"] = [result.manifest.plan_ref]
    else:
        record["timestamps"]["completed_at"] = "1900-01-01T00:00:00Z"
    manifest["evaluation_records"][key] = str(store.publish_json(record))
    ref = str(store.publish_json(manifest))
    assert any(item.code == "evaluation_record" for item in verify_manifest(store, ref))


async def test_cross_run_record_substitution_rejected(tmp_path: Path) -> None:
    store, result = await _run(tmp_path)
    fixture = execution_fixture(store, subject_ids=("ok",), worker_repeats=1, evaluator_repeats=1)
    second = await execute_plan(**fixture.arguments)
    assert isinstance(second, RunSucceeded)
    manifest = second.manifest.model_dump(mode="json")
    key = next(iter(manifest["execution_records"]))
    manifest["execution_records"][key] = result.manifest.execution_records[key]
    assert verify_manifest(store, str(store.publish_json(manifest)))


async def test_missing_transitive_artifact_and_unmanifested_bundle_insert_rejected(
    tmp_path: Path,
) -> None:
    store, result = await _run(tmp_path / "source")
    exported = export_bundle(store, str(result.manifest_ref), tmp_path / "export")
    assert verify_bundle(exported, str(result.manifest_ref)) == ()
    exported.publish_json({"unmanifested": "record"})
    assert any(
        item.code == "bundle_closure" for item in verify_bundle(exported, str(result.manifest_ref))
    )
    plan = ExecutionPlan.model_validate_json(store.read_bytes(result.manifest.plan_ref))
    snapshot = StudySnapshot.model_validate_json(store.read_bytes(plan.snapshot_ref))
    store._path(snapshot.evaluators[0].basis_ref).unlink()
    assert verify_manifest(store, str(result.manifest_ref))


async def test_operating_omission_and_missing_plan_coordinate_rejected(tmp_path: Path) -> None:
    store, result = await _run(tmp_path)
    manifest: dict[str, Any] = result.manifest.model_dump(mode="json")
    manifest["operating_records"] = {}
    assert any(
        item.code == "operating_coordinates"
        for item in verify_manifest(store, str(store.publish_json(manifest)))
    )
    manifest = result.manifest.model_dump(mode="json")
    manifest["evaluation_records"].pop(next(iter(manifest["evaluation_records"])))
    assert any(
        item.code == "missing_coordinates"
        for item in verify_manifest(store, str(store.publish_json(manifest)))
    )


async def test_failed_worker_evaluation_skip_cannot_be_omitted(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    fixture = execution_fixture(store, subject_ids=("fails",))
    result = await execute_plan(**fixture.arguments)
    assert isinstance(result, RunSucceeded)
    manifest = result.manifest.model_dump(mode="json")
    skipped = next(
        key for key, ref in manifest["evaluation_records"].items()
        if json.loads(store.read_bytes(ref)).get("error_type") == "ExecutionUnavailable"
    )
    # Every worker fails in this fixture, so every evaluation is already
    # unavailable and genuinely missing regardless of whether its terminal
    # skip record is even present. The real adversarial case this guards is
    # a manifest that omits the skip record *and* claims completeness by
    # scrubbing that coordinate from missing_coordinates too.
    del manifest["evaluation_records"][skipped]
    manifest["missing_coordinates"] = [
        coordinate for coordinate in manifest["missing_coordinates"] if coordinate != skipped
    ]
    if not manifest["missing_coordinates"]:
        manifest["status"] = "complete"
    assert any(
        item.code == "missing_coordinates"
        for item in verify_manifest(store, str(store.publish_json(manifest)))
    )


@pytest.mark.parametrize("kind", ["worker", "provenance", "components", "coverage"])
async def test_operating_attribution_substitution_rejected(tmp_path: Path, kind: str) -> None:
    store, result = await _run(tmp_path)
    manifest = result.manifest.model_dump(mode="json")
    key, ref = next(iter(manifest["operating_records"].items()))
    record = json.loads(store.read_bytes(ref))
    if kind == "worker":
        record["worker"]["id"] = "different-worker"
    elif kind == "components":
        record["components"] = []
    else:
        for index, source in enumerate(record["source_references"]):
            detail = json.loads(store.read_bytes(source))
            if isinstance(detail, dict) and "coverage" in detail:
                if kind == "coverage":
                    assert record["price"] is None
                    detail["coverage"] = "measured"
                else:
                    detail["run_id"] = "different-run"
                record["source_references"][index] = str(store.publish_json(detail))
                break
    manifest["operating_records"][key] = str(store.publish_json(record))
    assert any(
        item.code == "operating_record"
        for item in verify_manifest(store, str(store.publish_json(manifest)))
    )


def test_plan_estimates_are_per_arm_and_derived(tmp_path: Path) -> None:
    fixture = execution_fixture(ObjectStore(tmp_path))
    estimates = {
        "reference": PriceEstimate(amount=1.25, currency="USD", coverage="estimated"),
        "candidate": PriceEstimate(amount=None, coverage="unavailable"),
    }
    plan = compile_plan(
        fixture.snapshot,
        snapshot_ref=digest_bytes(canonical_json(fixture.snapshot.model_dump(mode="json"))),
        worker_repeats=1,
        jig_revision="test",
        arm_cost_estimates=estimates,
    )
    assert plan.cost_estimate == PriceEstimate(amount=1.25, currency="USD", coverage="mixed")
    validate_plan_snapshot(plan, fixture.snapshot)
    with pytest.raises(ValueError, match="derived"):
        compile_plan(
            fixture.snapshot,
            snapshot_ref=plan.snapshot_ref,
            worker_repeats=1,
            jig_revision="test",
            cost_estimate=PriceEstimate(amount=99, currency="USD", coverage="estimated"),
        )


@pytest.mark.parametrize(
    "metric,aggregation,mapping",
    [
        ("classification", "mean", None),
        ("scalar", "majority", None),
        ("ordinal", "mean", None),
        ("scalar", "mean", {"no": 0, "yes": 1}),
        ("classification", "majority", {"no": 0, "yes": 1}),
        ("ordinal", "majority", {"no": 0, "yes": 1}),
    ],
)
def test_report_rejects_incompatible_aggregation_mapping(
    metric: str, aggregation: str, mapping: dict[str, int] | None
) -> None:
    with pytest.raises(ValidationError):
        ReportConfig.model_validate(
            {
                "manifest_refs": ["sha256:" + "0" * 64],
                "record_refs": [],
                "reference_arm": "reference",
                "candidates": ["candidate"],
                "evaluator_id": "quality",
                "metric": metric,
                "scalar_direction": "higher_is_better" if metric == "scalar" or mapping else None,
                "evaluator_repeat_aggregation": aggregation,
                "worker_repeat_aggregation": aggregation,
                "ordinal_mapping": mapping,
                "categories": ["no", "yes"],
                "positive_label": "yes",
                "statistical_profile": {"seed": 1, "bootstrap_samples": 100},
                "engine_version": "0.1.0",
            }
        )
