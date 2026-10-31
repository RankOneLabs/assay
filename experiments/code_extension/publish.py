"""Render the committed extension report from retained evidence and ledgers."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from assay.fixture_manifest import FixtureManifestV3
from assay.models import ExecutionPlanV3, StudySnapshot
from assay.store import ObjectStore
from code_extension.classification import operator_category
from code_extension.ledger import AttemptLedger, build_ledger
from code_extension.metrics import SecondaryMeasures, measure_attempt
from code_extension import report
from code_extension.report import ScenarioArm

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


def render_from_ledgers(
    ledgers: Sequence[AttemptLedger], *,
    secondary: Mapping[str, SecondaryMeasures] | None = None,
    index_policy: Mapping[str, bool | None] | None = None,
) -> str:
    return report.render_from_ledgers(
        ledgers, secondary=secondary, index_policy=index_policy,
        scenario_arms=committed_scenario_arms(),
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
