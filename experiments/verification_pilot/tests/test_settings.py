"""The pilot's committed settings reach the repository bridge unchanged."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from verification_pilot.bridge import create_pilot_agent
from verification_pilot.inputs import (
    T1_SUBMISSION_SCHEMA,
    T2_SUBMISSION_SCHEMA,
    T3_SUBMISSION_SCHEMA,
)
from verification_pilot.settings import PILOT_TOOLS_SHA256, VerificationPilotSettings


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
    configuration = agent_configuration(
        bounds=agent.bounds, limits=SandboxLimits(),
        writable_prefixes=agent.writable_prefixes, model_route=agent.model_route,
        pilot_mode=True, next_user_turns=agent.next_user_turns,
        max_tool_calls_per_turn=agent.max_tool_calls_per_turn,
        max_tool_calls_per_cell=agent.max_tool_calls_per_cell,
    )
    assert configuration["writable_prefixes"] == ["src/"]
    assert configuration["max_tool_calls_per_turn"] == 7
    assert configuration["max_tool_calls_per_cell"] == 19
