"""Render the declared task prompt for each arm of one extension scenario."""

from __future__ import annotations

from assay.fixture_manifest import ExtensionArmSet, ExtensionScenario


def render_initial_task(
    *, feature_request: str, workspace_and_test_instructions: str,
    writable_scope: tuple[str, ...], budget: str,
) -> str:
    """Render ce-v1's one model-visible user turn in its fixed four-part order."""
    if not all((feature_request, workspace_and_test_instructions, writable_scope, budget)):
        raise ValueError("all four ce-v1 task parts are required")
    scope = "\n".join(f"- {path}" for path in writable_scope)
    return (
        f"# Feature request\n\n{feature_request}\n\n"
        f"# Workspace and tests\n\n{workspace_and_test_instructions}\n\n"
        f"# Writable scope\n\n{scope}\n\n"
        f"# Budget\n\n{budget}\n"
    )


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
