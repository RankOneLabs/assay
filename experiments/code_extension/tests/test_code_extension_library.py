"""The scenario library's committed assets regenerate from their declared edits."""

from __future__ import annotations

import pytest
from code_extension.fixture import PILOT
from code_extension.fixtures import load_scenario
from code_extension.library import (
    PATCHES,
    SLICES,
    SUBJECTS,
    TASKS,
    apply_edits,
    manifest_scope,
    render_patches,
)
from code_extension.reachability import adds_stage_code, feature_names
from code_extension.slice import LIBRARY_PIN


@pytest.mark.parametrize("scenario", sorted(PATCHES))
def test_committed_patches_are_exactly_the_declared_edits(scenario: str) -> None:
    directory = PILOT.parent / scenario / "patches"
    committed = {path.name: path.read_text(encoding="utf-8") for path in directory.glob("*.patch")}
    assert committed == render_patches(scenario)


@pytest.mark.parametrize("scenario", sorted(PATCHES))
def test_library_scenario_loads_with_every_held_patch(scenario: str) -> None:
    fixture = load_scenario(scenario)
    assert fixture.subject_id == SUBJECTS[scenario]
    assert len(fixture.arms[0].negative_patches) == len(PATCHES[scenario]) - 1


def test_an_edit_that_no_longer_matches_exactly_once_fails() -> None:
    with pytest.raises(ValueError, match="expected one"):
        apply_edits({"a.ts": "x x"}, (("a.ts", "x", "y"),))
    with pytest.raises(ValueError, match="expected one"):
        apply_edits({"a.ts": "x"}, (("a.ts", "z", "y"),))


@pytest.mark.parametrize("scenario", sorted(TASKS))
def test_every_held_negative_names_the_feature_so_none_reads_as_omitted(scenario: str) -> None:
    patches = render_patches(scenario)
    cell = f"{SUBJECTS[scenario]}:baseline:w0"
    assert feature_names(cell) == TASKS[scenario].feature_tokens
    for name, patch in patches.items():
        assert any(adds_stage_code(patch, token) for token in feature_names(cell)), name


def test_a_stage_task_cell_still_names_its_stage_type() -> None:
    assert feature_names("oakridge-dbos-stage-status-report:plugin:w0") == ("status_report",)


def test_manifest_scope_names_the_library_pin_and_pinned_sources() -> None:
    scenario = "worker-silence-bound"
    pin, included = manifest_scope(SUBJECTS[scenario]) or ("", ())
    assert pin == LIBRARY_PIN and len(pin) == 40
    assert included == tuple(sorted(SLICES[scenario].files))
    assert manifest_scope("oakridge-dbos-pointer-root") is None
