"""Pure transforms for the extension attempt ledger and report."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from code_extension.ledger import AttemptLedger, AttemptRow
from code_extension.metrics import SecondaryMeasures

@dataclass(frozen=True)
class ScenarioArm:
    subject_id: str
    arm_id: str

def _table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join(lines)


def render_from_ledgers(
    ledgers: Sequence[AttemptLedger], *,
    secondary: Mapping[str, SecondaryMeasures] | None = None,
    index_policy: Mapping[str, bool | None] | None = None,
    scenario_arms: Sequence[ScenarioArm] = (),
) -> str:
    """Render counts from rows, including every incomplete and operational row."""
    rows = [row for ledger in ledgers for row in ledger.rows]
    ids = [(row.attempt_key, row.subject_id, row.arm_id) for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate attempt across ledgers")
    scenario_arms = sorted(set(scenario_arms) | {
        ScenarioArm(row.subject_id, row.arm_id) for row in rows
    }, key=lambda item: (item.subject_id, item.arm_id))
    subjects = {item.subject_id for item in scenario_arms}
    arms = {item.arm_id for item in scenario_arms}
    by_subject = {
        subject: [row for row in rows if row.subject_id == subject]
        for subject in subjects
    }
    by_arm = {arm: [row for row in rows if row.arm_id == arm] for arm in arms}
    common: set[tuple[int, str]] = set()
    for index, ledger in enumerate(ledgers):
        run_arms = {row.arm_id for row in ledger.rows}
        if len(run_arms) >= 2:
            subjects_in_every_arm = set.intersection(*(
                {row.subject_id for row in ledger.rows if row.arm_id == arm}
                for arm in sorted(run_arms)
            ))
            common.update((index, subject) for subject in subjects_in_every_arm)
    measures = secondary or {}
    policy = index_policy or {}
    if any(
        dict(measures[row.attempt_key].tool_usage).get("codeintel_query", 0) > 0
        and policy.get(row.arm_id) is None
        for row in rows if row.attempt_key in measures
    ):
        raise ValueError("index use requires the run's declared index_agent_readable policy")

    def counts(cells: Sequence[AttemptRow]) -> tuple[str, str, str]:
        return (
            str(sum(row.attempted for row in cells)),
            str(sum(row.completed for row in cells)),
            str(sum(row.passed for row in cells)),
        )

    lines = [
        "# Code extension study report",
        "",
        "Generated from committed fixture manifests and retained run evidence. "
        "The fixture roster is qualified; no extension run bundle is committed "
        "when the attempt counts below are empty.",
        "",
        "## Implementation success",
        "",
        f"Common subjects with an attempt in every arm of a multi-arm run: {len(common)}. "
        + ("Descriptive only; no inferential statistics are calculated."
           if len(common) < 10 else "Paired inference is eligible but not calculated here."),
        "",
        _table(("Scope", "Attempted", "Completed", "Passed"), [
            ("All attempts", *counts(rows)),
        ]),
        "",
        "Per-scenario counts:",
        "",
        _table(("Scenario", "Attempted", "Completed", "Passed"), [
            (subject, *counts(by_subject[subject])) for subject in sorted(subjects)
        ]),
        "",
        "Per-arm counts:",
        "",
        _table(("Arm", "Attempted", "Completed", "Passed"), [
            (arm, *counts(by_arm[arm])) for arm in sorted(arms)
        ]),
        "",
        "Scenario/arm cells, including cells with no completed attempt:",
        "",
        _table(("Scenario", "Arm", "Attempted", "Completed", "Passed"), [
            (
                item.subject_id, item.arm_id,
                *counts([row for row in rows if row.subject_id == item.subject_id
                         and row.arm_id == item.arm_id]),
            ) for item in scenario_arms
        ]),
        "",
        "## Verification behavior",
        "",
        "Agent self-assessment is shown only beside the independent evaluator verdict. "
        "An unavailable verdict remains unavailable.",
        "",
        _table(("Attempt", "Agent assessment", "External verdict", "Agreement"), [
            (
                row.attempt_key,
                measures[row.attempt_key].self_assessed_verdict or "unavailable"
                if row.attempt_key in measures else "unavailable",
                row.verdict.value if row.verdict else "unavailable",
                (
                    "yes" if measures[row.attempt_key].self_report_agrees else "no"
                ) if (
                    row.attempt_key in measures
                    and measures[row.attempt_key].self_report_agrees is not None
                )
                else "unavailable",
            ) for row in rows
        ]),
        "",
        "Declared `index_agent_readable` is operator policy, not an enforced access boundary. "
        "Index use is interpreted beside that declared policy:",
        "",
        _table(("Arm", "index_agent_readable", "Index queries"), [
            (
                arm,
                "true" if policy.get(arm) is True else "false" if policy.get(arm) is False
                else "undeclared",
                (
                    "unavailable" if any(
                        row.attempt_key not in measures
                        or not measures[row.attempt_key].trace_available
                        for row in by_arm[arm]
                    ) else str(sum(
                        dict(measures[row.attempt_key].tool_usage).get("codeintel_query", 0)
                        for row in by_arm[arm]
                    ))
                ),
            ) for arm in sorted(arms)
        ]),
        "",
        "## Operational failures",
        "",
        _table(("Category", "Attempts"), [
            (tag, str(count)) for tag, count in sorted(Counter(
                row.category.tag for row in rows if row.category is not None
            ).items())
        ]),
        "",
        "Cost coverage is reported separately from implementation effects. "
        "Unpriced local usage is never treated as zero cost or ranked against priced usage.",
        "",
        _table(("Arm", "Priced", "Unavailable", "Uncertain", "Observed cost"), [
            (
                arm,
                str(sum(row.accounting.coverage in ("measured", "estimated", "mixed")
                        for row in by_arm[arm])),
                str(sum(row.accounting.coverage == "unavailable" for row in by_arm[arm])),
                str(sum(row.accounting.coverage == "uncertain" for row in by_arm[arm])),
                _observed_cost(by_arm[arm]),
            ) for arm in sorted(arms)
        ]),
        "",
        "## Secondary measures",
        "",
        "Scope of diff and unnecessary changed paths come from offline `assay code-metrics` "
        "comparison of the committed fixture tree with the patched tree. "
        "The expected path set is declared per task; an unmeasured path count stays unavailable.",
        "",
        _table((
            "Attempt", "Changed paths", "Unnecessary paths", "Duration s", "Prompt tokens",
            "Completion tokens", "Tool calls", "Files inspected", "Retries",
        ), [
            _secondary_row(row, measures.get(row.attempt_key)) for row in rows
        ]),
        "",
        "## Interpretation",
        "",
        "Describe code-shape effects separately from scenario difficulty, verification behavior, "
        "and operational failures. The fixture roster alone supplies no implementation effect.",
        "",
    ]
    return "\n".join(lines)


def _observed_cost(rows: Sequence[AttemptRow]) -> str:
    amounts = [row.accounting.amount for row in rows if row.accounting.amount is not None]
    if not amounts:
        return "unpriced"
    currencies = {row.accounting.currency for row in rows if row.accounting.amount is not None}
    if len(currencies) != 1:
        return "mixed currencies"
    currency = next(iter(currencies))
    coverage = "partial " if len(amounts) != len(rows) else ""
    return f"{coverage}{sum(amounts):.4f} {currency}"


def _secondary_row(row: AttemptRow, measures: SecondaryMeasures | None) -> tuple[str, ...]:
    if measures is None:
        return (row.attempt_key, *("unavailable",) * 8)
    diff = measures.diff
    return (
        row.attempt_key,
        str(len(diff.changed_paths)) if diff else "unavailable",
        str(len(diff.unnecessary_paths)) if diff else "unavailable",
        str(measures.duration_seconds) if measures.duration_seconds is not None else "unavailable",
        str(measures.prompt_tokens) if measures.prompt_tokens is not None else "unavailable",
        str(measures.completion_tokens) if measures.completion_tokens is not None
        else "unavailable",
        str(sum(count for _, count in measures.tool_usage))
        if measures.trace_available else "unavailable",
        str(len(measures.files_inspected)) if measures.trace_available else "unavailable",
        str(measures.retries) if measures.trace_available else "unavailable",
    )


