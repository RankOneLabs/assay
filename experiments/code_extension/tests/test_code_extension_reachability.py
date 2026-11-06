"""The reachability split follows retained output, the journal and the patch."""

from __future__ import annotations

from typing import Any

import pytest
from code_extension import authoring
from code_extension.fixtures import load_scenario
from code_extension.reachability import (
    adds_stage_code,
    claimed_cells,
    feature_failure,
    request_counts,
    settled_cells,
    stage_type,
)

TASKS = ("stage-status-report", "stage-collect-artifacts")
PATCH = """\
--- a/src/stages/index.ts
+++ b/src/stages/index.ts
@@ -1 +1,2 @@
 export const stages = [];
+export const added = "status_report";
"""
TEST_ONLY_PATCH = PATCH.replace("src/stages/index.ts", "tests/agent/status.test.ts")


@pytest.mark.parametrize(
    ("output", "group_failed", "expected"),
    [
        ("(pass) reachability: found\n(pass) semantics: ok [1.20ms]\n", False, None),
        ("(pass) reachability: found\n(fail) semantics: rejects [0.50ms]\n", True, "semantic"),
        ("(fail) reachability: found [1.00ms]\n(fail) semantics: rejects\n", True, "reachability"),
        ("(fail) semantics: rejects [0.50ms]\n", True, "unattributed"),
        ("(fail) something else [1.00ms]\n", True, "unattributed"),
        ("error: module threw on load\n", True, "unattributed"),
        ("", False, None),
    ],
)
def test_failed_titles_and_group_status_decide_the_split(
    output: str, group_failed: bool, expected: str | None,
) -> None:
    assert feature_failure(output, group_failed=group_failed) == expected


def test_stage_code_means_an_added_line_outside_the_test_tree() -> None:
    assert adds_stage_code(PATCH, "status_report")
    assert adds_stage_code(PATCH.replace("status_report", "statusReportCompiler"), "status_report")
    assert adds_stage_code(PATCH.replace("status_report", "./status-report"), "status_report")
    assert not adds_stage_code(PATCH, "collect_artifacts")
    assert not adds_stage_code(TEST_ONLY_PATCH, "status_report")
    assert not adds_stage_code("", "status_report")


@pytest.mark.parametrize("name", TASKS)
@pytest.mark.parametrize("arm", authoring.SHAPE_ARMS)
def test_an_unregistered_stage_still_counts_as_written(name: str, arm: str) -> None:
    """The qualified missed-integration patch must not read as an omitted stage."""
    fixture = load_scenario(name, arm_id=arm)
    cell = f"oakridge-dbos-{name}:{arm}:w0"
    assert adds_stage_code(fixture.arms[0].negative_patches[0], stage_type(cell))


def _journal() -> list[dict[str, Any]]:
    return [
        {"event": "attempt_started", "coordinate": "__route_probe__"},
        {"event": "reserved", "coordinate": "__route_probe__", "attempt_id": "probe"},
        {"event": "attempt_started", "coordinate": "a"},
        {"event": "reserved", "coordinate": "a", "attempt_id": "a:1"},
        {"event": "finished", "attempt_id": "a:1", "status": "settled"},
        {"event": "reserved", "coordinate": "a", "attempt_id": "a:2"},
        {"event": "finished", "attempt_id": "a:2", "status": "not_sent"},
        {"event": "run_manifest", "manifest_ref": "first"},
        {"event": "attempt_started", "coordinate": "b"},
        {"event": "reserved", "coordinate": "b", "attempt_id": "b:1"},
    ]


def test_only_claims_are_dispatched_and_a_later_claim_is_unsettled() -> None:
    records = _journal()
    assert claimed_cells(records) == ["a", "b"]
    assert settled_cells(records) == {"a"}


def test_unsent_requests_are_not_counted() -> None:
    counts = request_counts(_journal())
    assert counts["a"] == 1
    assert counts["b"] == 1
