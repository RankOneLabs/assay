from dataclasses import replace

from code_extension.fact_shapes.attempts import ToolCall
from code_extension.fact_shapes.mechanism import (
    holder_opened_with_read_file,
    holder_seen,
    miss_type,
)
from code_extension.fact_shapes.outcome import Held, Missed
from code_extension.tests.test_fact_shapes_outcome import sample


def test_discovery() -> None:
    attempt = sample()
    holder = attempt.variant.facts[0].holder
    for name, output, seen, opened in [
        ("read_file", " a   line\n b line", True, True),
        ("run_command", "src/x.ts:12: a line\nsrc/x.ts:13: b line", True, False),
        ("read_file", "a line", False, True),
        ("write_file", "a line b line", False, False),
        ("replace_in_file", "a line b line", False, False),
    ]:
        row = replace(
            attempt,
            calls=(ToolCall(name=name, arguments={"path": "./src/x.ts"}, returned_text=output),),
        )
        assert holder_seen(row, holder) == seen
        assert holder_opened_with_read_file(row, holder) == opened
    row = replace(
        attempt,
        calls=(
            ToolCall(name="submit_output"),
            ToolCall(
                name="read_file", arguments={"path": "src/x.ts"}, returned_text="a line b line"
            ),
        ),
    )
    assert not holder_seen(row, holder)
    assert not holder_opened_with_read_file(row, holder)


def test_miss_types() -> None:
    attempt = sample()
    holder = attempt.variant.facts[0].holder
    assert miss_type(attempt, holder, Missed()) == "never_touched"
    seen = replace(attempt, calls=(ToolCall(name="run_command", returned_text="a line b line"),))
    assert miss_type(seen, holder, Missed()) == "read_not_changed"
    edited = replace(attempt, patch="--- a/src/x.ts\n+++ b/src/x.ts\n-old\n+new")
    assert miss_type(edited, holder, Missed()) == "touched_but_wrong"
    assert miss_type(edited, holder, Held()) is None
