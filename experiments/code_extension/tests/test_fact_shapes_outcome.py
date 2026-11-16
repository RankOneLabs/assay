from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

import pytest
from code_extension.fact_shapes.attempts import (
    Attempt,
    Evaluator,
    Fact,
    Group,
    HolderSpec,
    Ok,
    Preflight,
    Submission,
    ToolCall,
    Trajectory,
    Turn,
    Variant,
    VariantId,
    assemble,
    replay_typecheck,
)
from code_extension.fact_shapes.cells import FactId, RepositoryPath
from code_extension.fact_shapes.outcome import (
    Held,
    Missed,
    Scored,
    Stopped,
    Unavailable,
    Unscored,
    diagnostics,
    fact_titles,
    preflight_status,
    score,
)


def sample() -> Attempt:
    facts = (
        Fact(
            FactId("a"),
            ("fact:a: accepts",),
            "type_enforced",
            HolderSpec((RepositoryPath("src/x.ts"),), ("a line", "b line")),
        ),
        Fact(
            FactId("b"),
            ("fact:b: accepts",),
            "reference",
            HolderSpec((RepositoryPath("src/y.ts"),), ("other",)),
        ),
    )
    return assemble(
        {
            "cell": "cell",
            "stop": "submitted",
            "terminal": "normal_submission",
            "verdict": "incorrect",
            "outcome": "semantic",
        },
        Variant(VariantId("v"), facts),
        Evaluator(
            groups={
                "new_behavior": Group(
                    status="failed", stdout="(fail) fact:a: accepts\n(pass) fact:b: accepts [1.5ms]"
                )
            },
            preflight=Preflight(status="passed"),
        ),
        "",
        Trajectory(),
        "sha256:pinned",
    )


def test_assembly() -> None:
    attempt = sample()
    trajectory = Trajectory(
        turns=(
            Turn(
                tool_calls=(
                    ToolCall(
                        name="read_file", arguments={"path": "src/x.ts"}, returned_text="text"
                    ),
                    ToolCall(name="submit_output"),
                    ToolCall(name="run_command"),
                ),
                submission=Submission(self_assessed_verdict="complete"),
            ),
            Turn(tool_calls=(ToolCall(name="write_file"),)),
        )
    )
    assembled = assemble(
        {
            "cell": "cell",
            "stop": "submitted",
            "terminal": "normal_submission",
            "verdict": "incorrect",
            "outcome": "semantic",
        },
        attempt.variant,
        attempt.evaluator,
        "patch",
        trajectory,
        attempt.image_digest,
    )
    assert assembled.cell == "cell"
    assert assembled.stop == "submitted"
    assert assembled.terminal == "normal_submission"
    assert assembled.verdict == "incorrect"
    assert assembled.outcome == "semantic"
    assert assembled.evaluator == attempt.evaluator
    assert assembled.request_timeout is False
    assert assembled.calls == (trajectory.turns[0].tool_calls[0],)
    assert assembled.self_assessed_verdict == "complete"
    assert assembled.patch == "patch"
    assert assembled.variant == attempt.variant
    assert assembled.image_digest == "sha256:pinned"


def test_titles() -> None:
    facts = sample().variant.facts
    assert fact_titles(
        facts, "(pass) fact:a: accepts [2ms]", "(pass) fact:b: accepts", ran=True
    ) == {FactId("a"): Held(), FactId("b"): Held()}
    assert fact_titles(facts, "(fail) fact:a: accepts\n(pass) fact:b: accepts", "", ran=True) == {
        FactId("a"): Missed(),
        FactId("b"): Held(),
    }
    assert fact_titles(facts, "(pass) unrelated", "", ran=True) == {
        FactId("a"): Missed(),
        FactId("b"): Missed(),
    }
    assert all(isinstance(x, Unavailable) for x in fact_titles(facts, "", "", ran=False).values())


@pytest.mark.parametrize(
    ("terminal", "outcome", "expected"),
    [
        ("request_limit", "limit_stop", Stopped("request_limit")),
        ("turn_limit", "limit_stop", Stopped("request_limit")),
        ("output_token_limit", "limit_stop", Stopped("output_token_limit")),
        ("wall_limit", "timeout", Stopped("wall_time")),
        ("conversation_limit", "no_submission", Unscored("conversation_limit")),
        ("unknown", "harness_failure", Unscored("harness_failure")),
    ],
)
def test_terminals(terminal: str, outcome: str, expected: Stopped | Unscored) -> None:
    assert (
        score(replace(sample(), stop="no_submission", terminal=terminal, outcome=outcome))
        == expected
    )


def test_score() -> None:
    assert score(sample()) == Scored({FactId("a"): Missed(), FactId("b"): Held()})
    assert score(replace(sample(), request_timeout=True)) == Stopped("request_timeout")
    trace = Trajectory.model_validate(
        {"events": [{"kind": "stopped", "cause": "transport_failure", "error": "ReadTimeout"}]}
    )
    row = assemble(
        {"cell": "c", "stop": "failed", "terminal": "unknown", "outcome": "harness_failure"},
        sample().variant,
        None,
        "",
        trace,
        "digest",
    )
    assert score(row) == Stopped("request_timeout")


def test_preflight() -> None:
    facts = sample().variant.facts
    errors = diagnostics("src/x.ts(1,2): error TS123: wrong\nsrc/z.ts(2,3): error TS456: other")
    assert len(errors) == 2
    assert preflight_status("typecheck_nonzero_exit", errors, facts) == Scored(
        {FactId("a"): Missed(), FactId("b"): Unavailable()}
    )
    assert preflight_status("typecheck_nonzero_exit", errors[:1], facts) == Scored(
        {FactId("a"): Missed(), FactId("b"): Unavailable()}
    )
    other = preflight_status("typecheck_nonzero_exit", errors[1:], facts)
    assert isinstance(other, Unscored) and "TS456" in other.reason
    assert preflight_status("typecheck_nonzero_exit", (), facts) == Unscored(
        "preflight_not_reproduced"
    )


@pytest.mark.parametrize(
    "cause", ["typecheck_nonzero_exit", "build_nonzero_exit", "patch_rejected"]
)
def test_replay(cause: str) -> None:
    calls: list[tuple[str, tuple[str, ...]]] = []

    def runner(image: str, root: Path, command: Sequence[str]) -> str:
        assert (root / "src/x.ts").read_text() == "original"
        calls.append((image, tuple(command)))
        return "diagnostic"

    attempt = replace(
        sample(), evaluator=Evaluator(groups={}, preflight=Preflight(status="failed", cause=cause))
    )
    result = replay_typecheck(attempt, {"src/x.ts": "original"}, runner)
    assert isinstance(result, Ok)
    if cause.startswith("typecheck_"):
        assert calls == [("sha256:pinned", ("tsc", "--noEmit", "-p", "tsconfig.json"))]
    else:
        assert calls == []
        assert score(attempt) == Unscored(cause)


def test_multiple_declared_titles() -> None:
    fact = replace(sample().variant.facts[0], titles=("fact:a: first", "fact:a: second"))
    output = "(pass) fact:a: first\n(fail) fact:a: second [4ms]\n(pass) unrelated"
    assert fact_titles((fact,), output, "", ran=True)[fact.id] == Missed()
    assert fact_titles((fact,), "(pass) fact:a: first", "", ran=True)[fact.id] == Missed()


def test_parse_error_is_result(tmp_path: Path) -> None:
    from code_extension.fact_shapes.attempts import Err, read_attempts

    result = read_attempts(tmp_path, "invalid-plan", {})
    assert isinstance(result, Err)
    assert result.error.operation == "plan_rows"
    assert result.error.detail


def test_non_timeout_transport_error() -> None:
    trajectory = Trajectory.model_validate(
        {
            "events": [
                {"kind": "stopped", "cause": "transport_failure", "error": "ConnectError"},
            ]
        }
    )
    attempt = assemble(
        {"cell": "c", "stop": "failed", "terminal": "unknown", "outcome": "harness_failure"},
        sample().variant,
        None,
        "",
        trajectory,
        "digest",
    )
    assert score(attempt) == Unscored("harness_failure")


def test_replay_applies_patch(tmp_path: Path) -> None:
    from code_extension.fact_shapes.attempts import Err

    attempt = replace(
        sample(),
        evaluator=Evaluator(
            groups={}, preflight=Preflight(status="failed", cause="typecheck_nonzero_exit")
        ),
        patch="diff --git a/x.ts b/x.ts\n--- a/x.ts\n+++ b/x.ts\n@@ -1 +1 @@\n-old\n+candidate\n",
    )

    def runner(image: str, root: Path, command: Sequence[str]) -> str:
        assert (root / "x.ts").read_text() == "candidate\n"
        return "x.ts(1,1): error TS123: retained candidate"

    result = replay_typecheck(attempt, {"x.ts": "old\n"}, runner)
    assert isinstance(result, Ok) and result.value is not None
    assert len(diagnostics(result.value)) == 1
    failed = replay_typecheck(replace(attempt, patch="invalid patch"), {}, runner)
    assert isinstance(failed, Err) and failed.error.operation == "replay_typecheck"


def test_undeclared_failure_with_fact_prefix() -> None:
    facts = sample().variant.facts
    stdout = "(pass) fact:a: accepts\n(pass) fact:b: accepts"
    stderr = "(fail) fact:a: unexpected regression [2ms]"
    assert fact_titles(facts, stdout, stderr, ran=True) == {
        FactId("a"): Missed(),
        FactId("b"): Held(),
    }
