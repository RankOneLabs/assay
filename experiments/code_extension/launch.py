"""Run a frozen cohort of plans in order, one at a time, under one combined cap.

The launcher never invents, retries or resumes a cell. Each plan's journal says
where it stands, so a second launch skips finished plans and refuses a partial
one. An operator continues that plan with `code_extension.resume`, then launches
again for whatever follows it.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from assay.canonical import canonical_json, digest_bytes
from assay.store import ObjectStore
from code_extension.budget import AttemptJournal
from code_extension.config import RunConfiguration
from code_extension.run import LaunchRefused, _build, _plan_dir, execute, prepare
from code_extension.status import plan_state

SCHEMA: Literal["assay-extension-cohort/0.1.0"] = "assay-extension-cohort/0.1.0"


class _Wire(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PlanRequest(_Wire):
    name: str = Field(min_length=1)
    config: Path


class CohortRequest(_Wire):
    """Operator input; paths are relative to the file that names them."""

    cohort: str = Field(min_length=1)
    combined_cap_usd: Decimal = Field(gt=0)
    plans: tuple[PlanRequest, ...] = Field(min_length=1)


class FrozenPlan(_Wire):
    name: str
    plan_digest: str
    config_digest: str
    attempts: int
    cap_usd: Decimal


class FrozenCohort(_Wire):
    schema_version: Literal["assay-extension-cohort/0.1.0"]
    cohort: str
    combined_cap_usd: Decimal
    plans: tuple[FrozenPlan, ...]

    def canonical_bytes(self) -> bytes:
        return canonical_json(self.model_dump(mode="json"))


def cohort_dir(store: ObjectStore, digest: str) -> Path:
    return store.root / "cohorts" / digest.removeprefix("sha256:")


def prepare_cohort(request_path: Path, store_path: Path) -> dict[str, Any]:
    """Freeze every plan and the cohort naming them; this dispatches nothing."""
    request = CohortRequest.model_validate_json(request_path.read_bytes())
    if len({plan.name for plan in request.plans}) != len(request.plans):
        raise LaunchRefused("duplicate plan name in cohort")
    paths = [request_path.parent / plan.config for plan in request.plans]
    configs = [RunConfiguration.load(path) for path in paths]
    if len({config.digest() for config in configs}) != len(configs):
        raise LaunchRefused("duplicate plan configuration in cohort")
    total = sum((config.total_cap_usd for config in configs), Decimal(0))
    # Each plan's gate refuses a reservation past its cap, so caps that fit here
    # bound every reservation. A bill above its reservation can still pass a cap
    # by that excess; the plan then halts and later plans do not start.
    if total > request.combined_cap_usd:
        raise LaunchRefused(
            f"combined_cap_exceeded: plan caps total {total}; "
            f"combined cap is {request.combined_cap_usd}"
        )
    summaries = [prepare(path, store_path) for path in paths]
    frozen = FrozenCohort(
        schema_version=SCHEMA, cohort=request.cohort, combined_cap_usd=request.combined_cap_usd,
        plans=tuple(
            FrozenPlan(
                name=plan.name, plan_digest=summary["digest"], config_digest=config.digest(),
                attempts=summary["attempts"], cap_usd=config.total_cap_usd,
            )
            for plan, config, summary in zip(request.plans, configs, summaries, strict=True)
        ),
    )
    data = frozen.canonical_bytes()
    digest = digest_bytes(data)
    directory = cohort_dir(ObjectStore(store_path), digest)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "cohort.json"
    path.write_bytes(data)
    durations = [item["expected_serial_duration"]["maximum_seconds"] for item in summaries]
    estimates = [item["estimated_spend_usd"] for item in summaries]
    summary: dict[str, Any] = {
        "cohort": str(path),
        "digest": digest,
        "name": request.cohort,
        "attempts": sum(item["attempts"] for item in summaries),
        "route_probe_calls": sum(item["route_probe_calls"] for item in summaries),
        "caps": {
            "combined_usd": str(request.combined_cap_usd),
            "plan_total_usd": str(total),
            "per_plan_usd": {plan.name: str(plan.cap_usd) for plan in frozen.plans},
        },
        "estimated_spend_usd": None if None in estimates
        else str(sum(Decimal(item) for item in estimates)),
        "expected_serial_duration": {
            "maximum_seconds": sum(durations),
            "basis": "every attempt in every plan reaches its timeout, before grading",
        },
        "schedule": {
            "plans": "one after another in the listed order, which separates models in time",
            "within_plan": summaries[0]["schedule"]["kind"],
        },
        "billing_recovery": summaries[0]["billing_recovery"],
        "plans": [
            {"name": plan.name, **item}
            for plan, item in zip(frozen.plans, summaries, strict=True)
        ],
    }
    (directory / "launch-summary.json").write_bytes(canonical_json(summary) + b"\n")
    return summary


async def _preflight(frozen: FrozenCohort, store: ObjectStore) -> list[FrozenPlan]:
    """Check the whole cohort before the first paid request; return what remains to run."""
    if sum((plan.cap_usd for plan in frozen.plans), Decimal(0)) > frozen.combined_cap_usd:
        raise LaunchRefused("combined_cap_exceeded: frozen plan caps exceed the combined cap")
    remaining: list[FrozenPlan] = []
    for plan in frozen.plans:
        directory = _plan_dir(store, plan.plan_digest)
        plan_bytes = (directory / "plan.json").read_bytes()
        config = RunConfiguration.load(directory / "config.json")
        if digest_bytes(plan_bytes) != plan.plan_digest or config.digest() != plan.config_digest \
                or config.total_cap_usd != plan.cap_usd:
            raise LaunchRefused(f"{plan.name}: frozen plan artifact changed")
        prepared = _build(config, store, live=False)
        if prepared.plan_bytes != plan_bytes:
            raise LaunchRefused(f"{plan.name}: plan differs from its frozen configuration")
        journal = AttemptJournal(directory / "attempts.jsonl", plan.plan_digest, config.digest())
        records = journal.records()
        state = plan_state(records)
        if state == "prepared":
            if config.route.provider != "smithers-local" \
                    and not os.environ.get("OPENROUTER_API_KEY"):
                raise LaunchRefused("hosted execution requires OPENROUTER_API_KEY")
            failure = await prepared.evaluator.runner._check_runtime()
            if failure is not None:
                raise LaunchRefused(
                    f"{plan.name}: evaluator_runtime_unavailable: {failure.error_type}"
                )
            remaining.append(plan)
        elif state != "finished":
            if any(record["event"] == "run_manifest" for record in records):
                raise LaunchRefused(
                    f"{plan.name} is {state}; continue it with code_extension.resume, "
                    "then launch again"
                )
            raise LaunchRefused(
                f"{plan.name} is {state} with no manifest, so nothing can resume it; "
                "prepare a new cohort from a relabelled configuration"
            )
    return remaining


async def launch(cohort_path: Path, authorization: str, store_path: Path) -> dict[str, Any]:
    data = cohort_path.read_bytes()
    actual = digest_bytes(data)
    if actual != authorization:
        raise LaunchRefused(
            f"cohort_authorization_mismatch: supplied {authorization}; actual {actual}"
        )
    store = ObjectStore(store_path)
    if cohort_path.resolve() != (cohort_dir(store, actual) / "cohort.json").resolve():
        raise LaunchRefused("original frozen cohort artifact is required")
    frozen = FrozenCohort.model_validate_json(data)
    results: list[dict[str, Any]] = []
    for plan in await _preflight(frozen, store):
        # Preflight reads state without a lock, so execute checks it again under one.
        result = await execute(
            _plan_dir(store, plan.plan_digest) / "plan.json", plan.plan_digest, store_path,
            unstarted_only=True,
        )
        results.append({"name": plan.name, **result})
        print(json.dumps({"event": "plan_ended", **results[-1]}, sort_keys=True), flush=True)
        if result["status"] != "RunSucceeded" or result["spend"]["halt"] is not None:
            return {"status": "halted", "cohort": actual, "plans": results}
    return {"status": "finished", "cohort": actual, "plans": results}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("prepare")
    p.add_argument("--cohort", type=Path, required=True)
    p.add_argument("--store", type=Path, required=True)
    e = commands.add_parser("execute")
    e.add_argument("--cohort", type=Path, required=True)
    e.add_argument("--authorize", required=True)
    e.add_argument("--store", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        print(json.dumps(prepare_cohort(args.cohort, args.store), sort_keys=True))
        return
    outcome = asyncio.run(launch(args.cohort, args.authorize, args.store))
    print(json.dumps(outcome, sort_keys=True))
    sys.exit(0 if outcome["status"] == "finished" else 1)


if __name__ == "__main__":
    main()
