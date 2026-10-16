"""Recorded rendering conditions for the placement contrast."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from verification_pilot.prompts import PILOT_SYSTEM_PROMPT

Placement = Literal["native-template", "quoted-template"]
Route = Literal["smithers-local", "openrouter"]


@dataclass(frozen=True, slots=True)
class RenderArm:
    placement: Placement
    route: Route
    # The quoted arm has one deliberate user turn containing the rotation.
    # Native handoff notes occupy tool results. The joint-final and T1 text
    # is deliberately one user turn, even on routes that merge user turns.
    conditions: tuple[str, ...]
    system_prompt: str = PILOT_SYSTEM_PROMPT


def arm(placement: Placement, route: Route) -> RenderArm:
    return RenderArm(
        placement=placement,
        route=route,
        conditions=(
            "quoted-rotation-in-one-user-message",
            "native-contributor-blocks-as-tool-results",
            "joint-final-and-T1-combined-user-message",
            f"route={route}",
        ),
    )
