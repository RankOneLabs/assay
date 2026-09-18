"""The bridge's half of the cross-project Pier wire contract.

This project deliberately has no import edge back onto ``assay``, so
``container.package_digest``, ``pier_adapter.sanitized_trial_name`` and the
artifact byte ceilings on ``TrialResult`` are local reimplementations of
``assay.pier_packaging.manifest_digest``, ``assay.pier_protocol.
trial_name_for`` and ``assay``'s own publication budget. The shared fixture
in the root project is the only thing that keeps the two copies honest;
reading it from here is a test-time file read, not a package dependency.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from assay_pier_bridge.container import package_digest
from assay_pier_bridge.pier_adapter import sanitized_trial_name
from assay_pier_bridge.protocol import (
    MANIFEST_PATH,
    MAX_AGGREGATE_ARTIFACT_BYTES,
    MAX_ARTIFACT_BYTES,
    EffectiveEnforcement,
    TrialResult,
)
from pydantic import ValidationError

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


def _effective() -> EffectiveEnforcement:
    return EffectiveEnforcement(
        uid=1000,
        gid=1000,
        workspace_read_only=True,
        submission_mount="/submission",
        scratch_mount="/scratch",
        network_policy="none",
        cpu_limit=1.0,
        memory_limit_mb=512,
        pids_limit=64,
        storage_limit_mb=64,
        containers_remaining=0,
        child_processes_remaining=0,
        teardown_completed=True,
    )


def test_artifact_ceilings_match_the_shared_fixture() -> None:
    """``assay`` pins the same three values from the same file. Changing a
    ceiling on one side alone fails there, where the other copy lives."""
    budget = _fixture()["artifact_budget"]
    assert budget["max_artifact_bytes"] == MAX_ARTIFACT_BYTES
    assert budget["max_aggregate_artifact_bytes"] == MAX_AGGREGATE_ARTIFACT_BYTES
    assert budget["manifest_path"] == MANIFEST_PATH


@pytest.mark.parametrize(
    "case", _fixture()["artifact_budget"]["cases"], ids=lambda case: case["name"]
)
def test_artifact_budget_matches_the_shared_fixture(case: dict[str, Any]) -> None:
    """This project's half of the budget contract is what a trial may carry.

    A set ``assay`` will publish and a set this side will return must be the
    same set. ``maximal_manifest_at_the_aggregate_ceiling`` is the case that
    forced it to be written down: a manifest may declare up to
    ``MAX_AGGREGATE_ARTIFACT_BYTES``, so charging ``manifest.json`` to that
    same budget here would fail an honest trial at the ceiling on the few
    hundred bytes describing what it already carried successfully.
    """
    artifacts = {path: b"\x00" * size for path, size in case["artifacts"].items()}
    fields: dict[str, Any] = {
        "cell_id": "s1:a1:w0",
        "status": "succeeded",
        "submission_ref": "sha256:" + "0" * 64,
        "effective": _effective(),
        "artifacts": artifacts,
    }
    if case["within_budget"]:
        assert TrialResult(**fields).artifacts.keys() == artifacts.keys()
    else:
        with pytest.raises(ValidationError, match="byte limit"):
            TrialResult(**fields)
