"""Assay's half of the cross-project Pier wire contract.

``integrations/pier`` reimplements both of these functions locally, because
that project has no import edge back onto ``assay``. A reimplementation that
merely *looks* equivalent is not enough: ``DockerTrialHandle`` rejects any
request whose ``package_digest`` differs from its own computation, and two
cells whose trial names collide share one directory on disk. The shared
fixture pins the expected outputs so neither side can drift silently --
``integrations/pier/tests/test_wire_contract.py`` asserts the same file.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from assay.models import CellCoordinate
from assay.pier_packaging import manifest_digest
from assay.pier_protocol import trial_name_for

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
