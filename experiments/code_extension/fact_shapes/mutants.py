"""Pure two-replay mutant verdicts, using the study scoring parser.

Docker execution and evidence publication must supply retained outputs from two
fresh sandboxes; this module never substitutes invented outputs for a replay.
"""

from dataclasses import dataclass

from code_extension.fact_shapes.attempts import Fact, Group
from code_extension.fact_shapes.cells import FactId
from code_extension.fact_shapes.outcome import (
    _TITLE,
    Held,
    Missed,
    Scored,
    diagnostics,
    fact_titles,
    preflight_status,
)


@dataclass(frozen=True)
class Run:
    groups: dict[str, Group]
    preflight_cause: str | None = None
    typecheck_output: str = ""


@dataclass(frozen=True)
class Result:
    arm: str
    patch: str
    fact: FactId | None
    passed: bool
    reason: str


def verdict(
    arm: str,
    patch: str,
    facts: tuple[Fact, ...],
    runs: tuple[Run, ...],
    dropped: FactId | None = None,
) -> Result:
    """Accept exactly the declared omission twice, including holder-only preflight."""

    def refuse(reason: str, fact: FactId | None = dropped) -> Result:
        return Result(arm, patch, fact, False, reason)

    if len(runs) != 2:
        return refuse("exactly two fresh sandbox runs are required")
    if not facts or len({fact.id for fact in facts}) != len(facts):
        return refuse("facts must be nonempty and unique")
    if dropped is not None and dropped not in {fact.id for fact in facts}:
        return refuse("unknown dropped fact")
    signatures: list[tuple[tuple[str, str], ...]] = []
    for run in runs:
        if run.preflight_cause is not None:
            control = next(
                (f for f in facts if f.id == dropped and f.shape == "type_enforced"), None
            )
            errors = diagnostics(run.typecheck_output)
            if (
                control is None
                or not errors
                or any(e.file.removeprefix("./") not in control.holder.paths for e in errors)
            ):
                return refuse(
                    "preflight diagnostics must be confined to the dropped control holder"
                )
            status = preflight_status(run.preflight_cause, errors, facts)
            if not isinstance(status, Scored) or not isinstance(
                status.facts.get(control.id), Missed
            ):
                return refuse("preflight classifier did not identify the control miss")
            signatures.append(((str(control.id), "preflight_missed"),))
            continue
        for name in ("visible_regression", "hidden_regression"):
            group = run.groups.get(name)
            if group is None or group.status != "passed":
                return refuse(f"{name} did not pass")
        behavior = run.groups.get("new_behavior")
        if behavior is None or behavior.status not in {"passed", "failed"}:
            return refuse("new_behavior did not run")
        observed = _TITLE.findall(behavior.stdout + "\n" + behavior.stderr)
        for fact in facts:
            expected_status = "fail" if fact.id == dropped else "pass"
            for title in fact.titles:
                statuses = {status for status, name in observed if name == title}
                if statuses != {expected_status}:
                    return refuse("missing or conflicting fact title outcome", fact.id)
        outcomes = fact_titles(facts, behavior.stdout, behavior.stderr, ran=True)
        for fact in facts:
            expected = Missed if fact.id == dropped else Held
            if not isinstance(outcomes[fact.id], expected):
                return refuse("unexpected fact outcome", fact.id)
        if behavior.status != ("passed" if dropped is None else "failed"):
            return refuse("new_behavior group status disagrees with expected omission")
        signatures.append(tuple(sorted((str(key), value.kind) for key, value in outcomes.items())))
    if signatures[0] != signatures[1]:
        return refuse("fresh sandbox runs disagree")
    return Result(arm, patch, dropped, True, "both replays satisfy the expected fact outcomes")
