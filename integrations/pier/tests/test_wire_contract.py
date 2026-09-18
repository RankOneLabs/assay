"""The bridge's half of the cross-project Pier wire contract.

This project deliberately has no import edge back onto ``assay``, so
``container.package_digest`` and ``pier_adapter.sanitized_trial_name`` are
local reimplementations of ``assay.pier_packaging.manifest_digest`` and
``assay.pier_protocol.trial_name_for``. The shared fixture in the root
project is the only thing that keeps the two copies honest; reading it from
here is a test-time file read, not a package dependency.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from assay_pier_bridge.container import package_digest
from assay_pier_bridge.pier_adapter import sanitized_trial_name

FIXTURE = (
    Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "pier_wire_contract.json"
)


def _fixture() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_the_shared_fixture_is_reachable_from_this_project() -> None:
    """A moved or renamed fixture must fail loudly here rather than silently
    skipping every case below and leaving the two implementations unpinned."""
    assert FIXTURE.is_file(), f"shared wire-contract fixture is missing: {FIXTURE}"


@pytest.mark.parametrize("case", _fixture()["package_digests"], ids=lambda case: case["name"])
def test_package_digest_matches_assays_computation(case: dict[str, Any]) -> None:
    assert package_digest(case["package"]) == case["digest"]


def test_package_digest_is_independent_of_mapping_order() -> None:
    for case in _fixture()["package_digests"]:
        reversed_order = dict(reversed(list(case["package"].items())))
        assert package_digest(reversed_order) == case["digest"]


@pytest.mark.parametrize("case", _fixture()["trial_names"], ids=lambda case: case["cell_id"])
def test_sanitized_trial_name_matches_assays_computation(case: dict[str, Any]) -> None:
    assert sanitized_trial_name(case["cell_id"]) == case["trial_name"]


def test_sanitized_trial_name_is_injective_across_hyphenated_identifiers() -> None:
    """The exact pair the naive ``replace(":", "-")`` mapping collided on."""
    assert sanitized_trial_name("a-b:c:w0") != sanitized_trial_name("a:b-c:w0")


def test_sanitized_trial_name_rejects_a_cell_id_that_is_not_three_components() -> None:
    with pytest.raises(ValueError, match="cell id"):
        sanitized_trial_name("subject-arm-w0")
