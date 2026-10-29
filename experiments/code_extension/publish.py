"""Render the committed extension report from retained evidence and ledgers."""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from assay.fixture_manifest import FixtureManifestV3
from assay.models import ExecutionPlanV3, StudySnapshot
from assay.store import ObjectStore
from code_extension.classification import operator_category
from code_extension.ledger import AttemptLedger, AttemptRow, build_ledger
from code_extension.metrics import SecondaryMeasures, measure_attempt

ROOT = Path(__file__).resolve().parent
REPORT_MD = ROOT / "REPORT.md"
FIXTURES = ROOT / "fixtures"
RUNS = ROOT / "evidence" / "runs"


class _Wire(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Judgment(_Wire):
    tag: Literal[
        "could_not_discover_relevant_code", "wrong_abstraction_or_plan",
        "missed_integration_point", "code_generation_defect", "invalid_verification_claim",
        "ambiguous_fixture",
    ]
    assigned_by: str
    trace_digest: str


class _RunIndex(_Wire):
    plan_ref: str
    manifest_ref: str
    judgments: dict[str, _Judgment]
    expected_change_paths: dict[str, tuple[str, ...]]


class _BridgePolicy(BaseModel):
    model_config = ConfigDict(extra="ignore")
    index_agent_readable: bool | None = None


@dataclass(frozen=True)
class ScenarioArm:
    subject_id: str
    arm_id: str


def committed_scenario_arms() -> tuple[ScenarioArm, ...]:
    """Read the committed, qualified scenario manifests; no roster is typed by hand."""
    rows: list[ScenarioArm] = []
    for path in sorted(FIXTURES.glob("*/qualification/manifest.json")):
        manifest = FixtureManifestV3.model_validate_json(path.read_bytes())
        for scenario in manifest.scenarios:
            for arm in scenario.arms:
                rows.append(ScenarioArm(scenario.subject_id, arm.arm_id))
    if len(set(rows)) != len(rows):
        raise ValueError("duplicate committed scenario/arm")
    return tuple(sorted(rows, key=lambda row: (row.subject_id, row.arm_id)))


def _fixture_trees() -> dict[ScenarioArm, Path]:
    trees: dict[ScenarioArm, Path] = {}
    for path in sorted(FIXTURES.glob("*/qualification/manifest.json")):
        manifest = FixtureManifestV3.model_validate_json(path.read_bytes())
        base = path.parent.parent / "repository"
        for scenario in manifest.scenarios:
            for arm in scenario.arms:
                tree = base / arm.arm_id if (base / arm.arm_id).is_dir() else base
                if not tree.is_dir():
                    raise ValueError(f"missing committed fixture tree: {tree}")
                trees[ScenarioArm(scenario.subject_id, arm.arm_id)] = tree
    return trees


def _committed_runs() -> tuple[
    tuple[AttemptLedger, ...], dict[str, SecondaryMeasures], dict[str, bool | None]
]:
    """Each run directory contains a small index and its content-addressed objects."""
    ledgers: list[AttemptLedger] = []
    secondary: dict[str, SecondaryMeasures] = {}
    policy: dict[str, bool | None] = {}
    trees = _fixture_trees()
    for index_path in sorted(RUNS.glob("*/run.json")):
        index = _RunIndex.model_validate_json(index_path.read_bytes())
        store = ObjectStore(index_path.parent)
        plan = ExecutionPlanV3.model_validate_json(store.read_bytes(index.plan_ref))
        snapshot = StudySnapshot.model_validate_json(store.read_bytes(plan.snapshot_ref))
        judgments = {
            cell: operator_category(
                judgment.tag, assigned_by=judgment.assigned_by,
                trace_digest=judgment.trace_digest,
            ) for cell, judgment in index.judgments.items()
        }
        ledger = build_ledger(
            plan=plan, manifest_ref=index.manifest_ref, store=store, judgments=judgments
        )
        ledgers.append(ledger)
        for arm in snapshot.arms:
            config_ref = arm.worker.get("configuration_ref")
            declared = (
                _BridgePolicy.model_validate_json(store.read_bytes(config_ref)).index_agent_readable
                if isinstance(config_ref, str) else None
            )
            if arm.id in policy and policy[arm.id] != declared:
                raise ValueError(f"conflicting index policy for arm {arm.id}")
            policy[arm.id] = declared
        for row in ledger.rows:
            tree = trees.get(ScenarioArm(row.subject_id, row.arm_id))
            if tree is None:
                raise ValueError(f"no committed fixture tree for {row.subject_id}/{row.arm_id}")
            if (
                row.reference.patch_ref is not None
                and row.subject_id not in index.expected_change_paths
            ):
                raise ValueError(f"missing declared expected paths for {row.subject_id}")
            secondary[row.attempt_key] = measure_attempt(
                row, store, fixture_tree=tree,
                expected_change_paths=frozenset(
                    index.expected_change_paths.get(row.subject_id, ())
                ),
            )
    return tuple(ledgers), secondary, policy


def _table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join(lines)


def render_from_ledgers(
    ledgers: Sequence[AttemptLedger], *,
    secondary: Mapping[str, SecondaryMeasures] | None = None,
    index_policy: Mapping[str, bool | None] | None = None,
) -> str:
    """Render counts from rows, including every incomplete and operational row."""
    rows = [row for ledger in ledgers for row in ledger.rows]
    ids = [(row.attempt_key, row.subject_id, row.arm_id) for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate attempt across ledgers")
    scenario_arms = sorted(set(committed_scenario_arms()) | {
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


def render() -> str:
    """Recompute the committed report from committed fixtures and run bundles."""
    ledgers, secondary, policy = _committed_runs()
    return render_from_ledgers(ledgers, secondary=secondary, index_policy=policy)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    value = render()
    if args.write:
        REPORT_MD.write_text(value, encoding="utf-8")
    else:
        print(value, end="")


if __name__ == "__main__":
    main()
