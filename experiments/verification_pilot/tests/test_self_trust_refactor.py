"""The self-trust refactor fixture: shares, omissions, recorded logs, sessions."""

from __future__ import annotations

import json
from dataclasses import asdict

import pytest

from assay.investigations.workflow_correctness import workflow_tree_digest
from verification_pilot.fixtures import GROUPS, OwnershipGroup
from verification_pilot.self_trust.check import REFACTOR_RESULT
from verification_pilot.self_trust.logs import log_key
from verification_pilot.self_trust.refactor import (
    HELD_OUT_TESTS,
    MODULES,
    ORDER,
    VISIBLE_TEST,
    apply,
    plan_share,
    share_edits,
    start_tree,
    subject_tree,
)
from verification_pilot.self_trust.refactor_session import recorded, session_prefix
from verification_pilot.self_trust.study import refactor_calibration_ids, self_trust_subjects


def test_committed_image_check_holds_for_the_current_generator() -> None:
    # A generator change fails here until check.py --fixture refactor is re-run.
    result = json.loads(REFACTOR_RESULT.read_text(encoding="utf-8"))
    assert result["holds"] is True
    expected = {"start": start_tree(), "clean": subject_tree(None),
                **{f"omit-{group}": subject_tree(group) for group in GROUPS}}
    assert {name: case["tree_digest"] for name, case in result["cases"].items()} == {
        name: workflow_tree_digest(tree) for name, tree in expected.items()}


def test_the_reserved_id_tests_are_held_out_of_the_visible_suite() -> None:
    visible = start_tree()[VISIBLE_TEST]
    assert not any(name in visible for name in HELD_OUT_TESTS)
    assert visible.count('\ntest("') == 29


@pytest.mark.parametrize("group", GROUPS)
def test_an_omission_changes_only_its_own_module(group: OwnershipGroup) -> None:
    clean, omitted = subject_tree(None), subject_tree(group)
    assert [path for path in clean if clean[path] != omitted[path]] == [MODULES[group]]
    assert len(omitted[MODULES[group]]) < len(clean[MODULES[group]])


@pytest.mark.parametrize("remnant", [None, *GROUPS])
def test_recorded_logs_match_the_current_plan(remnant: OwnershipGroup | None) -> None:
    # A planner change fails here until record.py --fixture refactor is re-run.
    tree = start_tree()
    for group in ORDER:
        omit = group == remnant
        entry = recorded()[log_key("refactor", group, omit)]
        assert entry["calls"] == [asdict(call) for call in plan_share(tree, group, omit=omit)]
        assert entry["outputs"][-1] == "exit=0\n 29 pass\n 0 fail\n"
        tree = apply(tree, share_edits(tree, group, omit=omit))
    assert tree == subject_tree(remnant)


def test_arms_place_only_the_own_log_differently() -> None:
    native = session_prefix("group_a", "group_a", "native")
    quoted = session_prefix("group_a", "group_a", "quoted")
    assert [m["role"] for m in quoted] == ["user"]
    assert native[0]["role"] == "assistant" and native[-1]["role"] == "user"
    for group in ("group_b", "group_c"):
        assert f"Session log: {group}" in native[-1]["content"]
        assert f"Session log: {group}" in quoted[0]["content"]
    assert "Session log: You (group_a)" in quoted[0]["content"]
    assert "Session log: You" not in native[-1]["content"]


def test_refactor_calibration_pairs_own_and_teammate_cells_per_omission() -> None:
    subjects = self_trust_subjects()
    by_id = {s.id: s for s in subjects}
    ids = refactor_calibration_ids(subjects)
    assert len(ids) == 6
    for own_id, teammate_id in zip(ids[::2], ids[1::2], strict=True):
        own, teammate = by_id[own_id], by_id[teammate_id]
        assert (own.condition, teammate.condition) == ("own", "teammate")
        assert own.remnant_owner == teammate.remnant_owner
        assert own.repository == teammate.repository
