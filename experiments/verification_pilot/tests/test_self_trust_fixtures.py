"""The one-share fixtures: the forge move/rewrite pair and #146."""

from __future__ import annotations

import json
from dataclasses import asdict

import pytest

from assay.investigations.workflow_correctness import workflow_tree_digest
from verification_pilot.self_trust.fixtures import CHANGES, FORGE_MOVE, FORGE_REWRITE, SHARE
from verification_pilot.self_trust.ladder import RUNGS
from verification_pilot.self_trust.logs import log_key
from verification_pilot.self_trust.refactor_session import recorded

NAMES = sorted(CHANGES)


def test_the_forge_pair_differs_only_in_the_kind_of_change() -> None:
    assert FORGE_MOVE.start_tree() == FORGE_REWRITE.start_tree()
    assert FORGE_MOVE.hidden_tests == FORGE_REWRITE.hidden_tests
    assert FORGE_MOVE.omission.path == FORGE_REWRITE.omission.path
    assert FORGE_MOVE.visible_tests == FORGE_REWRITE.visible_tests
    moved = set(FORGE_MOVE.subject_tree(None))
    assert moved == set(FORGE_REWRITE.subject_tree(None)) - {"src/forge/rules.ts"}


@pytest.mark.parametrize("name", NAMES)
def test_the_omission_is_one_span_in_one_file(name: str) -> None:
    change = CHANGES[name]
    clean, omitted = change.subject_tree(None), change.subject_tree(SHARE)
    assert [path for path in clean if clean[path] != omitted.get(path)] == [change.omission.path]
    assert change.omission.clean in clean[change.omission.path]
    assert change.omission.clean not in omitted[change.omission.path]


@pytest.mark.parametrize("name", NAMES)
def test_committed_image_check_holds_for_the_current_trees(name: str) -> None:
    rung = RUNGS[name]
    result = json.loads((rung.logs.parent / f"{name}-check.json").read_text(encoding="utf-8"))
    assert result["holds"] is True
    expected = {"start": rung.start_tree(), "clean": rung.subject_tree(None),
                f"omit-{SHARE}": rung.subject_tree(SHARE)}
    assert {case: entry["tree_digest"] for case, entry in result["cases"].items()} == {
        case: workflow_tree_digest(tree) for case, tree in expected.items()}


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("omit", [False, True])
def test_recorded_logs_match_the_current_plan(name: str, omit: bool) -> None:
    rung = RUNGS[name]
    entry = recorded(rung)[log_key(name, SHARE, omit)]
    calls = rung.plan_share(rung.start_tree(), SHARE, omit=omit)
    assert entry["calls"] == [asdict(call) for call in calls]
    assert entry["outputs"][-1].startswith("exit=0\n")
