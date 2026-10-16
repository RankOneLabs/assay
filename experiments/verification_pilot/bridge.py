"""Construct the verification pilot's repository agent from its frozen settings."""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

_BRIDGE_SRC = Path(__file__).resolve().parents[2] / "integrations" / "pier" / "src"
if str(_BRIDGE_SRC) not in sys.path:
    sys.path.insert(0, str(_BRIDGE_SRC))

from assay_pier_bridge.agent_loop import (  # noqa: E402
    CellStorage,
    DockerToolSandbox,
    LoopBounds,
    QuotaCellStorage,
    RepositoryAgentClient,
    SandboxFactory,
    TurnCompletion,
)
from assay_pier_bridge.protocol import ModelRoute  # noqa: E402

from verification_pilot.settings import VerificationPilotSettings  # noqa: E402


def create_pilot_agent(
    *,
    settings: VerificationPilotSettings,
    image: str,
    runs_root: Path,
    model_route: ModelRoute,
    completion: TurnCompletion | None,
    next_user_turns: tuple[str, ...],
    api_key: str | None = None,
    sandbox_factory: SandboxFactory = DockerToolSandbox,
    storage_factory: Callable[[Path, int], CellStorage] = QuotaCellStorage,
) -> RepositoryAgentClient:
    """Use the pilot's declared scope and call budgets for the actual loop."""
    return RepositoryAgentClient(
        api_key=api_key,
        image=image,
        runs_root=runs_root,
        model_route=model_route,
        completion=completion,
        bounds=LoopBounds(
            max_turns=settings.max_turns,
            max_tool_schema_bytes=settings.max_tool_schema_bytes,
            max_tool_output_bytes=settings.max_tool_output_bytes,
            max_conversation_bytes=settings.max_conversation_bytes,
            max_request_bytes=settings.max_request_bytes,
            max_response_bytes=settings.max_response_bytes,
            max_output_tokens=settings.max_output_tokens,
            max_storage_mb=settings.max_storage_mb,
        ),
        pilot_mode=True,
        next_user_turns=next_user_turns,
        writable_prefixes=settings.writable_prefixes,
        max_tool_calls_per_turn=settings.max_tool_calls_per_turn,
        max_tool_calls_per_cell=settings.max_tool_calls_per_cell,
        sandbox_factory=sandbox_factory,
        storage_factory=storage_factory,
    )
