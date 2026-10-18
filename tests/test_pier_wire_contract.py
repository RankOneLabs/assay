"""Assay's half of the cross-project Pier wire contract.

``integrations/pier`` reimplements all of this locally, because that project
has no import edge back onto ``assay``. A reimplementation that merely
*looks* equivalent is not enough: ``DockerTrialHandle`` rejects any request
whose ``package_digest`` differs from its own computation, two cells whose
trial names collide share one directory on disk, and an artifact budget
enforced differently on each side leaves a window where one project accepts
bytes the other refuses. The shared fixture pins the expected behaviour so
neither side can drift silently -- ``integrations/pier/tests/
test_wire_contract.py`` asserts the same file.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, get_args, get_origin

import pytest

from assay.adapters.pier import _publish_available_artifacts
from assay.models import CellCoordinate
from assay.pier_packaging import manifest_digest
from assay.pier_protocol import (
    MANIFEST_PATH,
    MAX_AGGREGATE_ARTIFACT_BYTES,
    MAX_ARTIFACT_BYTES,
    MAX_ARTIFACT_COUNT,
    CandidateCause,
    CandidateFailure,
    CandidateSubmission,
    EffectiveEnforcement,
    InfrastructureCause,
    InfrastructureFailure,
    ModelRoute,
    NetworkPolicy,
    TrialLimits,
    TrialRequest,
    trial_name_for,
)
from assay.store import ObjectStore

FIXTURE = Path(__file__).parent / "fixtures" / "pier_wire_contract.json"


def _fixture() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _field_contract(model: type[Any]) -> dict[str, tuple[Any, ...]]:
    def type_shape(annotation: Any) -> Any:
        origin = get_origin(annotation)
        if origin is None:
            return getattr(annotation, "__name__", repr(annotation))
        return (str(origin), tuple(type_shape(value) if isinstance(value, type) or
                                    get_origin(value) is not None else value
                                    for value in get_args(annotation)))

    return {
        name: (
            type_shape(field.annotation),
            tuple(sorted(
                (key, value)
                for rule in field.metadata
                for key in ("gt", "ge", "lt", "le", "pattern", "min_length",
                            "max_length", "strict", "allow_inf_nan")
                if (value := getattr(rule, key, None)) is not None
            )),
            field.is_required(),
            field.default if not field.is_required() else None,
        )
        for name, field in model.model_fields.items()
    }


def test_core_and_bridge_field_types_constraints_and_routes_agree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "integrations/pier/src"))
    from assay_pier_bridge import protocol as bridge

    # Intended differences: bridge ClosedModel is strict; core WireModel uses
    # allow_inf_nan=False and freeze_payloads. Bridge CellId is Annotated,
    # while core cell_id has an inline Field pattern. These base-model and
    # declaration differences do not change the field's wire constraints.
    # Validators are checked only for the route and local-posture behaviors
    # asserted below; unrelated future validators need their own behavior tests.
    for core_model, bridge_model in (
        (TrialRequest, bridge.TrialRequest),
        (TrialLimits, bridge.TrialLimits),
        (EffectiveEnforcement, bridge.EffectiveEnforcement),
        (ModelRoute, bridge.ModelRoute),
    ):
        assert _field_contract(core_model) == _field_contract(bridge_model)

    paid = {"endpoint": "https://openrouter.ai/api/v1", "model": "anthropic/claude-3-haiku",
            "provider": "amazon-bedrock"}
    local = {"endpoint": "http://willie:8900", "model": "qwen-coder-32b",
             "provider": "smithers-local"}
    for route in (paid, local):
        assert ModelRoute.model_validate(route).model_dump() == route
        assert bridge.ModelRoute.model_validate(route).model_dump() == route
    for route in ({**paid, "model": local["model"]}, {**local, "provider": paid["provider"]}):
        for model in (ModelRoute, bridge.ModelRoute):
            with pytest.raises(ValueError):
                model.model_validate(route)

    sample = {**_fixture()["trial_envelope"]["sample_request"],
              "egress_host": None, "egress_port": None,
              "network_policy": "egress-openrouter-only"}
    for model in (TrialRequest, bridge.TrialRequest):
        with pytest.raises(ValueError, match="toolchain posture"):
            model.model_validate({**sample, "model_route": local})
        assert model.model_validate({**sample, "model_route": local,
                                     "network_policy": "toolchain-only"}).model_route.provider == (
                                         "smithers-local"
                                     )


def test_trial_envelope_revision_matches_the_shared_fixture() -> None:
    envelope = _fixture()["trial_envelope"]
    assert set(get_args(NetworkPolicy)) == set(envelope["network_policies"])
    request = TrialRequest.model_validate(envelope["sample_request"])
    assert request.model_dump() == envelope["sample_request"]
    assert request.schema_version == envelope["schema_version"]
    assert set(get_args(CandidateCause)) == set(envelope["candidate_causes"])
    assert set(get_args(InfrastructureCause)) == set(envelope["infrastructure_causes"])
    assert {
        kind
        for outcome in (CandidateSubmission, CandidateFailure, InfrastructureFailure)
        for kind in get_args(outcome.model_fields["kind"].annotation)
    } == set(envelope["result_outcomes"])


@pytest.mark.parametrize(
    ("host", "allowed"),
    [
        ("10.0.0.1", True),
        ("172.16.0.1", True),
        ("192.168.1.10", True),
        ("169.254.169.254", False),
        ("127.0.0.1", False),
        ("100.64.0.1", False),
    ],
)
def test_lan_egress_host_requires_rfc1918_address(host: str, allowed: bool) -> None:
    request = {
        **_fixture()["trial_envelope"]["sample_request"],
        "egress_host": host,
    }
    if allowed:
        assert TrialRequest.model_validate(request).egress_host == host
    else:
        with pytest.raises(ValueError, match="LAN IPv4 address"):
            TrialRequest.model_validate(request)


def _coordinate(case: dict[str, Any]) -> CellCoordinate:
    return CellCoordinate(
        subject_id=case["subject_id"],
        arm_id=case["arm_id"],
        worker_repeat=case["worker_repeat"],
        realization_ref="sha256:" + "0" * 64,
    )


@pytest.mark.parametrize("case", _fixture()["package_digests"], ids=lambda case: case["name"])
def test_package_digest_matches_the_shared_fixture(case: dict[str, Any]) -> None:
    assert manifest_digest(case["package"]) == case["digest"]


def test_package_digest_is_independent_of_mapping_order() -> None:
    """The bridge receives a materialized package with no memory of how it
    was built, so the digest must not depend on the caller's insertion order."""
    for case in _fixture()["package_digests"]:
        reversed_order = dict(reversed(list(case["package"].items())))
        assert manifest_digest(reversed_order) == case["digest"]


@pytest.mark.parametrize("case", _fixture()["trial_names"], ids=lambda case: case["cell_id"])
def test_trial_name_matches_the_shared_fixture(case: dict[str, Any]) -> None:
    coordinate = _coordinate(case)
    assert coordinate.id == case["cell_id"]
    assert trial_name_for(coordinate) == case["trial_name"]


def test_fixture_covers_the_hyphen_collision_both_ways() -> None:
    """The fixture is only worth asserting if it contains the case that broke:
    two distinct cells whose naive ``replace(":", "-")`` encodings collide."""
    by_cell = {case["cell_id"]: case["trial_name"] for case in _fixture()["trial_names"]}
    assert by_cell["a-b:c:w0"] != by_cell["a:b-c:w0"]
    assert "a-b:c:w0".replace(":", "-") == "a:b-c:w0".replace(":", "-")


def test_fixture_trial_names_are_distinct() -> None:
    names = [case["trial_name"] for case in _fixture()["trial_names"]]
    assert len(set(names)) == len(names)


def test_artifact_ceilings_match_the_shared_fixture() -> None:
    """The bridge pins the same limits from the same file. Changing a
    ceiling on one side alone fails there, where the other copy lives."""
    budget = _fixture()["artifact_budget"]
    assert budget["max_artifact_bytes"] == MAX_ARTIFACT_BYTES
    assert budget["max_aggregate_artifact_bytes"] == MAX_AGGREGATE_ARTIFACT_BYTES
    assert budget["max_artifact_count"] == MAX_ARTIFACT_COUNT
    assert budget["manifest_path"] == MANIFEST_PATH


@pytest.mark.parametrize(
    "case", _fixture()["artifact_budget"]["cases"], ids=lambda case: case["name"]
)
def test_publication_budget_matches_the_shared_fixture(
    case: dict[str, Any], tmp_path: Path
) -> None:
    """Assay's half of the budget contract is which artifacts reach the store.

    A set the bridge refuses to carry and a set this side refuses to publish
    must be the same set. The case that forced this to be written down is
    ``maximal_manifest_at_the_aggregate_ceiling``: a manifest may declare up
    to ``MAX_AGGREGATE_ARTIFACT_BYTES``, so charging ``manifest.json`` to that
    same budget on either side makes an honest bridge at the ceiling
    impossible -- unpublishable here, and unreturnable there.
    """
    artifacts = {path: b"\x00" * size for path, size in case["artifacts"].items()}
    refs = _publish_available_artifacts(
        ObjectStore(tmp_path / ".assay"), artifacts, priority=frozenset(artifacts)
    )
    assert (set(refs) == set(artifacts)) is case["within_budget"]


def test_the_fixture_budget_cases_cover_both_verdicts() -> None:
    """A fixture that only carried accepted cases would pass against a side
    that had no ceilings at all."""
    verdicts = {case["within_budget"] for case in _fixture()["artifact_budget"]["cases"]}
    assert verdicts == {True, False}


def test_publication_refuses_an_unbounded_number_of_empty_artifacts(tmp_path: Path) -> None:
    artifacts = {f"empty-{index}": b"" for index in range(MAX_ARTIFACT_COUNT + 1)}
    refs = _publish_available_artifacts(ObjectStore(tmp_path / ".assay"), artifacts)
    assert refs == {}


def test_publication_does_not_charge_the_manifest_to_the_artifact_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("assay.adapters.pier.MAX_ARTIFACT_COUNT", 2)
    artifacts = {"a": b"", "b": b"", MANIFEST_PATH: b"{}"}
    refs = _publish_available_artifacts(ObjectStore(tmp_path / ".assay"), artifacts)
    assert refs.keys() == artifacts.keys()
