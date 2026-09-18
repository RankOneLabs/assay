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
from typing import Any

import pytest

from assay.adapters.pier import _publish_available_artifacts
from assay.models import CellCoordinate
from assay.pier_packaging import manifest_digest
from assay.pier_protocol import (
    MANIFEST_PATH,
    MAX_AGGREGATE_ARTIFACT_BYTES,
    MAX_ARTIFACT_BYTES,
    MAX_ARTIFACT_COUNT,
    trial_name_for,
)
from assay.store import ObjectStore

FIXTURE = Path(__file__).parent / "fixtures" / "pier_wire_contract.json"


def _fixture() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


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
