"""Rung L, the #468 rewrite: shares, omissions, recorded logs, image check."""

from __future__ import annotations

import json
from dataclasses import asdict

import pytest

from assay.investigations.workflow_correctness import workflow_tree_digest
from verification_pilot.fixtures import GROUPS, OwnershipGroup
from verification_pilot.self_trust.check import REWRITE_RESULT
from verification_pilot.self_trust.ladder import REWRITE
from verification_pilot.self_trust.logs import log_key
from verification_pilot.self_trust.refactor_session import recorded, session_prefix
from verification_pilot.self_trust.rewrite import (
    OMISSIONS,
    ORDER,
    plan_share,
    share_files,
    start_tree,
    subject_tree,
    target_files,
    trees,
)


def test_the_shares_cover_the_whole_rewrite_once() -> None:
    before, after = trees()
    changed = {p for p in set(before) | set(after) if before.get(p) != after.get(p)}
    files = share_files()
    assert sorted(p for group in ORDER for p in files[group]) == sorted(changed)
    assert len(changed) == 43
    assert subject_tree(None) == after


@pytest.mark.parametrize("group", GROUPS)
def test_an_omission_is_one_line_its_share_never_writes(group: OwnershipGroup) -> None:
    clean, omitted = subject_tree(None), subject_tree(group)
    path = OMISSIONS[group].path
    assert [p for p in clean if clean[p] != omitted.get(p)] == [path]
    assert len(clean[path].split("\n")) - len(omitted[path].split("\n")) == 1
    assert path in target_files(group, omit=True)


def test_committed_image_check_holds_for_the_current_generator() -> None:
    result = json.loads(REWRITE_RESULT.read_text(encoding="utf-8"))
    assert result["holds"] is True
    expected = {"start": start_tree(), "clean": subject_tree(None),
                **{f"omit-{group}": subject_tree(group) for group in GROUPS}}
    assert {name: case["tree_digest"] for name, case in result["cases"].items()} == {
        name: workflow_tree_digest(tree) for name, tree in expected.items()}


@pytest.mark.parametrize("remnant", [None, *GROUPS])
def test_recorded_logs_match_the_current_plan(remnant: OwnershipGroup | None) -> None:
    tree = start_tree()
    for group in ORDER:
        omit = group == remnant
        entry = recorded(REWRITE)[log_key("rewrite", group, omit)]
        assert entry["calls"] == [asdict(call) for call in plan_share(tree, group, omit=omit)]
        assert entry["outputs"][-1].startswith("exit=0\n")
        for path, content in target_files(group, omit=omit).items():
            if content is None:
                tree.pop(path, None)
            else:
                tree[path] = content
    assert tree == subject_tree(remnant)


def test_a_rewrite_session_renders_the_owner_claim_from_its_own_check() -> None:
    prefix = session_prefix("group_b", "group_b", "quoted", "holder_first", REWRITE)
    text = prefix[0]["content"]
    assert "Session log: You (group_b)" in text
    assert "is complete: every behaviour moved with the code" in text
