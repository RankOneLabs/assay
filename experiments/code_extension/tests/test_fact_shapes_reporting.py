from dataclasses import replace

import pytest
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


@pytest.mark.parametrize(
    "source",
    [
        "return { build_running: x };",
        "f(a, build_running: boolean)",
        "return {\n  build_running: x,\n};",
        "f({ build_running: x });",
        "function f(build_running: boolean) {}",
        "interface X { f(build_running: boolean): void; }",
    ],
)
def test_non_member_colons(source: str) -> None:
    patch = "\n".join("+" + line for line in source.splitlines())
    assert mirrored_state_count(patch, ["buildRunning"]) == 0


def test_type_body_context_and_members() -> None:
    patch = (
        "@@ -1,3 +1,4 @@\n interface X {\n+  build_running: boolean;\n }\n"
        "+export type Y = { build_running: boolean };\n"
        "+type BuildRunning = { other: boolean };\n"
        "+type Z = { method(build_running: boolean): void; build_running: boolean };\n"
    )
    assert mirrored_state_count(patch, ["buildRunning"]) == 4


def test_migration_columns() -> None:
    patch = (
        "+CREATE TABLE builds (\n+  id INTEGER PRIMARY KEY,\n"
        "+  build_running INTEGER,\n+  other TEXT\n+);\n"
        "+ALTER TABLE builds ADD build_running INTEGER;\n"
        "+CREATE TABLE other (build_running INTEGER);\n"
        " CREATE TABLE existing (\n+  build_running INTEGER\n );\n"
    )
    assert mirrored_state_count(patch, ["buildRunning"]) == 4


@pytest.mark.parametrize(
    "source",
    [
        "type X = { nested: { build_running: boolean } };",
        "interface X\n{\n build_running: boolean\n}",
        "type X =\n{ nested: {\n build_running: boolean\n} };",
    ],
)
def test_nested_and_multiline_type_bodies(source: str) -> None:
    patch = "\n".join("+" + line for line in source.splitlines())
    assert mirrored_state_count(patch, ["buildRunning"]) == 1


@pytest.mark.parametrize(
    "source",
    [
        'const note = "type X = { build_running: boolean }";',
        "const note = 'interface X { build_running: boolean }';",
        "const note = `interface X {\n build_running: boolean\n}`;",
        "/* type X = { build_running: boolean }; */",
        "/*\n interface X {\n build_running: boolean\n}\n*/",
        "// interface X { build_running: boolean }",
        "-- CREATE TABLE x (build_running INTEGER);",
    ],
)
def test_text_and_comments_are_not_declarations(source: str) -> None:
    patch = "\n".join("+" + line for line in source.splitlines())
    assert mirrored_state_count(patch, ["buildRunning"]) == 0


def test_quoted_members_and_comment_context() -> None:
    patch = (
        " /* existing comment\n+interface Fake { build_running: boolean }\n */\n"
        '+interface Real { "build_running": boolean; }\n'
        "+interface Header /* { build_running: boolean } */\n+{\n+ build_running: boolean;\n+}\n"
        '+CREATE TABLE x ("build_running" INTEGER);\n'
        '+const note = "escaped \\" type X = { build_running: boolean }";\n'
    )
    assert mirrored_state_count(patch, ["buildRunning"]) == 3
