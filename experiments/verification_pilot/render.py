"""Two placements of byte-identical contributor text."""

from __future__ import annotations

import json
from typing import Any

from verification_pilot.arms import RenderArm
from verification_pilot.prompts import JOINT_FINAL_MESSAGE, T1_MESSAGE
from verification_pilot.session import ContributorBlock

Message = dict[str, Any]


def block_text(blocks: tuple[ContributorBlock, ...]) -> str:
    return "\n\n".join(block.text for block in blocks)


def render_prefix(blocks: tuple[ContributorBlock, ...], arm: RenderArm) -> tuple[Message, ...]:
    """Return the pilot's bridge ``message_prefix`` parameter."""
    ending = {"role": "user", "content": f"{JOINT_FINAL_MESSAGE}\n\n{T1_MESSAGE}"}
    if arm.placement == "quoted-template":
        return (
            {"role": "user", "content": f"Quoted contributor handoff:\n{block_text(blocks)}"},
            ending,
        )

    messages: list[Message] = []
    for index, block in enumerate(blocks):
        call_id = f"pilot-contributor-{index + 1}"
        # This is an ordinary OpenAI-shape exchange. The handoff text is the
        # tool result, preserving its bytes in both placements.
        call = {
            "id": call_id,
            "type": "function",
            "function": {
                "name": "read_file",
                "arguments": json.dumps({"path": block.paths[0]}, separators=(",", ":")),
            },
        }
        messages.extend((
            {"role": "assistant", "content": None, "tool_calls": [call]},
            {"role": "tool", "tool_call_id": call_id, "content": block.text},
        ))
    messages.append(ending)
    return tuple(messages)


def request_messages(
    instruction: str, blocks: tuple[ContributorBlock, ...], arm: RenderArm
) -> list[Message]:
    """The exact message array passed as bridge ``message_prefix`` plus task."""
    return [
        {"role": "system", "content": arm.system_prompt},
        {"role": "user", "content": instruction},
        *render_prefix(blocks, arm),
    ]
