"""Pure per-fact scoring and terminal classification."""

import re
from dataclasses import dataclass
from typing import Literal

from code_extension.fact_shapes.attempts import Attempt, Fact
from code_extension.fact_shapes.attempts import replay_typecheck as replay_typecheck
from code_extension.fact_shapes.cells import FactId


@dataclass(frozen=True)
class Missed:
    kind: Literal["missed"] = "missed"


@dataclass(frozen=True)
class Held:
    kind: Literal["held"] = "held"


@dataclass(frozen=True)
class Unavailable:
    kind: Literal["unavailable"] = "unavailable"


type FactOutcome = Missed | Held | Unavailable


@dataclass(frozen=True)
class Scored:
    facts: dict[FactId, FactOutcome]
    kind: Literal["scored"] = "scored"


@dataclass(frozen=True)
class Unscored:
    reason: str
    kind: Literal["unscored"] = "unscored"


@dataclass(frozen=True)
class Stopped:
    stop_kind: Literal["request_limit", "output_token_limit", "wall_time", "request_timeout"]
    kind: Literal["stopped"] = "stopped"


type AttemptStatus = Scored | Unscored | Stopped
_TITLE = re.compile(r"^\((pass|fail)\) (.*?)(?: \[[\d.]+ms\])?$", re.MULTILINE)
_TS = re.compile(r"^(\S+\.ts)\(\d+,\d+\): error (TS\d+): (.*)$", re.MULTILINE)


@dataclass(frozen=True)
class Diagnostic:
    file: str
    code: str
    message: str


def diagnostics(output: str) -> tuple[Diagnostic, ...]:
    return tuple(Diagnostic(*match) for match in _TS.findall(output))


def fact_titles(
    facts: tuple[Fact, ...], stdout: str, stderr: str, *, ran: bool
) -> dict[FactId, FactOutcome]:
    titles = _TITLE.findall(stdout + "\n" + stderr)
    results: dict[FactId, FactOutcome] = {}
    for fact in facts:
        expected = set(fact.titles)
        passed = {
            t for status, t in titles if status == "pass" and t.startswith(f"fact:{fact.id}: ")
        }
        failed = {
            t for status, t in titles if status == "fail" and t.startswith(f"fact:{fact.id}: ")
        }
        if not ran:
            results[fact.id] = Unavailable()
        elif failed & expected or not expected or not expected <= passed:
            results[fact.id] = Missed()
        else:
            results[fact.id] = Held()
    return results


def preflight_status(
    cause: str, errors: tuple[Diagnostic, ...], facts: tuple[Fact, ...]
) -> Scored | Unscored:
    if not cause.startswith("typecheck_"):
        return Unscored(cause)
    controls = {
        f.id
        for f in facts
        if f.shape == "type_enforced"
        and any(e.file.removeprefix("./") in f.holder.paths for e in errors)
    }
    if controls:
        return Scored({f.id: Missed() if f.id in controls else Unavailable() for f in facts})
    if not errors:
        return Unscored("preflight_not_reproduced")
    return Unscored("; ".join(f"{e.file}: {e.code}: {e.message}" for e in errors))


def score(attempt: Attempt, replay_output: str | None = None) -> AttemptStatus:
    if attempt.request_timeout:
        return Stopped("request_timeout")
    if attempt.terminal in {"request_limit", "turn_limit"}:
        return Stopped("request_limit")
    if attempt.terminal == "output_token_limit":
        return Stopped("output_token_limit")
    if attempt.outcome == "timeout":
        return Stopped("wall_time")
    if attempt.outcome in {"harness_failure", "unsettled"}:
        return Unscored(attempt.terminal if attempt.terminal != "unknown" else attempt.outcome)
    if attempt.stop != "submitted":
        return Unscored(attempt.terminal)
    if attempt.evaluator is None or attempt.verdict is None:
        return Unscored("unevaluated")
    preflight = attempt.evaluator.preflight
    if preflight is None:
        return Unscored("preflight_unavailable")
    if preflight.status != "passed":
        cause = preflight.cause or "preflight_unavailable"
        if cause.startswith("typecheck_") and replay_output is None:
            return Unscored("preflight_replay_required")
        return preflight_status(cause, diagnostics(replay_output or ""), attempt.variant.facts)
    group = attempt.evaluator.groups.get("new_behavior")
    return Scored(
        fact_titles(
            attempt.variant.facts,
            group.stdout if group else "",
            group.stderr if group else "",
            ran=group is not None and group.status in {"passed", "failed"},
        )
    )
