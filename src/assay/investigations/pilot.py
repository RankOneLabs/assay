"""Prepare, inspect, then explicitly authorize a source-only consistency pilot."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from importlib.metadata import distribution
from pathlib import Path

from assay._version import __version__
from assay.adapters.consistency import ClientFactory, ConsistencyWorker, PilotSettings, render_input
from assay.execution import RunFailed, WorkerFailure, execute_plan
from assay.investigations.consistency import (
    CATEGORIES,
    StructuralEvaluator,
    materialize_consistency,
)
from assay.models import ReportConfig, StatisticalProfile, StudySnapshot
from assay.planning import authorize, compile_plan
from assay.report_engine import persist_report
from assay.store import ObjectStore
from assay.verify import export_bundle, verify_bundle, verify_snapshot


@dataclass(frozen=True)
class PilotPrepared:
    snapshot_ref: str
    plan_ref: str
    executions: int
    evaluations: int


@dataclass(frozen=True)
class PilotFailed:
    error_type: str
    message: str
    manifest_ref: str | None = None
    report_ref: str | None = None


@dataclass(frozen=True)
class PilotSucceeded:
    manifest_ref: str
    report_ref: str


def installed_jig_revision() -> str:
    """Fail closed for an unpinned/local install, rather than inventing provenance."""
    direct = distribution("jig").read_text("direct_url.json")
    if direct is None:
        raise ValueError("pilot requires a VCS-pinned Jig installation")
    metadata = json.loads(direct)
    if not isinstance(metadata, dict) or "dir_info" in metadata or "archive_info" in metadata:
        raise ValueError("pilot requires a non-editable VCS-pinned Jig installation")
    vcs = metadata.get("vcs_info")
    if not isinstance(vcs, dict) or vcs.get("vcs") != "git":
        raise ValueError("pilot requires Git provenance for Jig")
    revision = vcs.get("commit_id")
    requested = vcs.get("requested_revision")
    if (
        not isinstance(revision, str)
        or re.fullmatch(r"[0-9a-fA-F]{40}", revision) is None
        or not isinstance(requested, str)
        or re.fullmatch(r"[0-9a-fA-F]{40}", requested) is None
        or requested.lower() != revision.lower()
    ):
        raise ValueError("Jig must be requested at its exact full Git commit revision")
    return revision.lower()


def prepare_pilot(
    store: ObjectStore,
    *,
    factory: ClientFactory,
    settings: PilotSettings,
    schemas: Mapping[str, dict[str, object]],
) -> PilotPrepared | PilotFailed:
    """No client creation or provider calls. Returns the plan hash for inspection.

    Three tasks, two arms, two worker repeats, one deterministic evaluation,
    concurrency one. The artifact closure carries the complete authorized policy.
    """
    try:
        worker = ConsistencyWorker(factory, settings)
        snapshot = materialize_consistency(
            store,
            worker_configuration=worker.configuration("clean"),
            evaluator=StructuralEvaluator(),
            schemas=schemas,
            evaluator_repeats=1,
        )
        verify_snapshot(store, snapshot)
        snapshot_ref = str(store.publish_json(snapshot.model_dump(mode="json")))
        plan = compile_plan(
            snapshot,
            snapshot_ref=snapshot_ref,
            worker_repeats=2,
            jig_revision=installed_jig_revision(),
            concurrency=1,
        )
        plan_ref = str(store.publish_json(plan.model_dump(mode="json")))
        return PilotPrepared(snapshot_ref, plan_ref, len(plan.cells), len(plan.evaluations))
    except Exception as error:
        return PilotFailed(type(error).__name__, str(error))


async def run_pilot(
    store: ObjectStore,
    *,
    plan_ref: str,
    authorization: str,
    factory: ClientFactory,
    allow_paid: bool = False,
    export_destination: Path | None = None,
) -> PilotSucceeded | PilotFailed:
    """Execute exactly an inspected plan; never generate its authorization here.

    Paid mode additionally requires explicit opt-in. Reinvocation is a new run
    with a new run-local budget, not a resume operation or a lifetime spend cap.
    """
    manifest_ref: str | None = None
    report_ref: str | None = None
    try:
        plan_bytes = store.read_bytes(plan_ref)
        plan = authorize(plan_bytes, authorization)
        if plan.jig_revision != installed_jig_revision() or plan.assay_version != __version__:
            raise ValueError("installed runtime differs from authorized plan")
        snapshot = StudySnapshot.model_validate_json(store.read_bytes(plan.snapshot_ref))
        if plan.concurrency != 1 or plan.worker_repeats != 2:
            raise ValueError("pilot requires concurrency one and two worker repeats")
        settings = PilotSettings.model_validate(snapshot.arms[0].worker["settings"])
        if settings.mode == "paid" and not allow_paid:
            raise ValueError("paid pilot requires explicit allow_paid=True")
        worker = ConsistencyWorker(factory, settings, allow_paid=allow_paid)
        evaluator = StructuralEvaluator()
        if {arm.id for arm in snapshot.arms} != {"clean", "inconsistent"}:
            raise ValueError("pilot requires clean and inconsistent arms")
        if len(snapshot.evaluators) != 1 or snapshot.evaluators[0].repeats != 1:
            raise ValueError("pilot requires one deterministic evaluation per output")
        # Validate every rendering before making the first potentially paid call.
        for ref in {cell.realization_ref for cell in plan.cells}:
            rendered = render_input(json.loads(store.read_bytes(ref)), settings.max_input_bytes)
            if isinstance(rendered, WorkerFailure):
                return PilotFailed(rendered.error_type, rendered.message)
        result = await execute_plan(
            plan_bytes=plan_bytes,
            authorization=authorization,
            snapshot=snapshot,
            store=store,
            workers={arm.id: worker for arm in snapshot.arms},
            evaluators={"abstraction": evaluator},
        )
        if result.manifest_ref is not None:
            manifest_ref = str(result.manifest_ref)
        if isinstance(result, RunFailed):
            return PilotFailed(result.error_type, result.message, manifest_ref)
        assert manifest_ref is not None
        config = ReportConfig(
            manifest_refs=(manifest_ref,),
            record_refs=tuple(sorted(result.manifest.evaluation_records.values())),
            reference_arm="clean",
            candidates=("inconsistent",),
            evaluator_id="abstraction",
            metric="ordinal",
            categories=CATEGORIES,
            evaluator_repeat_aggregation="median",
            worker_repeat_aggregation="median",
            statistical_profile=StatisticalProfile(
                seed=7,
                bootstrap_samples=100,
            ),
            engine_version=__version__,
        )
        report_ref = str(persist_report(store, config))
        if export_destination is not None:
            bundle = export_bundle(store, report_ref, export_destination)
            failures = verify_bundle(bundle, report_ref)
            if failures:
                raise ValueError(f"exported bundle failed verification: {failures}")
        return PilotSucceeded(manifest_ref, report_ref)
    except Exception as error:
        return PilotFailed(type(error).__name__, str(error), manifest_ref, report_ref)
