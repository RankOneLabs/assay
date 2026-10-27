"""The model-visible self-trust instructions and turns."""

from __future__ import annotations

from itertools import zip_longest

import pytest

from assay.pier_packaging import REPOSITORY_AGENT_WORKSPACE, render_instruction
from verification_pilot.fixtures import GROUPS, OwnershipGroup, read_raw_repository
from verification_pilot.self_trust.bridge import subject_prefix, subject_system_prompt
from verification_pilot.self_trust.concepts import CONCEPTS, Concept
from verification_pilot.self_trust.ladder import (
    RESUME_146,
    REWRITE,
    REWRITE_0,
    REWRITE_1,
    RUNGS,
    Rung,
)
from verification_pilot.self_trust.prompts import (
    T2_TEXT,
    T3_TEXT,
    build_system_prompt,
    framing_for,
    t1_message,
)
from verification_pilot.self_trust.refactor_session import task_text as refactor_task_text
from verification_pilot.self_trust.session import task_text as rename_task_text
from verification_pilot.self_trust.study import (
    MATCHED_ARMS,
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


@pytest.mark.parametrize("rung", (REWRITE, REWRITE_0, RESUME_146, REWRITE_1),
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
    assert message in subject_prefix(subject, "st-native")[-1]["content"]


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
