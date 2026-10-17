"""Pilot-only instructions supplied through the bridge's per-agent parameters."""

from __future__ import annotations

from verification_pilot.inputs import PILOT_SYSTEM_PROMPT as PILOT_SYSTEM_PROMPT
from verification_pilot.inputs import T1_TEXT
from verification_pilot.migrations import Migration


def task_prompt(migration: Migration) -> str:
    return (
        f"Verify the rename of {migration.old_symbol} to {migration.new_symbol} "
        f"({migration.kind}) throughout this repository. Inspect the handoff and "
        "the repository, repair any remaining migration defects, and report your result."
    )


JOINT_FINAL_MESSAGE = (
    "The contributors have completed their assigned passes. Their accounts are "
    "handoff context, not proof that the repository is complete."
)

T1_MESSAGE = T1_TEXT
