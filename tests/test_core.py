from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from test_execution import execution_fixture

from assay.canonical import CanonicalizationError, canonical_json, digest_bytes
from assay.models import Exclusion, PriceEstimate
from assay.planning import AuthorizationError, authorize, compile_plan
from assay.schema_export import check_schemas, schema_documents
from assay.store import ObjectCollisionError, ObjectStore


def test_canonical_json_is_stable_and_strict() -> None:
    assert canonical_json({"z": "café", "a": [2, 1]}) == b'{"a":[2,1],"z":"caf\xc3\xa9"}'
    assert canonical_json({"a": [2, 1], "z": "café"}) == canonical_json({"z": "café", "a": [2, 1]})
    for value in [float("nan"), float("inf"), {1: "bad"}, {"set"}]:
        with pytest.raises(CanonicalizationError):
            canonical_json(value)


def test_store_is_idempotent_and_detects_simulated_collision(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    ref = store.publish_json({"a": 1})
    assert store.publish_json({"a": 1}) == ref
    store._path(ref).write_bytes(b"other")
    with pytest.raises(ObjectCollisionError):
        store.publish_json({"a": 1})


def test_plan_is_deterministic_complete_and_authorized(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    study = execution_fixture(store, subject_ids=("s0", "s1")).snapshot
    kwargs = dict(
        snapshot_ref=str(store.publish_json(study.model_dump(mode="json"))),
        worker_repeats=2,
        jig_revision="test",
    )
    first = compile_plan(study, **kwargs)
    reordered = study.model_copy(
        update={"subjects": tuple(reversed(study.subjects)), "arms": tuple(reversed(study.arms))}
    )
    second = compile_plan(reordered, **kwargs)
    assert first == second
    assert len(first.cells) == 8 and len(first.evaluations) == 16
    data = canonical_json(first.model_dump(mode="json"))
    assert authorize(data, digest_bytes(data)) == first
    with pytest.raises(AuthorizationError):
        authorize(data, "sha256:" + "0" * 64)


def test_exclusion_removes_only_declared_pair(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    study = execution_fixture(store, subject_ids=("s0", "s1")).snapshot
    plan = compile_plan(
        study,
        snapshot_ref=str(store.publish_json(study.model_dump(mode="json"))),
        worker_repeats=2,
        jig_revision="test",
        exclusions=(
            Exclusion(
                subject_id="s1", arm_id="candidate", classification="fixture", reason="declared"
            ),
        ),
        arm_cost_estimates={
            "candidate": PriceEstimate(amount=1.25, currency="USD", coverage="estimated"),
            "reference": PriceEstimate(amount=None, coverage="unavailable"),
        },
    )
    assert len(plan.cells) == 6
    assert all((c.subject_id, c.arm_id) != ("s1", "candidate") for c in plan.cells)


def test_schema_files_are_valid_and_closed() -> None:
    directory = Path(__file__).resolve().parents[1] / "schemas"
    check_schemas(directory)
    assert len(schema_documents()) == 9
    for name in schema_documents():
        path = directory / name
        schema = json.loads(path.read_text())
        Draft202012Validator.check_schema(schema)
        if name == "assay-execution-plan.schema.json":
            # The unversioned name is a discriminator-selected oneOf over the
            # pinned 0.1.0/0.2.0 documents, not a closed object schema itself.
            assert schema["oneOf"]
        else:
            assert schema["additionalProperties"] is False
