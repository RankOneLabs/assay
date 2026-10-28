"""The model-visible self-trust instructions and turns."""

from __future__ import annotations

import re
from itertools import combinations, zip_longest

import pytest

from assay.canonical import canonical_json, digest_bytes
from assay.code_intel.baseline import select_code_intel
from assay.code_intel.contract import (
    CodeIntelSettings,
    append_code_intel_prefix,
    append_code_intel_tools,
    render_code_intel_prompt,
)
from assay.code_intel.errors import Ok
from assay.code_intel.models import BaselineMode
from assay.pier_packaging import REPOSITORY_AGENT_WORKSPACE, render_instruction
from verification_pilot.fixtures import GROUPS, OwnershipGroup, read_raw_repository
from verification_pilot.self_trust.bridge import (
    subject_prefix,
    subject_system_prompt,
    subject_turns,
)
from verification_pilot.self_trust.concepts import CONCEPTS, Concept
from verification_pilot.self_trust.ladder import (
    RESUME_146,
    REWRITE,
    REWRITE_0,
    REWRITE_1,
    REWRITE_2,
    RUNGS,
    Rung,
)
from verification_pilot.self_trust.pins import SYSTEM_PROMPT_SHA256, TURN_PROMPTS_SHA256
from verification_pilot.self_trust.prompts import (
    T2_TEXT,
    T3_TEXT,
    build_system_prompt,
    framing_for,
    t1_message,
)
from verification_pilot.self_trust.refactor_session import (
    session_prefix as refactor_session_prefix,
)
from verification_pilot.self_trust.refactor_session import task_text as refactor_task_text
from verification_pilot.self_trust.session import T1_TEXT
from verification_pilot.self_trust.session import task_text as rename_task_text
from verification_pilot.self_trust.study import (
    ARMS,
    MATCHED_ARMS,
    order_for,
    placement_for,
    realization_payload,
    self_trust_subjects,
)


@pytest.mark.parametrize("own", GROUPS)
@pytest.mark.parametrize("rung", RUNGS.values(), ids=lambda rung: rung.name)
def test_refactor_task_has_one_heading_and_workspace(own: OwnershipGroup, rung: Rung) -> None:
    rendered = render_instruction(refactor_task_text(own, rung), "repository-agent")
    assert rendered.count("# Task\n\n") == 1
    assert rendered.count(REPOSITORY_AGENT_WORKSPACE) == 1


@pytest.mark.parametrize("own", GROUPS)
@pytest.mark.parametrize("concept", CONCEPTS, ids=lambda concept: concept.name)
def test_rename_task_has_one_heading_and_workspace(own: OwnershipGroup, concept: Concept) -> None:
    rendered = render_instruction(rename_task_text(read_raw_repository(), concept, own),
                                  "repository-agent")
    assert rendered.count("# Task\n\n") == 1
    assert rendered.count(REPOSITORY_AGENT_WORKSPACE) == 1


@pytest.mark.parametrize("rung", (REWRITE, REWRITE_0, RESUME_146, REWRITE_1, REWRITE_2),
                         ids=lambda rung: rung.name)
@pytest.mark.parametrize("own", GROUPS)
def test_refactor_prompt_agrees_with_task_framing(rung: Rung, own: OwnershipGroup) -> None:
    task = refactor_task_text(own, rung)
    framing = framing_for(rung, own)
    prompt = build_system_prompt(rung, framing)
    assert "rename" not in prompt.lower()
    assert "once" not in prompt.lower()
    assert "There are three turns, and each turn ends with one `submit_output` call." in prompt
    if framing == "two_teammates":
        assert "You and two teammates" in task and "two teammates" in prompt
    elif framing == "one_teammate":
        assert "You and a teammate" in task and "a teammate" in prompt
    elif framing == "own_work":
        assert "The work is yours" in task and "The work is yours" in prompt
        assert "teammate" not in prompt
    else:
        assert "your part is to verify it" in task and "your part is to verify it" in prompt
        assert "You wrote none of the work" in prompt


@pytest.mark.parametrize("message", (T2_TEXT, T3_TEXT))
def test_followup_turns_request_their_submission_fields(message: str) -> None:
    assert "A new submission is expected this turn" in message
    for field in ("verdict", "remaining_v1", "checks_performed"):
        assert f"`{field}`" in message


@pytest.mark.parametrize("rung", (REWRITE, REWRITE_0, RESUME_146),
                         ids=lambda rung: rung.name)
def test_first_turn_requests_its_submission_fields(rung: Rung) -> None:
    message = t1_message(rung)
    assert "A new submission is expected this turn" in message
    assert "`title`" in message and "`body`" in message
    holder = rung.order[0]
    subject = next(subject for subject in self_trust_subjects()
                   if subject.fixture == rung.name and subject.own == holder
                   and subject.remnant_owner == holder)
    direct_prefix = refactor_session_prefix(holder, holder, "native", rung=rung)
    assert direct_prefix == subject_prefix(subject, "st-native")
    assert message in direct_prefix[-1]["content"]


@pytest.mark.parametrize("rung", (REWRITE, REWRITE_0, RESUME_146),
                         ids=lambda rung: rung.name)
def test_matched_arms_differ_only_in_holder_labels(rung: Rung) -> None:
    holder = rung.order[0]
    subject = next(subject for subject in self_trust_subjects()
                   if subject.fixture == rung.name and subject.own == holder
                   and subject.remnant_owner == holder)
    own_arm, teammate_arm = MATCHED_ARMS
    own_task = render_instruction(realization_payload(subject, own_arm)["task"],
                                  "repository-agent")
    teammate_task = render_instruction(realization_payload(subject, teammate_arm)["task"],
                                       "repository-agent")
    own_prefix = subject_prefix(subject, own_arm)
    teammate_prefix = subject_prefix(subject, teammate_arm)
    assert [item["role"] for item in own_prefix] == ["user"]
    assert [item["role"] for item in teammate_prefix] == ["user"]
    assert subject_system_prompt(subject, own_arm) == subject_system_prompt(subject, teammate_arm)
    own_lines = (own_task + own_prefix[0]["content"]).splitlines()
    teammate_lines = (teammate_task + teammate_prefix[0]["content"]).splitlines()
    differences = [(left, right) for left, right in zip_longest(own_lines, teammate_lines)
                   if left != right]
    assert differences[0] == (f"- {holder} (you): {rung.share_work[holder]}",
                              f"- {holder}: {rung.share_work[holder]}")
    assert len(differences) == 4
    assert differences[1] == (f"Session log: You ({holder})", f"Session log: {holder}")
    for own_line, teammate_line in differences[2:]:
        assert own_line.startswith(f"You ({holder}): ")
        assert own_line.replace(f"You ({holder}): ", f"{holder}: ", 1) == teammate_line


def test_baseline_arm_pairs_keep_existing_prompts_prefixes_and_dispatched_tools() -> None:
    """All 15 arm pairs retain their existing differences and identical tool bytes."""
    # The bridge source path is installed by verification_pilot.bridge.
    from assay_pier_bridge.agent_loop import PILOT_TOOL_SCHEMAS

    selected = select_code_intel(CodeIntelSettings(mode=BaselineMode()))
    assert isinstance(selected, Ok)
    code_intel = selected.value
    assert code_intel.prompt_block() is None and code_intel.prefix_block() == ()
    subject = next(subject for subject in self_trust_subjects()
                   if subject.fixture == "refactor" and subject.own == "group_a"
                   and subject.remnant_owner == "group_b")
    assert digest_bytes(canonical_json(list(subject_turns()))) == TURN_PROMPTS_SHA256
    rendered = {}
    expected_placement_and_order = {
        "st-native": ("native", "own_first"),
        "st-quoted": ("quoted", "own_first"),
        "st-quoted-first": ("quoted", "holder_first"),
        "st-quoted-last": ("quoted", "holder_last"),
        "st-matched-own": ("quoted", "own_first"),
        "st-matched-teammate": ("quoted", "own_first"),
    }
    assert {arm: (placement_for(arm), order_for(arm)) for arm in ARMS} == (
        expected_placement_and_order
    )
    for arm in ARMS:
        prompt = subject_system_prompt(subject, arm)
        prefix = subject_prefix(subject, arm)
        baseline_prompt = render_code_intel_prompt(prompt, code_intel.prompt_block())
        baseline_prefix = append_code_intel_prefix(prefix, code_intel.prefix_block())
        assert baseline_prompt == prompt
        assert baseline_prefix == prefix
        tools_by_turn = {
            turn: append_code_intel_tools(PILOT_TOOL_SCHEMAS[turn], code_intel.tools())
            for turn in ("T1", "T2_T3")
        }
        for turn in tools_by_turn:
            assert digest_bytes(canonical_json(tools_by_turn[turn])) == digest_bytes(
                canonical_json(PILOT_TOOL_SCHEMAS[turn]))
        rendered[arm] = (baseline_prompt, baseline_prefix, tools_by_turn)
        if arm in ("st-native", "st-quoted", "st-quoted-first", "st-quoted-last"):
            assert digest_bytes(prompt.encode("utf-8")) == SYSTEM_PROMPT_SHA256[
                ("refactor", framing_for(RUNGS["refactor"], subject.own))]
        else:
            assert digest_bytes(prompt.encode("utf-8")) == SYSTEM_PROMPT_SHA256[
                ("refactor", "matched")]
    assert len(list(combinations(ARMS, 2))) == 15
    expected_logs = {
        "st-native": ("group_b", "group_c"),
        "st-quoted": ("You (group_a)", "group_b", "group_c"),
        "st-quoted-first": ("group_b", "You (group_a)", "group_c"),
        "st-quoted-last": ("You (group_a)", "group_c", "group_b"),
        "st-matched-own": ("You (group_b)", "group_a", "group_c"),
        "st-matched-teammate": ("group_b", "group_a", "group_c"),
    }
    ordered_prefixes = {arm: rendered[arm][1] for arm in ARMS}
    for arm, prefix in ordered_prefixes.items():
        assert tuple(re.findall(r"^Session log: (.+)$", prefix[-1]["content"], re.M)) == (
            expected_logs[arm]
        )
        assert [item["role"] for item in prefix] == (
            ["user"] if arm != "st-native" else ["assistant", "tool"] * 8 + ["assistant", "user"]
        )
    quoted_blocks = []
    for arm in ("st-quoted", "st-quoted-first", "st-quoted-last"):
        content = ordered_prefixes[arm][0]["content"]
        log_text = content.split("Session log: ", 1)[1].split(
            "\n\nAll three shares are done.", 1
        )[0]
        quoted_blocks.append(sorted(log_text.split("\n\nSession log: ")))
    assert quoted_blocks[0] == quoted_blocks[1] == quoted_blocks[2]
    for left, right in combinations(ARMS, 2):
        left_prompt, left_prefix, left_tools = rendered[left]
        right_prompt, right_prefix, right_tools = rendered[right]
        assert (left_prompt != right_prompt) == ((left in MATCHED_ARMS) !=
                                                 (right in MATCHED_ARMS))
        assert left_prefix != right_prefix
        for turn in ("T1", "T2_T3"):
            assert left_tools[turn] == right_tools[turn]


@pytest.mark.parametrize("rung", RUNGS.values(), ids=lambda rung: rung.name)
def test_hidden_path_is_derived_from_every_rung(rung: Rung) -> None:
    from assay.code_intel.snapshot import hidden_paths, hidden_sources

    assert hidden_paths(rung) == frozenset({"tests/hidden/omissions.test.ts"})
    assert hidden_sources(rung)[rung.hidden_test] == rung.hidden_tests


def test_subject_owners_have_distinct_snapshot_and_index_keys() -> None:
    from assay.code_intel.snapshot import index_cache_key, repo_revision

    revisions = [repo_revision(RUNGS["refactor"].subject_tree(owner)) for owner in GROUPS]
    assert len(set(revisions)) == 3
    keys = [index_cache_key(revision, "sha256:" + "1" * 64, "symbols/1")
            for revision in revisions]
    assert len(set(keys)) == 3


@pytest.mark.parametrize("fixture", ("refactor", "rewrite0", "rename"))
@pytest.mark.parametrize("arm_id", ARMS)
def test_preloaded_block_has_one_position_in_every_arm(
    fixture: str, arm_id: str,
) -> None:
    if fixture == "rename" and arm_id in ("st-quoted-first", "st-quoted-last"):
        pytest.skip("the rename fixture does not vary log order")
    subject = next(subject for subject in self_trust_subjects()
                   if subject.fixture == fixture and subject.own == "group_a"
                   and subject.remnant_owner == "group_a")
    before = subject_prefix(subject, arm_id)
    after = subject_prefix(subject, arm_id, codeintel_block="INDEX BLOCK\n")
    assert len(after) == len(before)
    assert after[:-1] == before[:-1]
    assert after[-1]["role"] == "user"
    turn1 = t1_message(RUNGS[fixture]) if fixture in RUNGS else T1_TEXT
    assert before[-1]["content"].endswith(turn1)
    assert after[-1]["content"] == before[-1]["content"][:-len(turn1)] + (
        "INDEX BLOCK\n\n" + turn1
    )
