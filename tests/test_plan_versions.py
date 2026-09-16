"""Dual-version assay-execution-plan/0.1.0 and /0.2.0 contract behavior."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from test_execution import execution_fixture

from assay.canonical import canonical_json, digest_bytes
from assay.models import (
    ExecutionPlan,
    ExecutionPlanV2,
    RuntimeProfile,
    parse_execution_plan,
    plan_runtime_identity,
)
from assay.planning import (
    AuthorizationError,
    authorize,
    compile_plan,
    compile_plan_v2,
    validate_plan_snapshot,
)
from assay.references import reference_closure
from assay.store import ObjectStore


def _runtime(store: ObjectStore, *, id: str = "pier", version: str = "1.0.0") -> RuntimeProfile:
    configuration_ref = str(store.publish_json({"backend": id, "version": version}))
    return RuntimeProfile(id=id, version=version, configuration_ref=configuration_ref)


def test_parse_execution_plan_selects_the_matching_model_before_validating(
    tmp_path: Path,
) -> None:
    store = ObjectStore(tmp_path)
    fixture = execution_fixture(store)
    v1_plan = json.loads(fixture.plan_bytes)
    assert isinstance(parse_execution_plan(v1_plan), ExecutionPlan)

    v2_common = {k: v for k, v in v1_plan.items() if k not in ("schema_version", "jig_revision")}
    v2_plan = {
        **v2_common,
        "schema_version": "assay-execution-plan/0.2.0",
        "runtime": _runtime(store).model_dump(mode="json"),
    }
    assert isinstance(parse_execution_plan(v2_plan), ExecutionPlanV2)


@pytest.mark.parametrize(
    "schema_version", ["assay-execution-plan/0.3.0", "assay-execution-plan/0.1", "", "garbage"]
)
def test_parse_execution_plan_rejects_unknown_versions(schema_version: str) -> None:
    with pytest.raises(ValidationError):
        parse_execution_plan({"schema_version": schema_version})


def test_v1_bytes_are_never_normalized_through_the_v2_model(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    fixture = execution_fixture(store)
    v1_plan = json.loads(fixture.plan_bytes)
    with pytest.raises(ValidationError):
        ExecutionPlanV2.model_validate(v1_plan)


def test_v2_plan_rejects_legacy_and_generic_field_mixing(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    fixture = execution_fixture(store)
    v1_plan = json.loads(fixture.plan_bytes)
    v2_common = {k: v for k, v in v1_plan.items() if k != "schema_version"}

    # A 0.2.0 document cannot carry the legacy jig_revision field alongside runtime.
    with pytest.raises(ValidationError):
        ExecutionPlanV2.model_validate(
            {
                **v2_common,
                "schema_version": "assay-execution-plan/0.2.0",
                "runtime": _runtime(store).model_dump(mode="json"),
            }
        )

    # A 0.1.0 document cannot carry a generic runtime profile.
    with pytest.raises(ValidationError):
        ExecutionPlan.model_validate(
            {**v1_plan, "runtime": _runtime(store).model_dump(mode="json")}
        )


def test_runtime_profile_requires_a_content_addressed_configuration(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    with pytest.raises(ValidationError):
        RuntimeProfile(id="pier", version="1.0.0", configuration_ref="not-a-hash")
    profile = _runtime(store)
    assert profile.configuration_ref.startswith("sha256:")


def test_compile_plan_v2_binds_runtime_and_round_trips_through_authorize(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    study = execution_fixture(store, subject_ids=("s0", "s1")).snapshot
    snapshot_ref = str(store.publish_json(study.model_dump(mode="json")))
    runtime = _runtime(store)
    plan = compile_plan_v2(
        study,
        snapshot_ref=snapshot_ref,
        worker_repeats=2,
        runtime=runtime,
    )
    assert plan.schema_version == "assay-execution-plan/0.2.0"
    assert plan.runtime == runtime
    validate_plan_snapshot(plan, study)

    data = canonical_json(plan.model_dump(mode="json"))
    authorized = authorize(data, digest_bytes(data))
    assert authorized == plan
    with pytest.raises(AuthorizationError):
        authorize(data, "sha256:" + "0" * 64)


def test_validate_plan_snapshot_rejects_drift_for_v2(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    study = execution_fixture(store, subject_ids=("s0", "s1")).snapshot
    snapshot_ref = str(store.publish_json(study.model_dump(mode="json")))
    plan = compile_plan_v2(
        study, snapshot_ref=snapshot_ref, worker_repeats=2, runtime=_runtime(store)
    )
    with pytest.raises(ValueError, match="compilation"):
        validate_plan_snapshot(plan.model_copy(update={"cells": ()}), study)


def test_reference_closure_requires_the_runtime_configuration_object(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    study = execution_fixture(store, subject_ids=("s0", "s1")).snapshot
    snapshot_ref = str(store.publish_json(study.model_dump(mode="json")))
    runtime = _runtime(store)
    plan = compile_plan_v2(
        study, snapshot_ref=snapshot_ref, worker_repeats=2, runtime=runtime
    )
    for declaration in (*study.arms, *study.evaluators):
        store.publish_json(declaration.model_dump(mode="json"))
    store.publish_json([arm.conditions for arm in sorted(study.arms, key=lambda item: item.id)])
    plan_ref = str(store.publish_json(plan.model_dump(mode="json")))

    closure = reference_closure(store, (plan_ref,))
    assert runtime.configuration_ref in closure

    store._path(runtime.configuration_ref).unlink()
    with pytest.raises(FileNotFoundError):
        reference_closure(store, (plan_ref,))


def test_plan_runtime_identity_projects_legacy_and_generic_plans(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    fixture = execution_fixture(store)
    v1_plan = ExecutionPlan.model_validate_json(fixture.plan_bytes)
    assert plan_runtime_identity(v1_plan) == (v1_plan.jig_revision, "jig", v1_plan.jig_revision)

    study = fixture.snapshot
    snapshot_ref = str(store.publish_json(study.model_dump(mode="json")))
    runtime = _runtime(store, id="pier", version="2.0.0")
    v2_plan = compile_plan_v2(
        study, snapshot_ref=snapshot_ref, worker_repeats=2, runtime=runtime
    )
    assert plan_runtime_identity(v2_plan) == (None, "pier", "2.0.0")
    assert plan_runtime_identity(None) == (None, None, None)


def test_compile_plan_still_produces_the_legacy_0_1_0_shape(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    study = execution_fixture(store, subject_ids=("s0", "s1")).snapshot
    plan = compile_plan(
        study,
        snapshot_ref=str(store.publish_json(study.model_dump(mode="json"))),
        worker_repeats=1,
        jig_revision="abc123",
    )
    assert plan.schema_version == "assay-execution-plan/0.1.0"
    assert plan.jig_revision == "abc123"
