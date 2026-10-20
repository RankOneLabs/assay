"""Recorded rendering conditions for the placement contrast."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from verification_pilot.inputs import PILOT_SYSTEM_PROMPT

Placement = Literal["native-template", "quoted-template"]
Route = Literal["smithers-local", "openrouter"]
SCHEDULE = "subject-rotated-v1"
TIER_1_ARMS = ("t1-native", "t1-quoted")
TIER_2_ARMS = ("t2-native", "t2-quoted")
TIER_3_ARMS = ("t3-native", "t3-quoted")
ALL_ARMS = TIER_1_ARMS + TIER_2_ARMS + TIER_3_ARMS


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
    placement_condition = (
        "quoted-rotation-in-one-user-message"
        if placement == "quoted-template"
        else "native-contributor-blocks-as-tool-results"
    )
    return RenderArm(
        placement=placement,
        route=route,
        conditions=(
            placement_condition,
            "joint-final-and-T1-combined-user-message",
            f"route={route}",
        ),
    )


def placement_for(arm_id: str) -> Placement:
    if arm_id not in ALL_ARMS:
        raise ValueError(f"unknown pilot arm: {arm_id}")
    return "native-template" if arm_id.endswith("native") else "quoted-template"
