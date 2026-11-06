"""Read where a study's plans stand, from durable records only; this writes nothing.

An attempt's terminal state comes from the journal, so it is current while a grid
runs. Grading follows the last attempt and is only retained in the run manifest,
so `evaluated` and `passed` stay null until a plan has settled once.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from decimal import Decimal
from pathlib import Path
from typing import Any

from assay.models import ExecutionOutcome, ExecutionPlanV3, RunManifest, parse_execution_plan
from assay.store import ObjectStore
from code_extension.budget import AttemptJournal
from code_extension.classification import Passed, classify
from code_extension.config import RunConfiguration
from code_extension.ledger import _stop, _verdict
from code_extension.run import LaunchRefused, _archive_root, _plan_dir, _run_label

ROUTE_PROBE = "__route_probe__"


def plan_state(records: list[dict[str, Any]]) -> str:
    """`in_progress` also describes a killed process; compare `last_activity`."""
    if not records:
        return "prepared"
    last = next(
        (r for r in reversed(records) if r["event"] in {"run_started", "run_ended"}), None,
    )
    if last is None:
        return "unrecorded"  # A journal written before runs recorded their own end.
    if last["event"] == "run_started":
        return "in_progress"
    return "finished" if last["result"] == "RunSucceeded" and last["halt"] is None else "halted"


def _charges(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Count a request at its full reservation until a measured cost replaces it."""
    finished = {r["attempt_id"]: r for r in records if r["event"] == "finished"}
    measured = conservative = Decimal(0)
    unknown: list[str] = []
    unsettled: list[str] = []
    for record in records:
        if record["event"] != "reserved":
            continue
        request = record["attempt_id"]
        terminal = finished.get(request)
        if terminal is None:
            unsettled.append(request)
            conservative += Decimal(record["bound_usd"])
        elif terminal["status"] == "not_sent":
            continue
        elif terminal["cost_usd"] is None:
            unknown.append(request)
            conservative += Decimal(record["bound_usd"])
        else:
            measured += Decimal(terminal["cost_usd"])
            conservative += Decimal(terminal["cost_usd"])
    return {
        "measured_usd": str(measured),
        "conservative_usd": str(conservative),
        "unknown_charges": unknown,
        "unsettled_requests": unsettled,
    }


def _manifest(store: ObjectStore, config: RunConfiguration) -> tuple[str, RunManifest] | None:
    index = _archive_root(store) / _run_label(config) / "run.json"
    if not index.is_file():
        return None
    reference = str(json.loads(index.read_bytes())["manifest_ref"])
    return reference, RunManifest.model_validate_json(store.read_bytes(reference))


def plan_status(store: ObjectStore, plan_digest: str) -> dict[str, Any]:
    directory = _plan_dir(store, plan_digest)
    plan = parse_execution_plan(json.loads((directory / "plan.json").read_bytes()))
    if not isinstance(plan, ExecutionPlanV3):
        raise LaunchRefused("extension status requires a v3 plan")
    config = RunConfiguration.load(directory / "config.json")
    records = AttemptJournal(directory / "attempts.jsonl", plan_digest, config.digest()).records()
    claimed = [
        r["coordinate"] for r in records
        if r["event"] == "attempt_started" and r["coordinate"] != ROUTE_PROBE
    ]
    outcomes = {
        r["coordinate"]: r["status"] for r in records if r["event"] == "attempt_finished"
    }
    settled = _manifest(store, config)
    evaluated: int | None = None
    passed: int | None = None
    missing: list[str] | None = None
    if settled is not None:
        _, manifest = settled
        evaluated = passed = 0
        missing = list(manifest.missing_coordinates)
        # A manifest also lists spending refusals for cells that were never claimed.
        for cell in claimed:
            reference = manifest.execution_records.get(cell)
            if reference is None:
                continue
            outcome = ExecutionOutcome.model_validate_json(store.read_bytes(reference))
            outcomes[cell] = outcome.status
            verdict = _verdict(cell, manifest, store)
            if verdict is not None and verdict.value != "unavailable":
                evaluated += 1
            passed += isinstance(classify(_stop(outcome, store), verdict), Passed)
    state = plan_state(records)
    halt = next((r for r in reversed(records) if r["event"] == "run_ended"), None)
    active = [cell for cell in claimed if cell not in outcomes]
    return {
        "plan_digest": plan_digest,
        "state": state,
        "planned": len(plan.cells),
        "started": len(claimed),
        "terminal": len(outcomes),
        "completed_normally": sum(status == "succeeded" for status in outcomes.values()),
        "evaluated": evaluated,
        "passed": passed,
        "unstarted": len(plan.cells) - len(claimed),
        "active_coordinate": active[-1] if active and state == "in_progress" else None,
        "last_activity": records[-1].get("at") if records else None,
        "halt_reason": (halt["halt"] or halt["detail"]) if halt and state == "halted" else None,
        "manifest_ref": settled[0] if settled else None,
        "missing_coordinates": missing,
        "cap_usd": str(config.total_cap_usd),
        **_charges(records),
    }


def _combined_state(states: Iterable[str]) -> str:
    seen = set(states)
    for state in ("halted", "unrecorded", "in_progress"):
        if state in seen:
            return state
    return "finished" if seen == {"finished"} else "prepared" if seen == {"prepared"} \
        else "between_plans"


def store_status(store_path: Path, *, cohort: str | None = None) -> dict[str, Any]:
    """Report a cohort's plans in launch order, or every plan a store holds."""
    store = ObjectStore(store_path)
    if cohort is None:
        names = sorted((store.root / "plans").glob("*/plan.json"))
        digests = {f"sha256:{path.parent.name}": None for path in names}
        cap = None
    else:
        frozen = json.loads(
            (store.root / "cohorts" / cohort.removeprefix("sha256:") / "cohort.json").read_bytes()
        )
        digests = {plan["plan_digest"]: plan["name"] for plan in frozen["plans"]}
        cap = frozen["combined_cap_usd"]
    plans = [{"name": name, **plan_status(store, digest)} for digest, name in digests.items()]
    counts = ("planned", "started", "terminal", "completed_normally", "unstarted")
    return {
        "cohort": cohort,
        "state": _combined_state(plan["state"] for plan in plans),
        "plans": plans,
        **{name: sum(plan[name] for plan in plans) for name in counts},
        **{
            name: None if any(plan[name] is None for plan in plans)
            else sum(plan[name] for plan in plans)
            for name in ("evaluated", "passed")
        },
        "combined_cap_usd": cap,
        "measured_usd": str(sum(Decimal(plan["measured_usd"]) for plan in plans)),
        "conservative_usd": str(sum(Decimal(plan["conservative_usd"]) for plan in plans)),
        "unknown_charges": [item for plan in plans for item in plan["unknown_charges"]],
    }
