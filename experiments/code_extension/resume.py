"""Continue an authorized extension grid without redispatching claimed attempts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import cast

from assay.canonical import canonical_json, digest_bytes
from assay.execution import RunResult, execute_plan
from assay.models import ExecutionOutcome, ExecutionPlanV3, RunManifest
from assay.planning import authorize
from assay.store import ObjectStore
from assay.verify import verify_manifest
from code_extension.budget import AttemptJournal
from code_extension.config import RunConfiguration
from code_extension.run import (
    ExtensionStudyWorker,
    LaunchRefused,
    _build,
    _interruption,
    _plan_dir,
    _plan_lock,
    _recorded,
    _route_probe,
    _settle_archive,
)


def checkpoint(
    store: ObjectStore, plan: ExecutionPlanV3, manifest_ref: str, journal: AttemptJournal,
) -> tuple[str, tuple[str, ...]]:
    """Keep claimed outcomes; discard only proven pre-dispatch spending refusals."""
    journal.validate_resume()
    manifest = RunManifest.model_validate_json(store.read_bytes(manifest_ref))
    if manifest.plan_ref != journal.plan_digest:
        raise LaunchRefused("resume manifest belongs to another plan")
    failures = verify_manifest(store, manifest_ref)
    if any(f.code != "incomplete_run" for f in failures):
        raise LaunchRefused(f"invalid resume manifest: {failures}")
    if manifest.interruption_ref is not None:
        raise LaunchRefused("an interrupted run cannot resume")
    claimed = {
        r["coordinate"] for r in journal.records()
        if r["event"] == "attempt_started" and r["coordinate"] != "__route_probe__"
    }
    if not claimed <= manifest.execution_records.keys():
        raise LaunchRefused("a claimed attempt lacks a terminal outcome; recover it first")
    if not claimed <= {cell.id for cell in plan.cells}:
        raise LaunchRefused("journal contains an unplanned coordinate")
    for cell in manifest.execution_records.keys() - claimed:
        outcome = ExecutionOutcome.model_validate_json(
            store.read_bytes(manifest.execution_records[cell]),
        )
        if outcome.status != "failed" or outcome.error_type not in {
            "billing_uncertain", "budget_exhausted",
        } or outcome.error_message != "run spending gate halted" \
                or outcome.output_ref is not None or outcome.trace_ref is not None:
            raise LaunchRefused("unclaimed outcome is not a pre-dispatch spending refusal")
    execution = {cell: ref for cell, ref in manifest.execution_records.items() if cell in claimed}
    evaluations = {item.id: manifest.evaluation_records[item.id] for item in plan.evaluations
                   if item.cell_id in claimed and item.id in manifest.evaluation_records}
    operating = {key: ref for key, ref in manifest.operating_records.items()
                 if (key.startswith("worker:") and key[7:] in execution)
                 or (key.startswith("evaluator:") and key[10:] in evaluations)}
    successful = {
        cell for cell, ref in execution.items()
        if ExecutionOutcome.model_validate_json(store.read_bytes(ref)).status == "succeeded"
    }
    expected_operating = {f"worker:{cell}" for cell in execution} | {
        f"evaluator:{item.id}" for item in plan.evaluations
        if item.id in evaluations and item.cell_id in successful
    }
    missing = (
        ({cell.id for cell in plan.cells} - execution.keys())
        | ({item.id for item in plan.evaluations} - evaluations.keys())
        | (expected_operating - operating.keys())
        | {item.id for item in plan.evaluations
           if item.id in evaluations and item.cell_id not in successful}
    )
    resumed = manifest.model_copy(update={
        "execution_records": execution, "evaluation_records": evaluations,
        "operating_records": operating, "missing_coordinates": tuple(sorted(missing)),
        "status": "incomplete" if missing else "complete",
    })
    checkpoint_ref = str(store.publish_json(resumed.model_dump(mode="json")))
    if any(f.code != "incomplete_run" for f in verify_manifest(store, checkpoint_ref)):
        raise LaunchRefused("resume checkpoint failed verification")
    remaining = tuple(cell.id for cell in plan.cells if cell.id not in claimed)
    return checkpoint_ref, remaining


async def resume(
    plan_path: Path, authorization: str, store_path: Path, manifest_ref: str,
    *, accept_unknown: str | None = None,
) -> dict[str, object]:
    plan_bytes = plan_path.read_bytes()
    if digest_bytes(plan_bytes) != authorization:
        raise LaunchRefused("resume plan authorization mismatch")
    plan = authorize(plan_bytes, authorization)
    if not isinstance(plan, ExecutionPlanV3):
        raise LaunchRefused("extension resume requires a v3 plan")
    store = ObjectStore(store_path)
    directory = _plan_dir(store, authorization)
    if plan_path.resolve() != (directory / "plan.json").resolve():
        raise LaunchRefused("original frozen plan artifact is required")
    with _plan_lock(directory):
        return await _resume(
            plan, plan_bytes, authorization, store, directory, manifest_ref, accept_unknown,
        )


async def _resume(
    plan: ExecutionPlanV3, plan_bytes: bytes, authorization: str, store: ObjectStore,
    directory: Path, manifest_ref: str, accept_unknown: str | None,
) -> dict[str, object]:
    config = RunConfiguration.load(directory / "config.json")
    journal = AttemptJournal(directory / "attempts.jsonl", authorization, config.digest())
    checkpoint_ref, remaining = checkpoint(store, plan, manifest_ref, journal)
    prepared = _build(config, store, live=False)
    if prepared.plan_bytes != plan_bytes:
        raise LaunchRefused("resume configuration differs from frozen plan")
    records = journal.records()
    unknown = {r["attempt_id"] for r in records
               if r["event"] == "finished" and r["cost_usd"] is None}
    if accept_unknown is not None:
        for request_id in sorted(unknown):
            journal.accept_uncertain_charge(request_id, reason=accept_unknown)
    audit = {
        "schema_version": "assay-extension-resume/0.1.0", "plan_ref": authorization,
        "prior_manifest_ref": manifest_ref, "checkpoint_ref": checkpoint_ref,
        "remaining_coordinates": list(remaining), "unknown_charge_request_ids": sorted(unknown),
        "unknown_charge_reason": accept_unknown,
    }
    audit_ref = str(store.publish_json(audit))
    (directory / f"resume-{audit_ref.removeprefix('sha256:')}.json").write_bytes(
        canonical_json(audit) + b"\n",
    )
    prepared = _build(config, store, live=True, plan_digest=authorization)
    if prepared.plan_bytes != plan_bytes:
        raise LaunchRefused("resume plan changed before dispatch")
    worker = cast(ExtensionStudyWorker, next(iter(prepared.workers.values())))
    assert worker.binding is not None and worker.gate is not None
    archive = worker.binding.archive
    archive.retain_manifest_closure(store, manifest_ref)
    archive.retain_manifest_closure(store, checkpoint_ref)
    retained_audit = archive._publish(canonical_json(audit))
    (archive.directory / f"resume-{audit_ref.removeprefix('sha256:')}.json").write_bytes(
        archive.objects.read_bytes(retained_audit) + b"\n",
    )
    runtime_failure = await prepared.evaluator.runner._check_runtime()
    if runtime_failure is not None:
        raise LaunchRefused("resume evaluator runtime is unavailable")
    binding = worker.binding

    async def dispatch() -> tuple[RunResult, Path | None]:
        await _route_probe(config, store, authorization, prepared)
        result = await execute_plan(
            plan_bytes=plan_bytes, authorization=authorization, snapshot=prepared.snapshot,
            store=store, workers=prepared.workers, evaluators={"correctness": prepared.evaluator},
            resume_from=checkpoint_ref,
        )
        latest = str(result.manifest_ref) if result.manifest_ref is not None else None
        return result, _settle_archive(
            binding, fixture=prepared, manifest_ref=latest,
            interruption=_interruption(result), preserve_settled=True,
        )

    result, index = await _recorded(worker, dispatch())
    return {
        "status": type(result).__name__, "authorization": authorization,
        "spend": worker.gate.record(), "resume_audit_ref": audit_ref,
        "unknown_charge_request_ids": sorted(unknown),
        "archive": str(worker.binding.archive.directory),
        "run_index": str(index) if index is not None else None,
    }


def main() -> None:
    import asyncio

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--authorize", required=True)
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--accept-unknown", metavar="REASON")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(resume(
        args.plan, args.authorize, args.store, args.manifest, accept_unknown=args.accept_unknown,
    ))))


if __name__ == "__main__":
    main()
