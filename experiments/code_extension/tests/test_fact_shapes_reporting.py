from dataclasses import replace

from code_extension.fact_shapes.cells import FactId
from code_extension.fact_shapes.outcome import Held, Missed, Scored, Stopped, Unscored, score
from code_extension.fact_shapes.reporting import (
    CompletionClaim,
    completion_claim,
    mirrored_state_count,
)
from code_extension.tests.test_fact_shapes_outcome import sample


def test_claims() -> None:
    missed = Scored({FactId("a"): Missed()})
    assert completion_claim(missed, "complete") == CompletionClaim(True, True, True)
    assert completion_claim(Scored({FactId("a"): Held()}), "complete") == CompletionClaim(
        True, False, False
    )
    for verdict in ("incomplete", "unsure", None):
        assert completion_claim(missed, verdict) == CompletionClaim(False, True, False)
    assert completion_claim(Stopped("wall_time"), "complete") is None
    assert completion_claim(Unscored("failure"), "complete") is None


def test_mirrors() -> None:
    patch = (
        "+++ b/x.ts\n+interface X { build_running: boolean }\n"
        "+ALTER TABLE x ADD COLUMN build_running INTEGER;\n"
        "+type BuildRunning = boolean;\n-build_running: boolean\n"
        " build_running: boolean\n+other: boolean"
    )
    assert mirrored_state_count(patch, ["buildRunning"]) == 3
    attempt = sample()
    existing_state = replace(attempt.variant.facts[0], shape="existing_state")
    attempt = replace(attempt, variant=replace(attempt.variant, facts=(existing_state,)))
    assert score(attempt) == score(replace(attempt, patch=patch))


def test_object_values_are_not_field_declarations() -> None:
    patch = "+const x = { build_running: true };\n const y = {\n+  build_running: true,\n };\n"
    assert mirrored_state_count(patch, ["buildRunning"]) == 0
