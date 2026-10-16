"""The pilot's committed settings reach the repository bridge unchanged."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from assay_pier_bridge.agent_loop import PILOT_TOOL_SCHEMAS, SandboxLimits
from assay_pier_bridge.identity import canonical_json, digest_bytes
from assay_pier_bridge.protocol import ModelRoute
from assay_pier_bridge.repository_trial import agent_configuration

from verification_pilot.bridge import create_pilot_agent
from verification_pilot.settings import PILOT_TOOLS_SHA256, VerificationPilotSettings


def test_committed_pilot_tool_digest_matches_schema() -> None:
    assert digest_bytes(canonical_json(PILOT_TOOL_SCHEMAS)) == PILOT_TOOLS_SHA256


def test_pilot_agent_and_configuration_consume_settings(tmp_path: Path) -> None:
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
