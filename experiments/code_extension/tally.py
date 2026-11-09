"""Tally a frozen cohort per task and model, and apply the library study's decision rule.

The rule reads only mechanical outcomes, so review of failures cannot change it. See
`studies/scenario-library/study-plan.md`.

    uv run python -m code_extension.tally --store <store> --cohort <cohort.json>
"""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any

from code_extension.launch import FrozenCohort
from code_extension.library import SUBJECTS
from code_extension.reachability import plan_rows

REPEATS = 5
SHOWS_AT = 2  # reachability failures in one task and model pairing
RECURS_ON_TASKS = 3
RECURS_ACROSS_APPS = 2
READABLE_ATTEMPTS = 3  # attempts whose feature tests ran, per pairing
READABLE_TASKS = 5

CONTROLS = frozenset({
    SUBJECTS["worker-start-budget"], SUBJECTS["export-credential"],
})
NON_LOCAL = frozenset(SUBJECTS.values()) - CONTROLS
# Fixed before any attempt ran. They describe results and never enter the decision rule.
GROUPS: Mapping[str, frozenset[str]] = {
    "Runtime table or list": frozenset(SUBJECTS[name] for name in (
        "operations-route", "subject-only-build", "addressing-runner", "restricted-evidence",
    )),
    "Carried through layers": frozenset(SUBJECTS[name] for name in (
        "worker-silence-bound", "context-usage-inbox", "agent-default-model",
    )),
    "Protocol, order or second boundary": frozenset(SUBJECTS[name] for name in (
        "native-compaction-summary", "gated-review-shortcuts",
    )),
    "Control": CONTROLS,
}
COLUMNS = (
    "passed", "reachability", "omitted_stage", "semantic", "unattributed", "regression_only",
    "unusable_patch", "limit_stop", "timeout", "scope_or_integrity", "no_submission",
    "harness_failure", "unsettled",
)
FEATURE_TESTS_RAN = frozenset({
    "passed", "reachability", "omitted_stage", "semantic", "unattributed", "regression_only",
})

type Rows = Mapping[str, Iterable[Mapping[str, Any]]]  # model -> plan_rows
type Counts = dict[tuple[str, str], Counter[str]]  # (model, subject) -> outcome counts


def app(subject: str) -> str:
    """`oakridge-dbos-worker-silence-bound` belongs to `dbos`."""
    return subject.split("-")[1]


def subject_of(row: Mapping[str, Any]) -> str:
    return str(row["cell"]).split(":")[0]


def outcome_counts(rows: Rows) -> Counts:
    counts: Counts = {}
    for model, model_rows in rows.items():
        for row in model_rows:
            counts.setdefault((model, subject_of(row)), Counter())[row["outcome"]] += 1
    return counts


def shows_missed_integration(counts: Counts, model: str, subject: str) -> bool:
    return counts.get((model, subject), Counter())["reachability"] >= SHOWS_AT


def recurs(counts: Counts, model: str) -> bool:
    shown = [s for s in NON_LOCAL if shows_missed_integration(counts, model, s)]
    return len(shown) >= RECURS_ON_TASKS and len({app(s) for s in shown}) >= RECURS_ACROSS_APPS


def control_clean(counts: Counts, model: str) -> bool:
    return not any(shows_missed_integration(counts, model, s) for s in CONTROLS)


def readable(counts: Counts, model: str) -> bool:
    tasks = 0
    for subject in NON_LOCAL:
        pairing = counts.get((model, subject), Counter())
        if sum(pairing[name] for name in FEATURE_TESTS_RAN) >= READABLE_ATTEMPTS:
            tasks += 1
    return tasks >= READABLE_TASKS


@dataclass(frozen=True)
class Decision:
    result: str
    next_step: str


def decide(counts: Counts, models: Iterable[str]) -> Decision:
    """The first row of the plan's decision table that matches."""
    names = tuple(models)
    subjects = tuple(sorted(SUBJECTS.values()))
    pairings = [counts.get((m, s), Counter()) for m in names for s in subjects]
    settled = [p.total() - p["unsettled"] for p in pairings]
    if any(total < REPEATS for total in settled):
        return Decision("Incomplete", "Do not apply the rule. Review the plan's halt first.")
    if all(p["passed"] in (0, REPEATS) for p in pairings):
        return Decision("Floor or ceiling", "Stop and review, even if the rule is met.")
    if not any(readable(counts, m) for m in names):
        return Decision("No model is readable", "Stop and review.")
    recurring = [m for m in names if recurs(counts, m)]
    clean = [m for m in recurring if control_clean(counts, m)]
    if clean:
        return Decision(
            f"Recurs with a clean control: {', '.join(clean)}",
            "Review every counted failure, then plan a study of what hides the edit.",
        )
    if recurring:
        return Decision(
            f"Recurs without a clean control: {', '.join(recurring)}",
            "Review. The failures are not specific to non-local edits.",
        )
    if any(shows_missed_integration(counts, m, s) for m in names for s in NON_LOCAL):
        return Decision(
            "Some non-local tasks show missed integration",
            "Review those tasks before committing to anything further.",
        )
    return Decision(
        "No non-local task shows missed integration",
        "Stop and review. Report the combined count with the matched-task study.",
    )


def _row(cells: Iterable[object]) -> str:
    return "| " + " | ".join(str(cell) for cell in cells) + " |"


def outcome_table(rows: Rows) -> str:
    """One line per task and model pairing, with mean requests."""
    counts = outcome_counts(rows)
    lines = [_row(("Model", "Task", *COLUMNS, "Mean requests")),
             _row(("---", "---", *("---:" for _ in COLUMNS), "---:"))]
    for model, model_rows in rows.items():
        kept = list(model_rows)
        for subject in sorted({subject_of(row) for row in kept}):
            requests = [row["requests"] for row in kept if subject_of(row) == subject]
            pairing = counts[(model, subject)]
            lines.append(_row((model, subject, *(pairing[name] for name in COLUMNS),
                               f"{mean(requests):.1f}")))
    return "\n".join(lines)


def group_table(rows: Rows) -> str:
    """Reachability failures by what hides the edit. Descriptive only."""
    counts = outcome_counts(rows)
    lines = [_row(("Group", *rows)), _row(("---", *("---:" for _ in rows)))]
    for group, subjects in GROUPS.items():
        lines.append(_row((group, *(
            sum(counts.get((model, s), Counter())["reachability"] for s in subjects)
            for model in rows
        ))))
    return "\n".join(lines)


def cohort_rows(store: Path, cohort: Path) -> dict[str, list[dict[str, Any]]]:
    frozen = FrozenCohort.model_validate_json(cohort.read_bytes())
    return {plan.name: plan_rows(store, plan.plan_digest) for plan in frozen.plans}


def main() -> None:
    parser = argparse.ArgumentParser(prog="code_extension.tally", description=__doc__)
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--cohort", type=Path, required=True)
    args = parser.parse_args()
    rows = cohort_rows(args.store, args.cohort)
    decision = decide(outcome_counts(rows), rows)
    print(f"{outcome_table(rows)}\n\n{group_table(rows)}\n")
    print(f"Decision: {decision.result}\nNext: {decision.next_step}")


if __name__ == "__main__":
    main()
