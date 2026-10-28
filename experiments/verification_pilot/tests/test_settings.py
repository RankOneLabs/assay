"""The pilot's committed settings reach the repository bridge unchanged."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from assay.canonical import canonical_json, digest_bytes
from verification_pilot.arms import ALL_ARMS, arm, placement_for
from verification_pilot.bridge import create_pilot_agent
from verification_pilot.fixture import load_fixture
from verification_pilot.inputs import (
    PILOT_SYSTEM_PROMPT,
    T1_SUBMISSION_SCHEMA,
    T2_SUBMISSION_SCHEMA,
    T2_TEXT,
    T3_SUBMISSION_SCHEMA,
    T3_TEXT,
)
from verification_pilot.migrations import MIGRATIONS
from verification_pilot.prompts import task_prompt
from verification_pilot.render import request_messages
from verification_pilot.session import contributor_blocks, rotated_blocks
from verification_pilot.settings import PILOT_TOOLS_SHA256, VerificationPilotSettings
from verification_pilot.study import pilot_subjects


def test_writable_prefixes_are_strict_nonempty_directories() -> None:
    settings = VerificationPilotSettings(writable_prefixes=("adapters/", "core/"))
    assert settings.writable_prefixes == ("adapters/", "core/")
    for invalid in ((), ("",), ("../core/",), ("core",)):
        with pytest.raises(ValidationError):
            VerificationPilotSettings(writable_prefixes=invalid)
    with pytest.raises(ValidationError):
        VerificationPilotSettings(writable_prefixes=["src/"])  # type: ignore[arg-type]


def test_committed_pilot_tool_digest_matches_schema() -> None:
    # Import after verification_pilot.bridge adds the isolated bridge source path.
    from assay_pier_bridge.agent_loop import PILOT_TOOL_SCHEMAS
    from assay_pier_bridge.identity import canonical_json, digest_bytes

    assert digest_bytes(canonical_json(PILOT_TOOL_SCHEMAS)) == PILOT_TOOLS_SHA256
    for name, schema in (("T1", T1_SUBMISSION_SCHEMA),
                         ("T2_T3", T2_SUBMISSION_SCHEMA),
                         ("T2_T3", T3_SUBMISSION_SCHEMA)):
        submit = next(tool for tool in PILOT_TOOL_SCHEMAS[name]
                      if tool["function"]["name"] == "submit_output")
        parameters = submit["function"]["parameters"]
        assert tuple(parameters["properties"]) == schema.required
        assert tuple(parameters["required"]) == schema.required
        assert parameters["additionalProperties"] is schema.additional_properties
        for field in schema.fields:
            actual = parameters["properties"][field.name]
            assert actual["type"] == field.value_type
            if field.allowed_values:
                assert tuple(actual["enum"]) == field.allowed_values


def test_baseline_code_intel_mode_is_selected_from_study_settings(tmp_path: Path) -> None:
    from assay_pier_bridge.agent_loop import PILOT_TOOL_SCHEMAS
    from assay_pier_bridge.protocol import ModelRoute

    settings = VerificationPilotSettings.model_validate({
        "code_intel": {"mode": {"kind": "baseline"}},
    })
    agent = create_pilot_agent(
        settings=settings, image="img", runs_root=tmp_path,
        model_route=ModelRoute(endpoint="http://willie:8900", model="qwen-coder-32b",
                               provider="smithers-local"),
        completion=lambda **_: None, next_user_turns=("Review", "Check"),
    )
    assert settings.code_intel.mode.kind == "baseline"
    assert agent.system_prompt == PILOT_SYSTEM_PROMPT
    assert agent.message_prefix == ()
    assert agent.pilot_tools_by_turn == PILOT_TOOL_SCHEMAS
    assert digest_bytes(canonical_json(agent.pilot_tools_by_turn)) == PILOT_TOOLS_SHA256


def test_pilot_agent_and_configuration_consume_settings(tmp_path: Path) -> None:
    from assay_pier_bridge.agent_loop import SandboxLimits
    from assay_pier_bridge.protocol import ModelRoute
    from assay_pier_bridge.repository_trial import agent_configuration

    # Different values expose a hard-coded bridge limit or scope immediately.
    settings = VerificationPilotSettings().model_copy(update={
        "writable_prefixes": ("src/",),
        "max_tool_calls_per_turn": 7,
        "max_tool_calls_per_cell": 19,
    })
    route = ModelRoute(
        endpoint="http://willie:8900", model="qwen-coder-32b", provider="smithers-local"
    )

    def completion(**kwargs: Any) -> Any:
        raise AssertionError("construction must not dispatch a turn")

    agent = create_pilot_agent(
        settings=settings, image="img", runs_root=tmp_path, model_route=route,
        completion=completion, next_user_turns=("Review", "Check"),
    )
    assert agent.writable_prefixes == settings.writable_prefixes
    assert agent.max_tool_calls_per_turn == settings.max_tool_calls_per_turn
    assert agent.max_tool_calls_per_cell == settings.max_tool_calls_per_cell
    assert agent.system_prompt == PILOT_SYSTEM_PROMPT
    configuration = agent_configuration(
        bounds=agent.bounds, limits=SandboxLimits(),
        writable_prefixes=agent.writable_prefixes, model_route=agent.model_route,
        pilot_mode=True, pilot_tools_by_turn=agent.pilot_tools_by_turn,
        next_user_turns=agent.next_user_turns,
        system_prompt=agent.system_prompt,
        max_tool_calls_per_turn=agent.max_tool_calls_per_turn,
        max_tool_calls_per_cell=agent.max_tool_calls_per_cell,
    )
    assert configuration["writable_prefixes"] == ["src/"]
    assert configuration["max_tool_calls_per_turn"] == 7
    assert configuration["max_tool_calls_per_cell"] == 19
    from assay_pier_bridge.identity import canonical_json, digest_bytes

    assert digest_bytes(canonical_json(agent.pilot_tools_by_turn)) == PILOT_TOOLS_SHA256
    assert configuration["tools_sha256"] == PILOT_TOOLS_SHA256
    assert configuration["tools_t1_sha256"] == digest_bytes(
        canonical_json(agent.pilot_tools_by_turn["T1"]))
    assert configuration["tools_t2_t3_sha256"] == digest_bytes(
        canonical_json(agent.pilot_tools_by_turn["T2_T3"]))
    assert configuration["system_prompt_sha256"] == digest_bytes(
        PILOT_SYSTEM_PROMPT.encode("utf-8")
    )


def test_pilot_agent_accepts_instance_turn_tools_before_size_check(tmp_path: Path) -> None:
    from assay_pier_bridge.agent_loop import PILOT_TOOL_SCHEMAS
    from assay_pier_bridge.protocol import ModelRoute

    supplied: dict[str, list[dict[str, Any]]] = json.loads(json.dumps(PILOT_TOOL_SCHEMAS))
    supplied["T2_T3"].append({
        "type": "function", "function": {"name": "extra", "description": "provider tool"},
    })
    route = ModelRoute(
        endpoint="http://willie:8900", model="qwen-coder-32b", provider="smithers-local")

    def completion(**kwargs: Any) -> Any:
        raise AssertionError("construction must not dispatch a turn")

    agent = create_pilot_agent(
        settings=VerificationPilotSettings(), image="img", runs_root=tmp_path,
        model_route=route, completion=completion,
        next_user_turns=("Review", "Check"), pilot_tools_by_turn=supplied,
    )
    assert agent.pilot_tools_by_turn == supplied
    assert agent.pilot_tools_by_turn["T1"] == PILOT_TOOL_SCHEMAS["T1"]
    assert agent.pilot_tools_by_turn["T2_T3"] != PILOT_TOOL_SCHEMAS["T2_T3"]
    supplied["T2_T3"].append({
        "type": "function", "function": {"name": "large", "description": "x" * 16_384},
    })
    with pytest.raises(ValueError, match="tool_schema_limit"):
        create_pilot_agent(
            settings=VerificationPilotSettings(), image="img", runs_root=tmp_path,
            model_route=route, completion=completion,
            next_user_turns=("Review", "Check"), pilot_tools_by_turn=supplied,
        )


def test_pilot_turn_texts_and_byte_envelope() -> None:
    settings = VerificationPilotSettings()
    assert (T2_TEXT, T3_TEXT) == (
        "T2: Review your first finding.", "T3: Check again and submit.",
    )
    assert settings.max_conversation_bytes == 3_670_016
    assert settings.max_request_bytes == 3_932_160
    assert settings.max_conversation_bytes < settings.max_request_bytes <= 4_000_000


def test_qualification_sizes_match_the_rendered_fixture() -> None:
    fixture = load_fixture()
    assert len(fixture.repository) == 62
    assert sum(len(source.encode()) for source in fixture.repository.values()) == 348_936
    migration = MIGRATIONS[0]
    assert sum(
        len(line.encode()) for path in migration.use_sites
        for line in fixture.repository[path].splitlines(keepends=True)
        if migration.old_symbol in line
    ) == 9_512
    sizes = [
        len(json.dumps(
            request_messages(
                task_prompt(subject.migration),
                rotated_blocks(contributor_blocks(subject.migration), subject.rotation),
                arm(placement_for(arm_id), "smithers-local"),
            ), separators=(",", ":"), ensure_ascii=False,
        ).encode())
        for subject in pilot_subjects(fixture) for arm_id in ALL_ARMS
    ]
    assert max(sizes) == 2_843
