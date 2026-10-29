"""Render the declared task prompt for each arm of one extension scenario."""

from __future__ import annotations

from assay.fixture_manifest import ExtensionArmSet, ExtensionScenario


def render_arm_prompts(arm_set: ExtensionArmSet, scenario: ExtensionScenario) -> dict[str, str]:
    """Only handoff detail may change the prompt within a scenario."""
    prompts = {arm.arm_id: arm.task_prompt for arm in scenario.arms}
    if set(prompts) != set(arm_set.arm_ids) or len(prompts) != len(scenario.arms):
        raise ValueError("scenario arms differ from the declared arm set")
    distinct = len(set(prompts.values()))
    if arm_set.factor == "handoff_detail":
        if distinct != len(prompts):
            raise ValueError("handoff_detail requires a distinct prompt per arm")
    elif distinct != 1:
        raise ValueError(f"{arm_set.factor} requires one byte-identical prompt")
    return prompts
