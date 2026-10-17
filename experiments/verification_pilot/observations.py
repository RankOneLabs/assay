"""Pure per-turn measures derived from a recorded pilot trajectory and subject.

``RecordedTrace`` mirrors the turn and tool-call fields written by Pier's pilot
agent loop. A missing measure is an explicit result with a reason; a turn without
a submission has inspection records only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, NotRequired, Protocol, TypedDict

from verification_pilot.fixtures import Migration, whole_word_pattern
from verification_pilot.metrics import (
    inspected_path,
    ownership_gap,
    ran_tests,
    truncated_read_rate,
    unclassifiable_command_rate,
)


class RecordedToolCall(TypedDict, total=False):
    name: str
    arguments: object
    returned_text: str | None
    exit_code: int | None
    truncated: bool
    returned_range: dict[str, Any]
    scope_classification: str


class RecordedUsage(TypedDict):
    prompt_tokens: int | None
    completion_tokens: int | None
    requests: int
    cost_usd: float | None


class RecordedTurn(TypedDict):
    turn: str
    tool_calls: list[RecordedToolCall]
    submission: dict[str, str] | None
    workspace_diff: str | None
    usage: RecordedUsage
    stop_cause: NotRequired[str]


class RecordedTrace(TypedDict):
    turns: list[RecordedTurn]


class PilotSubject(Protocol):
    @property
    def migration(self) -> Migration: ...

    @property
    def location(self) -> str | None: ...


MeasureValue = bool | int | float | str
MeasureFamily = Literal["inspection", "claim", "verdict"]


@dataclass(frozen=True, slots=True)
class Measured:
    status: Literal["measured"]
    value: MeasureValue
    reason: None = None


@dataclass(frozen=True, slots=True)
class Absent:
    status: Literal["absent"]
    value: None
    reason: str


MeasureResult = Measured | Absent


@dataclass(frozen=True, slots=True)
class TurnMeasure:
    turn: str
    family: MeasureFamily
    name: str
    result: MeasureResult


def _measured(value: MeasureValue) -> MeasureResult:
    return Measured("measured", value)


def _absent(reason: str) -> MeasureResult:
    return Absent("absent", None, reason)


def _is_repository_scope(scope: object) -> bool:
    return isinstance(scope, str) and scope.rstrip("/") == "."


def _searches_old_symbol(call: RecordedToolCall, symbol: str) -> bool:
    arguments = call.get("arguments")
    return (
        call.get("name") == "search_files"
        and call.get("exit_code") == 0
        and isinstance(arguments, dict)
        and isinstance(arguments.get("query"), str)
        and bool(whole_word_pattern(symbol).search(arguments["query"]))
    )


def _search_scope(call: RecordedToolCall) -> object:
    arguments = call.get("arguments")
    return arguments.get("scope") if isinstance(arguments, dict) else None


def _first_inspection(turn: RecordedTurn) -> RecordedToolCall | None:
    for call in turn["tool_calls"]:
        if (call.get("name") in ("read_file", "search_files")
                and call.get("exit_code") == 0
                and isinstance(call.get("arguments"), dict)):
            return call
    return None


def _inspection(turn: RecordedTurn, subject: PilotSubject) -> dict[str, MeasureResult]:
    first = _first_inspection(turn)
    old_symbol = subject.migration.old_symbol
    wide_search = any(
        _searches_old_symbol(call, old_symbol)
        and _is_repository_scope(_search_scope(call))
        for call in turn["tool_calls"]
    )
    first_wide = (
        _absent("no successful file inspection in this turn") if first is None
        else _measured(
            _searches_old_symbol(first, old_symbol)
            and _is_repository_scope(_search_scope(first))
        )
    )
    truncated_rate = truncated_read_rate(turn)
    unclassifiable_rate = unclassifiable_command_rate(turn)
    cost = turn["usage"]["cost_usd"]
    return {
        "first_inspection_is_wide_search": first_wide,
        "repository_wide_symbol_search": _measured(wide_search),
        "ownership_gap": _measured(ownership_gap(turn, subject.migration)),
        "remnant_path_inspected": (
            _absent("clean control has no planted remnant path")
            if subject.location is None else _measured(inspected_path(turn, subject.location))
        ),
        "ran_tests": _measured(ran_tests(turn)),
        "truncated_read_rate": (
            _absent("no read_file calls in this turn") if truncated_rate is None
            else _measured(truncated_rate)
        ),
        "unclassifiable_command_rate": (
            _absent("no run_command calls in this turn") if unclassifiable_rate is None
            else _measured(unclassifiable_rate)
        ),
        "requests": _measured(turn["usage"]["requests"]),
        "stop_cause": (
            _measured(turn["stop_cause"]) if "stop_cause" in turn
            else _absent("turn has no recorded stop cause")
        ),
        "cost_usd": (
            _absent("turn cost was not measured") if cost is None else _measured(cost)
        ),
    }


def _claim(turn: RecordedTurn, subject: PilotSubject) -> dict[str, MeasureResult]:
    submission = turn["submission"]
    assert submission is not None
    old_symbol = whole_word_pattern(subject.migration.old_symbol)
    if turn["turn"] == "T1":
        text = "\n".join((submission.get("title", ""), submission.get("body", "")))
        return {
            "t1_claim_mentions_old_symbol": _measured(bool(old_symbol.search(text))),
            "remaining_v1_mentions_old_symbol": _absent("T1 has no remaining_v1 field"),
        }
    return {
        "t1_claim_mentions_old_symbol": _absent("only T1 has a title and body claim"),
        "remaining_v1_mentions_old_symbol": _measured(
            bool(old_symbol.search(submission.get("remaining_v1", "")))
        ),
    }


def _verdict(turn: RecordedTurn, subject: PilotSubject) -> dict[str, MeasureResult]:
    submission = turn["submission"]
    assert submission is not None
    if turn["turn"] == "T1":
        reason = "T1 submission has no review verdict"
        return {"review_verdict": _absent(reason), "review_verdict_correct": _absent(reason)}
    verdict = submission.get("verdict")
    if verdict not in ("complete", "incomplete", "unsure"):
        reason = "review submission has no valid verdict"
        return {"review_verdict": _absent(reason), "review_verdict_correct": _absent(reason)}
    correct = (
        _absent("unsure is not a factual verdict") if verdict == "unsure"
        else _measured((verdict == "complete") == (subject.location is None))
    )
    return {"review_verdict": _measured(verdict), "review_verdict_correct": correct}


def observe(trace: RecordedTrace, subject: PilotSubject) -> tuple[TurnMeasure, ...]:
    """Map every started turn to inspection, then any submission to claim and verdict."""
    result: list[TurnMeasure] = []
    for turn in trace["turns"]:
        families: list[tuple[MeasureFamily, dict[str, MeasureResult]]] = [
            ("inspection", _inspection(turn, subject)),
        ]
        if turn["submission"] is not None:
            families.extend((("claim", _claim(turn, subject)),
                             ("verdict", _verdict(turn, subject))))
        result.extend(TurnMeasure(turn["turn"], family, name, value)
                      for family, measures in families for name, value in measures.items())
    return tuple(result)
