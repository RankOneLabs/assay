"""Prepare and execute one DRY experiment run for a named governed profile.

    cd experiments && uv run python -m consistency_pilot.run_dry <profile> <store-dir> [scenario]

``scenario`` is ``v1`` (default: single-file value helpers) or ``layered``
(route/view, domain-rule and cross-module fixtures).

Running this is the spending authorization: it approves the plan it just
prepared. Bundles are exported to ``<store-dir>-run-1-bundles``.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import paa_contracts

from assay.adapters.openrouter import OpenRouterFactory
from assay.investigations.correctness import DockerPythonRunner
from assay.store import ObjectStore
from consistency_pilot.dry_experiment import (
    DryExperimentPrepared,
    DryExperimentSucceeded,
    dry_profiles,
    prepare_dry_experiment,
    run_dry_experiment,
)


def _summary(store: ObjectStore, report_ref: str) -> dict[str, object]:
    report = json.loads(store.read_bytes(report_ref))
    comparison = report["comparisons"][0]
    return {
        "clean": comparison["candidate_distribution"],
        "inconsistent": comparison["reference_distribution"],
        "n": comparison["n"],
        "ties": comparison["ties"],
        "improved": comparison["improved"],
        "regressed": comparison["regressed"],
        "p_value": comparison["p_value"],
        "decision": comparison["decision"],
        "missingness": report["missingness"],
        "cost": report["costs"]["amounts"],
    }


async def main(profile: str, root: str, scenario: str = "v1") -> int:
    route, settings = dry_profiles(scenario)[profile]
    store = ObjectStore(root)
    factory = OpenRouterFactory(route)
    prepared = prepare_dry_experiment(
        store,
        factory=factory,
        settings=settings,
        runner=DockerPythonRunner(),
        schemas={
            name: paa_contracts.load_schema(name)
            for name in ("paa-task", "paa-evidence-record", "paa-operating-record")
        },
        scenario=scenario,
    )
    print(profile, prepared, flush=True)
    if not isinstance(prepared, DryExperimentPrepared):
        return 1
    result = await run_dry_experiment(
        store,
        plan_ref=prepared.plan_ref,
        authorization=prepared.plan_ref,
        factory=factory,
        runner=DockerPythonRunner(),
        allow_paid=True,
        export_destination=Path(f"{root}-run-1-bundles"),
        scenario=scenario,
    )
    print(profile, result, flush=True)
    if not isinstance(result, DryExperimentSucceeded):
        return 1
    for name, ref in (
        ("abstraction", result.abstraction_report_ref),
        ("correctness", result.correctness_report_ref),
    ):
        print(profile, name, json.dumps(_summary(store, ref)), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(*sys.argv[1:4])))
