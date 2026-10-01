"""Prepare and execute one DRY experiment run for a named governed profile.

    cd experiments && uv run python -m consistency_pilot.run_dry <profile> <store-dir> [scenario]

``scenario`` is ``v1`` (default: single-file value helpers), ``layered``
(route/view, domain-rule and cross-module fixtures) or ``dose`` (the layered
subjects with 0, 1, 3, 5, 7 or 10 of ten existing callers bypassing the
abstraction), ``placement`` (the bypassing callers clustered right above the
insertion point), ``chain`` (five successive additions per cell),
``context`` (the same subjects unpadded and padded to repositories of about
30 KB and 90 KB), ``codebase`` (eleven subjects set in snapshots of jig and
scout; correctness needs the image built from ``codebase_sandbox/``) or
``codebase-near`` (the same, with a neighbour function in the target module
that also inlines the helper in the inconsistent arm).

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
from assay.store import ObjectStore
from consistency_pilot.dry_experiment import (
    DryExperimentPrepared,
    DryExperimentSucceeded,
    dry_profiles,
    dry_runner,
    prepare_dry_experiment,
    run_dry_experiment,
)


def _summary(store: ObjectStore, report_ref: str) -> dict[str, object]:
    report = json.loads(store.read_bytes(report_ref))
    comparisons = report["comparisons"]
    summary: dict[str, object] = {
        comparisons[0]["reference"]: comparisons[0]["reference_distribution"]
    }
    for comparison in comparisons:
        summary[comparison["candidate"]] = {
            "distribution": comparison["candidate_distribution"],
            "n": comparison["n"],
            "ties": comparison["ties"],
            "improved": comparison["improved"],
            "regressed": comparison["regressed"],
            "p_value": comparison["p_value"],
            "decision": comparison["decision"],
        }
    summary["missingness"] = report["missingness"]
    summary["cost"] = report["costs"]["amounts"]
    return summary


async def main(profile: str, root: str, scenario: str = "v1") -> int:
    route, settings = dry_profiles(scenario)[profile]
    store = ObjectStore(root)
    factory = OpenRouterFactory(route)
    prepared = prepare_dry_experiment(
        store,
        factory=factory,
        settings=settings,
        runner=dry_runner(scenario),
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
        runner=dry_runner(scenario),
        allow_paid=True,
        export_destination=Path(f"{root}-run-1-bundles"),
        scenario=scenario,
    )
    print(profile, result, flush=True)
    if not isinstance(result, DryExperimentSucceeded):
        return 1
    for name, ref in (result.report_refs or {}).items():
        print(profile, name, json.dumps(_summary(store, ref)), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(*sys.argv[1:4])))
