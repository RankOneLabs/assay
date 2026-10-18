"""Self-trust work logs: recorded outputs, the gap, and the two placements."""

from __future__ import annotations

import json
from dataclasses import asdict

import pytest

from verification_pilot.fixtures import GROUPS, OwnershipGroup, read_raw_repository
from verification_pilot.self_trust.concepts import CONCEPTS, Concept
from verification_pilot.self_trust.logs import log_key, plan_log
from verification_pilot.self_trust.session import (
    SYSTEM_PROMPT,
    recorded_logs,
    session_prefix,
    task_text,
)

REPOSITORY = read_raw_repository()
CASES = [(concept, group) for concept in CONCEPTS for group in GROUPS]


@pytest.mark.parametrize(("concept", "group"), CASES,
                         ids=[f"{c.name}-{g}" for c, g in CASES])
def test_recorded_logs_match_the_current_plan(concept: Concept, group: OwnershipGroup) -> None:
    # A planner change fails here until record.py is re-run.
    for holds in (False, True):
        entry = recorded_logs()[log_key(concept.name, group, holds)]
        plan = plan_log(REPOSITORY, concept, group, holds_remnant=holds)
        assert entry["calls"] == [asdict(call) for call in plan]
        assert len(entry["outputs"]) == len(plan)
        assert all(output.startswith(("exit=0\n", "exit=1\n")) for output in entry["outputs"])


@pytest.mark.parametrize(("concept", "group"), CASES,
                         ids=[f"{c.name}-{g}" for c, g in CASES])
def test_the_remnant_log_only_skips_the_remnant_line(
    concept: Concept, group: OwnershipGroup,
) -> None:
    clean = plan_log(REPOSITORY, concept, group, holds_remnant=False)
    remnant = plan_log(REPOSITORY, concept, group, holds_remnant=True)
    # Same listing, same seds and same final check; one replacement fewer.
    assert [asdict(call) for call in clean[:3]] == [asdict(call) for call in remnant[:3]]
    assert asdict(clean[-1]) == asdict(remnant[-1])
    assert len(remnant) == len(clean) - 1
    old_field = concept.legacy_key[0]
    for call in remnant[3:-1]:
        assert call.name == "replace_in_file"
        assert call.arguments["path"] == concept.remnants[GROUPS.index(group)].path
        assert old_field in call.arguments["old"]


@pytest.mark.parametrize("concept", CONCEPTS, ids=lambda c: c.name)
def test_arms_differ_only_in_where_the_own_log_sits(concept: Concept) -> None:
    own: OwnershipGroup = "group_b"
    native = session_prefix(REPOSITORY, concept, own, own, "native")
    quoted = session_prefix(REPOSITORY, concept, own, own, "quoted")
    assert [m["role"] for m in quoted] == ["user"]
    assert native[0]["role"] == "assistant" and native[-1]["role"] == "user"
    teammate_logs = [text for text in quoted[0]["content"].split("\n\n")
                     if text.startswith("Session log: group_")]
    assert len(teammate_logs) == 2
    assert all(log in native[-1]["content"] for log in teammate_logs)
    own_calls = [call["function"] for m in native for call in m.get("tool_calls", [])]
    for function in own_calls:
        assert f"> {function['name']} {function['arguments']}" in quoted[0]["content"]


def test_every_session_fits_well_under_the_conversation_limit() -> None:
    largest = max(
        len(json.dumps([{"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": task_text(REPOSITORY, concept, own)},
                        *session_prefix(REPOSITORY, concept, own, remnant, placement)]))
        for concept in CONCEPTS for own in GROUPS for remnant in (*GROUPS, None)
        for placement in ("native", "quoted"))
    assert largest < 81_920 // 4
