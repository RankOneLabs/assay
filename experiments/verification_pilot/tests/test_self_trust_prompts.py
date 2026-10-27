"""The model-visible self-trust instructions and turns."""

from __future__ import annotations

import pytest

from assay.pier_packaging import REPOSITORY_AGENT_WORKSPACE, render_instruction
from verification_pilot.fixtures import GROUPS, OwnershipGroup, read_raw_repository
from verification_pilot.self_trust.concepts import CONCEPTS, Concept
from verification_pilot.self_trust.ladder import RUNGS, Rung
from verification_pilot.self_trust.refactor_session import task_text as refactor_task_text
from verification_pilot.self_trust.session import task_text as rename_task_text


@pytest.mark.parametrize("own", GROUPS)
@pytest.mark.parametrize("rung", RUNGS.values(), ids=lambda rung: rung.name)
def test_refactor_task_has_one_heading_and_workspace(own: OwnershipGroup, rung: Rung) -> None:
    rendered = render_instruction(refactor_task_text(own, rung), "repository-agent")
    assert rendered.count("# Task\n\n") == 1
    assert rendered.count(REPOSITORY_AGENT_WORKSPACE) == 1


@pytest.mark.parametrize("own", GROUPS)
@pytest.mark.parametrize("concept", CONCEPTS, ids=lambda concept: concept.name)
def test_rename_task_has_one_heading_and_workspace(own: OwnershipGroup, concept: Concept) -> None:
    rendered = render_instruction(rename_task_text(read_raw_repository(), concept, own),
                                  "repository-agent")
    assert rendered.count("# Task\n\n") == 1
    assert rendered.count(REPOSITORY_AGENT_WORKSPACE) == 1
