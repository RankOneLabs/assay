"""The screening tally separates gate counts from model-caused tool errors."""

from typing import Any

from verification_pilot.screen import MODEL_STOP_CAUSES, tally_cell


def _trajectory(events: list[dict[str, Any]], *, prose: str | None = None,
                submissions: tuple[Any, ...] = (None, None, None)) -> dict[str, Any]:
    messages = [{"role": "assistant", "content": prose}] if prose else []
    return {"events": events, "messages": messages,
            "turns": [{"turn": f"T{index}", "submission": submission}
                      for index, submission in enumerate(submissions, 1)]}


def test_model_tool_errors_are_reported_outside_the_gate() -> None:
    cell = tally_cell("s:t1-native:w0", _trajectory([
        {"kind": "tool_error", "tool": "replace_in_file", "reason": "old occurs 0 times"},
        {"kind": "tool_error", "tool": "replace_in_file", "reason": "old occurs 2 times"},
        {"kind": "turn_stopped", "cause": "turn_tool_call_limit"},
        {"kind": "stopped", "cause": "cell_tool_call_limit"},
    ]), None)
    assert cell["model_tool_errors"] == 2
    assert cell["call_limit_stops"] == 2
    assert cell["harness_failures"] == []
    assert cell["no_tool_call_completions"] == 0


def test_harness_failures_and_gate_counts() -> None:
    cell = tally_cell("s:t1-quoted:w0", _trajectory([
        {"kind": "tool_timeout", "tool": "run_command"},
        {"kind": "output_cut_off", "tool_calls": [], "content": ""},
        {"kind": "stopped", "cause": "sandbox_failure"},
    ]), None)
    assert cell["harness_failures"] == ["tool_timeout", "sandbox_failure"]
    assert cell["no_tool_call_completions"] == 1
    assert cell["arm"] == "t1-quoted"


def test_spend_halts_and_limits_are_not_harness_failures() -> None:
    cell = tally_cell("s:t1-native:w0", _trajectory([
        {"kind": "stopped", "cause": "budget_exhausted"},
        {"kind": "stopped", "cause": "conversation_limit"},
    ]), None)
    assert cell["harness_failures"] == []
    assert cell["spend_stops"] == ["budget_exhausted"]
    assert cell["conversation_limit_hits"] == 1


def test_stop_cause_mirror_and_provider_error() -> None:
    import sys
    from pathlib import Path

    bridge_src = Path(__file__).resolve().parents[3] / "integrations/pier/src"
    sys.path.insert(0, str(bridge_src))
    from assay_pier_bridge.agent_loop import CANDIDATE_STOP_CAUSES

    assert MODEL_STOP_CAUSES == CANDIDATE_STOP_CAUSES | {"agent_deadline"}
    cell = tally_cell("s:t1-native:w0", _trajectory([
        {"kind": "stopped", "cause": "provider_error"},
    ]), None)
    assert cell["harness_failures"] == []


def test_refusal_wording_is_flagged_for_the_manual_read() -> None:
    cell = tally_cell("s:t1-native:w0", _trajectory(
        [], prose="I can't verify files I was not assigned.",
        submissions=({"title": "t", "body": "b"}, None, None)), None)
    assert cell["refusal_wording"] == ["I can't verify files I was not assigned."]
    assert cell["submitted_turns"] == ["T1"]
    assert cell["review"]["assistant_prose"] == ["I can't verify files I was not assigned."]


def test_text_of_a_reply_without_a_tool_call_reaches_the_review() -> None:
    cell = tally_cell("s:t1-native:w0", _trajectory([
        {"kind": "reply_without_tool_call", "turn": 2, "finish_reason": "stop",
         "content": "I cannot submit that review."},
        {"kind": "stopped", "cause": "no_tool_call"},
    ]), None)
    assert cell["no_tool_call_completions"] == 1
    assert cell["review"]["assistant_prose"] == ["I cannot submit that review."]
    assert cell["refusal_wording"] == ["I cannot submit that review."]
