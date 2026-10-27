"""Run self-trust shards and archive them under ``raw/self_trust/runs``.

Commands, from ``experiments/``:

- ``scripted --store DIR``: the 36 x 2 grid with a model-free worker, to check
  the plan, evaluator and archive end to end.
- ``calibrate --store DIR --image DIGEST --paid-route NAME --max-spend-usd N``:
  calibration step 1. Every teammate-share remnant of one concept (six cells),
  native arm only.
- ``calibrate-refactor ...``: the first refactor signal. A matched
  own/teammate pair for each omission location, six cells, native arm only.
- ``attribution-order ...``: the same matched pairs in the two quoted arms
  that put the omission holder's log first or last, so attribution and log
  position vary separately. Twelve cells.
- ``remeasure --archive DIR ... --image DIGEST``: re-derive archived measures
  from their trajectories after a measure is added or changed.
- ``cells --subject ID ... --arm ARM ...``: any explicit shard on the paid
  route, for the later calibration steps.

Docker Desktop cannot bind-mount ``/tmp``, so ``--runs-root`` must live
elsewhere on a live run.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

from assay.adapters.smithers import SmithersFactory
from assay.execution import RunFailed, RunSucceeded, execute_plan
from assay.models import RuntimeProfile
from assay.store import ObjectStore
from verification_pilot.bridge import ModelRoute
from verification_pilot.budget import SpendGate
from verification_pilot.run import (
    PAID_ROUTES,
    ScriptedWorker,
    _spend_cap,
    archive_manifest,
    dated_measures_path,
    paid_model_route,
)
from verification_pilot.self_trust.bridge import SelfTrustBridgeClient, self_trust_worker
from verification_pilot.self_trust.evaluation import SelfTrustEvaluator, measures
from verification_pilot.self_trust.settings import (
    CELL_SECONDS,
    LOCAL_MAX_OUTPUT_TOKENS,
    SelfTrustSettings,
)
from verification_pilot.self_trust.study import (
    ARMS,
    ATTRIBUTION_ORDER_ARMS,
    PreparedSelfTrust,
    SelfTrustSubject,
    calibration_subject_ids,
    compile_self_trust_plan,
    refactor_calibration_ids,
    self_trust_subjects,
)

ARCHIVE_ROOT = Path(__file__).resolve().parents[1] / "raw" / "self_trust" / "runs"


async def _execute(store: ObjectStore, prepared: PreparedSelfTrust, worker: Any,
                   subjects: dict[str, SelfTrustSubject],
                   archive_root: Path, image: str = "") -> tuple[Any, Path | None]:
    evaluator = SelfTrustEvaluator(store, subjects, image)

    def _measures(trace: Any, subject: SelfTrustSubject) -> list[dict[str, Any]]:
        return measures(subject, trace, image)

    result = await execute_plan(
        plan_bytes=prepared.plan_bytes, authorization=prepared.authorization,
        snapshot=prepared.snapshot, store=store,
        workers={arm.id: worker for arm in prepared.snapshot.arms},
        evaluators={declaration.id: evaluator for declaration in prepared.snapshot.evaluators},
    )
    destination = None
    if isinstance(result, RunFailed | RunSucceeded) and result.manifest_ref is not None:
        destination = archive_manifest(store, str(result.manifest_ref), archive_root,
                                       subjects, measure=_measures)
    return result, destination


async def run_scripted(store: ObjectStore, archive_root: Path,
                       image: str = "") -> tuple[Any, Path | None]:
    subjects = self_trust_subjects()
    worker = ScriptedWorker(store)
    runtime = RuntimeProfile(id="scripted", version="1",
                             configuration_ref=str(store.publish_json({"scripted": True})))
    prepared = compile_self_trust_plan(
        store, runtime, worker_configurations={arm: worker.configuration(arm) for arm in ARMS},
        active_subject_ids=tuple(s.id for s in subjects), subjects_data=subjects)
    return await _execute(store, prepared, worker, {s.id: s for s in subjects}, archive_root,
                          image)


async def run_live(store: ObjectStore, *, image: str, runs_root: Path,
                   paid_route: str | None, api_key: str | None, spend_gate: SpendGate | None,
                   subject_ids: tuple[str, ...], arms: tuple[str, ...], archive_root: Path,
                   local_model: str | None = None, routing_config: Path | None = None,
                   repeats: int = 1) -> tuple[Any, Path | None]:
    """One shard on the paid route, or on the free local route when ``local_model`` is set."""
    subjects = self_trust_subjects()
    by_id = {s.id: s for s in subjects}
    if local_model is not None:
        if api_key or spend_gate is not None or paid_route is not None:
            raise ValueError("the local route takes no OpenRouter key, spend cap or paid route")
        if routing_config is None:
            raise ValueError("the local route needs the Smithers routing config")
        bridge = SelfTrustBridgeClient(
            image=image, runs_root=runs_root,
            # Smithers keys each job by label, cell and turn and refuses a
            # changed body under a seen key, so a fixed label made any re-run of
            # a cell fail. The label is outside the worker fingerprint.
            run_label=f"self-trust-local-{uuid.uuid4()}",
            model_route=ModelRoute(endpoint="http://willie:8900", model=local_model,  # type: ignore[arg-type]
                                   provider="smithers-local"),
            subjects=dict(by_id),
            settings=SelfTrustSettings(max_output_tokens=LOCAL_MAX_OUTPUT_TOKENS),
            factory=SmithersFactory(model=local_model, machine="mcbain",
                                    routing_config=routing_config,
                                    dispatch_url="http://willie:8900"),
            timeout_s=CELL_SECONDS,
        )
    else:
        if not api_key or any(char.isspace() for char in api_key):
            raise ValueError("OPENROUTER_API_KEY is required for the paid route")
        if paid_route is None or spend_gate is None:
            raise ValueError("the paid route needs a named route and a spend cap")
        bridge = SelfTrustBridgeClient(
            image=image, runs_root=runs_root, run_label="self-trust",
            model_route=paid_model_route(paid_route), subjects=dict(by_id),
            settings=SelfTrustSettings(), api_key=api_key, spend_gate=spend_gate,
            timeout_s=CELL_SECONDS,
        )
    worker, runtime = self_trust_worker(store, bridge)
    prepared = compile_self_trust_plan(
        store, runtime, worker_configurations={arm: worker.configuration(arm) for arm in ARMS},
        active_subject_ids=subject_ids, active_arms=arms, subjects_data=subjects,
        worker_repeats=repeats)
    result, destination = await _execute(store, prepared, worker, by_id, archive_root, image)
    if destination is not None and spend_gate is not None:
        (destination / "spend.json").write_text(
            json.dumps(spend_gate.record(), sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return result, destination


def remeasure(archive: Path, image: str) -> int:
    """Re-derive every measures file of one archive from its own trajectories."""
    by_id = {s.id: s for s in self_trust_subjects()}
    index = json.loads((archive / "index.json").read_text(encoding="utf-8"))
    rewritten = 0
    for cell_id, entry in sorted(index.items()):
        if "trajectory" not in entry or "measures" not in entry:
            continue
        trace = json.loads((archive / "traces" / entry["trajectory"]).read_text(encoding="utf-8"))
        rows = measures(by_id[cell_id.split(":", 1)[0]], trace, image)
        dated_measures_path(archive / "traces" / entry["measures"]).write_text(
            json.dumps(rows, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        rewritten += 1
    return rewritten


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("scripted", "calibrate", "calibrate-refactor",
                                            "attribution-order", "cells", "remeasure"))
    parser.add_argument("--archive", type=Path, action="append", default=[])
    parser.add_argument("--store", type=Path, default=None)
    parser.add_argument("--image", default="")
    parser.add_argument("--runs-root", type=Path, default=None)
    parser.add_argument("--paid-route", choices=sorted(PAID_ROUTES), default=None)
    parser.add_argument("--max-spend-usd", type=_spend_cap, default=None)
    parser.add_argument("--concept", default="stage_run")
    parser.add_argument("--rung", choices=("refactor", "refactor-long", "rewrite0", "rewrite0-read",
                                           "rewrite1",
                                           "rewrite2", "rewrite", "forge-move", "forge-rewrite",
                                           "resume146"),
                        default="refactor",
                        help="size-ladder rung for calibrate-refactor and attribution-order: "
                             "S (refactor) or L (rewrite)")
    parser.add_argument("--local-model", choices=("qwen3.6-27b", "qwen-coder-32b"), default=None,
                        help="run on the free local Smithers route instead of the paid route")
    parser.add_argument("--routing-config", type=Path,
                        default=Path("~/codes/rol/smithers/routing_config.yaml"))
    parser.add_argument("--repeats", type=int, default=1,
                        help="worker repeats per cell, for rungs with few matched pairs")
    parser.add_argument("--subject", action="append", default=[])
    parser.add_argument("--arm", action="append", choices=ARMS, default=[])
    args = parser.parse_args()
    if args.command == "remeasure":
        if not args.image or not args.archive:
            parser.error("remeasure needs --image and --archive")
        print(json.dumps({str(path): remeasure(path, args.image) for path in args.archive}))
        return
    if args.store is None:
        parser.error("--store is required")
    store = ObjectStore(args.store)
    if args.command == "scripted":
        if not args.image:
            parser.error("scripted needs --image: refactor cells are scored in the image")
        result, destination = asyncio.run(run_scripted(store, ARCHIVE_ROOT, args.image))
        print(json.dumps({"result": type(result).__name__, "archive": str(destination)}))
        return
    if not args.image or args.runs_root is None:
        parser.error("live runs require --image and --runs-root")
    local = args.local_model is not None
    if local and (args.paid_route is not None or args.max_spend_usd is not None):
        parser.error("the local route takes no --paid-route or --max-spend-usd")
    if not local and (args.paid_route is None or args.max_spend_usd is None):
        parser.error("paid runs require --paid-route and --max-spend-usd")
    subjects = self_trust_subjects()
    arms: tuple[str, ...]
    if args.command == "calibrate":
        subject_ids, arms = calibration_subject_ids(subjects, args.concept), ("st-native",)
    elif args.command == "calibrate-refactor":
        subject_ids, arms = refactor_calibration_ids(subjects, args.rung), ("st-native",)
    elif args.command == "attribution-order":
        subject_ids, arms = refactor_calibration_ids(subjects, args.rung), ATTRIBUTION_ORDER_ARMS
    else:
        if not args.subject or not args.arm:
            parser.error("cells requires --subject and --arm")
        subject_ids, arms = tuple(args.subject), tuple(args.arm)
    gate = None if local else SpendGate(Decimal(args.max_spend_usd))
    result, destination = asyncio.run(run_live(
        store, image=args.image, runs_root=args.runs_root, paid_route=args.paid_route,
        api_key=None if local else os.environ.get("OPENROUTER_API_KEY", ""), spend_gate=gate,
        subject_ids=subject_ids, arms=arms, archive_root=ARCHIVE_ROOT,
        local_model=args.local_model, routing_config=args.routing_config.expanduser(),
        repeats=args.repeats))
    print(json.dumps({"result": type(result).__name__,
                      "error": result.message if isinstance(result, RunFailed) else None,
                      "manifest_ref": str(result.manifest_ref) if result.manifest_ref else None,
                      "archive": str(destination),
                      "spend": gate.record() if gate is not None else None}))


if __name__ == "__main__":
    main()
