"""wf-13 qualification: a real repository-agent smoke through ``execute_plan``.

Every cell of the smoke runs the production path: an authorized 0.3.0 plan with
a capacity ceiling, ``PierAdapter`` packaging and settlement, the bridge's
repository agent with each turn dispatched through the pinned Smithers client,
and the workflow correctness evaluator on the reconstructed patch. The probes
drive the same path with scripted, model-free turns to produce each typed
rejection on purpose. Everything a published number is computed from is
written to the evidence file this module also reads back.
"""

from __future__ import annotations

import argparse
import asyncio
import gzip
import json
import time
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import paa_contracts

from assay.adapters.pier import PierAdapter
from assay.adapters.smithers import SmithersFactory
from assay.canonical import canonical_json, digest_bytes
from assay.execution import (
    EvaluationFailed,
    EvaluationResult,
    RunFailed,
    WorkerResult,
    WorkerSuccess,
    execute_plan,
)
from assay.fixture_manifest import FixtureManifest, FixtureManifestV2, fixture_identity
from assay.investigations.workflow_correctness import (
    DockerWorkflowRunner,
    WorkflowRunnerSettings,
)
from assay.models import (
    Arm,
    CellCoordinate,
    EvaluationCoordinate,
    EvaluatorDeclaration,
    ExecutionCeiling,
    ExecutionPlanV3,
    Realization,
    RuntimeProfile,
    StudySnapshot,
    Subject,
)
from assay.pier_protocol import CandidateSubmission, RuntimeBinding
from assay.planning import compile_plan_v2
from assay.store import ObjectIntegrityError, ObjectStore
from workflow_edit.arms import MESS_00
from workflow_edit.bridge import (
    LOCAL_ROUTE,
    WorkflowEditBridgeClient,
    trial_limits,
)
from workflow_edit.diagnose import diagnose
from workflow_edit.evaluation import (
    CORRECTNESS_CATEGORIES,
    CellEvaluator,
    cell_arm,
    envelope_bytes,
    evaluate_candidate,
    record_result,
    worker_candidate,
)
from workflow_edit.fixture import (
    MAX_REPOSITORY_BYTES,
    MAX_REPOSITORY_FILES,
    SMOKE_EDIT_SUBJECT_ID,
    SmokeEditFixture,
    load_fixture,
)

CHECKPOINT = "f3b3ffca43e43672ff2f58ab797d65c7532aaed8"
SMITHERS = "http://willie:8900"
MACHINE = "mcbain"
MODEL_ALIAS = "qwen-coder-32b"
CELL_TIMEOUT_S = 900.0
EVIDENCE = Path(__file__).resolve().parent / "evidence" / "wf13"
HOSTED_MODEL = "qwen/qwen3.5-397b-a17b"


def fixture_manifest(
    store: ObjectStore, fixture: SmokeEditFixture, *, image: str, routing_digest: str
) -> FixtureManifest:
    """Fill the Part 1 manifest format for the smoke fixture, binding the built image."""
    hidden = [
        str(store.publish_json(group.model_dump(mode="json"))) for group in fixture.groups[1:]
    ]
    return FixtureManifest(
        schema_version="assay-fixture-manifest/0.1.0",
        checkpoint_sha=CHECKPOINT,
        included_paths=tuple(sorted(fixture.repository)),
        excluded_paths=(
            "oakridge-dbos/** except included_paths; see fixtures/smoke-edit/README.md",
        ),
        dependency_lock_digests={
            name: digest_bytes(fixture.repository[name].encode("utf-8"))
            for name in ("package.json", "package-lock.json")
        },
        observed_runtime_image_digest=image,
        normalization_diff="Slice adaptations only; listed in fixtures/smoke-edit/README.md.",
        treatment_site_inventory=(),
        per_arm_tree_digests={MESS_00: fixture.tree_digest},
        transformation_version="smoke-edit-slice/1",
        equivalence_test_version="smoke-edit-no-doses/1",
        task_prompt=fixture.task,
        hidden_tests=tuple(hidden),
        reference_patch=str(store.publish_bytes(fixture.reference_patch.encode("utf-8"))),
        negative_patches=(str(store.publish_bytes(fixture.negative_patch.encode("utf-8"))),),
        rubric=str(store.publish_json({"rubric": "none: the smoke fixture is never graded"})),
        routing_config_digest=routing_digest,
    )


@dataclass
class CorrectnessEvaluator:
    """Grade one settled smoke cell against the single-arm 0.1.0 manifest.

    As in the study's ``CellEvaluator``, the arm comes from the cell, the
    baseline from the realization the worker was given, and the baseline
    digest from the worker's own evidence. Only the hidden groups stay
    positional, because 0.1.0 records them that way; each must still carry
    the name it is graded under.
    """

    store: ObjectStore
    fixture: SmokeEditFixture
    manifest: FixtureManifest
    runner: DockerWorkflowRunner
    records: dict[str, dict[str, Any]] = field(default_factory=dict)

    def configuration(self) -> dict[str, Any]:
        return {
            "id": "workflow-edit-correctness",
            "version": "1",
            "categories": list(CORRECTNESS_CATEGORIES),
            "runner": self.runner.configuration(),
            "fixture": fixture_identity(self.manifest),
            "visible_regression": digest_bytes(
                canonical_json(self.fixture.groups[0].model_dump(mode="json"))
            ),
        }

    async def evaluate(
        self, *, input_value: Any, output: Any, coordinate: EvaluationCoordinate
    ) -> EvaluationResult:
        started = time.monotonic()
        _subject_id, arm_id = cell_arm(coordinate)
        try:
            if output["cell_id"] != coordinate.cell_id:
                return EvaluationFailed("MismatchedCell", "output belongs to another cell")
            candidate = worker_candidate(self.store, output)
            baseline = input_value["repository"]
        except (KeyError, TypeError, ValueError, ObjectIntegrityError, OSError) as error:
            return EvaluationFailed("MissingCandidate", f"unreadable candidate: {error}")
        submission = CandidateSubmission(
            patch_ref=str(self.store.publish_bytes(candidate.patch)),
            tree_digest=candidate.tree_digest,
            baseline_tree_digest=candidate.baseline_tree_digest,
        )
        result = await evaluate_candidate(
            store=self.store,
            fixture=self.manifest,
            arm_id=arm_id,
            baseline=baseline,
            submission=submission,
            visible_regression=self.fixture.groups[0],
            hidden_regression_ref=self.manifest.hidden_tests[0],
            new_behavior_ref=self.manifest.hidden_tests[1],
            runner=self.runner,
        )
        return record_result(
            self.records, coordinate, result, empty_patch=candidate.patch == b"", started=started
        )


@dataclass
class WorkflowEditWorker:
    """``PierAdapter`` plus the live bridge description, keeping each cell's evidence.

    ``PierAdapter`` pins the bridge runtime only by its configuration ref. The
    live description re-reads the Smithers routing file, so ``execute_plan``'s
    configuration check before every cell refuses a routing change.
    """

    adapter: PierAdapter
    bridge: WorkflowEditBridgeClient
    store: ObjectStore
    records: dict[str, dict[str, Any]] = field(default_factory=dict)
    supports_cell_coordinates: bool = True

    def configuration(self, arm_id: str) -> dict[str, Any]:
        return {**self.adapter.configuration(arm_id), "runtime": self.bridge.configuration()}

    async def run_cell(self, *, input_value: Any, coordinate: CellCoordinate) -> WorkerResult:
        started_at = datetime.now(UTC).isoformat()
        started = time.monotonic()
        result = await self.adapter.run_cell(input_value=input_value, coordinate=coordinate)
        self.records[coordinate.id] = cell_record(
            self.store, result, started_at=started_at, seconds=time.monotonic() - started
        )
        return result


def cell_record(
    store: ObjectStore, result: WorkerResult, *, started_at: str, seconds: float
) -> dict[str, Any]:
    """The settled outcome and the raw evidence every SMOKE number is derived from."""
    if isinstance(result, WorkerSuccess):
        refs = {
            key: value for key, value in result.output.items()
            if isinstance(value, str) and value.startswith("sha256:")
        }
        trajectory_ref, patch_ref = refs.get("raw_trajectory_ref"), refs.get("patch_ref")
        outcome: dict[str, Any] = {"kind": "candidate"}
    else:
        trace = result.trace if isinstance(result.trace, dict) else {}
        refs = dict(trace.get("artifact_refs") or {})
        trajectory_ref = refs.get("trajectory.json")
        patch_ref = refs.get("stopped/candidate.patch")
        bridge_outcome = trace.get("bridge_outcome") or {}
        outcome = {
            "kind": bridge_outcome.get("kind", "worker_failure"),
            "cause": bridge_outcome.get("cause"),
            "error_type": result.error_type,
            "detail": result.message[:500],
        }
    accounting = result.accounting
    return {
        "started_at": started_at,
        "seconds": round(seconds, 3),
        "outcome": outcome,
        "accounting": {
            "coverage": accounting.coverage,
            "amount": accounting.amount,
            "usage": accounting.usage,
        },
        "artifact_refs": refs,
        "trajectory": (
            json.loads(envelope_bytes(store, trajectory_ref)) if trajectory_ref else None
        ),
        "patch": envelope_bytes(store, patch_ref).decode("utf-8") if patch_ref else None,
    }


@dataclass(frozen=True)
class Qualification:
    """The fixed inputs of one run; ``prepare`` derives everything authorized from them."""

    store: ObjectStore
    image: str
    routing_config: Path
    runs_root: Path
    run_label: str
    docker_client_version: str
    docker_server_version: str
    completion_for: Callable[[str], Any] | None = None
    cell_timeout_s: float = CELL_TIMEOUT_S

    def factory(self, routing_config: Path | None = None) -> SmithersFactory:
        return SmithersFactory(
            model=MODEL_ALIAS,
            machine=MACHINE,
            routing_config=routing_config or self.routing_config,
            dispatch_url=SMITHERS,
        )

    def bridge(self) -> WorkflowEditBridgeClient:
        return WorkflowEditBridgeClient(
            image=self.image,
            runs_root=self.runs_root,
            factory=self.factory(),
            run_label=self.run_label,
            timeout_s=self.cell_timeout_s,
            completion_for=self.completion_for,
        )

    def runner(self) -> DockerWorkflowRunner:
        return DockerWorkflowRunner(
            WorkflowRunnerSettings(
                image=self.image,
                toolchain="bun",
                docker_client_version=self.docker_client_version,
                docker_server_version=self.docker_server_version,
                command_timeout_s=30.0,
                deadline_s=600.0,
                candidate_timeout_s=120.0,
                max_output_bytes=1_000_000,
            )
        )


@dataclass
class Prepared:
    snapshot: StudySnapshot
    plan_bytes: bytes
    authorization: str
    worker: WorkflowEditWorker
    evaluator: CorrectnessEvaluator | CellEvaluator
    manifest: FixtureManifest | FixtureManifestV2


@dataclass(frozen=True)
class PlanKind:
    """What distinguishes one authorized workflow-edit plan from another."""

    task: str
    description: str
    payload_schema: str
    partition: str


SMOKE_PLAN = PlanKind(
    task="workflow_edit_wf13",
    description="wf-13 zero-paid repository-agent qualification smoke",
    payload_schema="https://assay.local/schemas/workflow-edit-wf13-correctness-v1.json",
    partition="qualification",
)


def bridge_worker(q: Qualification) -> tuple[WorkflowEditWorker, RuntimeProfile]:
    """The repository-agent worker every arm dispatches through, and its runtime."""
    bridge = q.bridge()
    configuration_ref = str(q.store.publish_json(bridge.configuration()))
    binding = RuntimeBinding(
        runtime_version="workflow-edit-wf13",
        image_digest=q.image,
        configuration_ref=configuration_ref,
        package_digest="sha256:" + "0" * 64,
    )
    adapter = PierAdapter(
        store=q.store,
        bridge=bridge,
        binding=binding,
        model_route=LOCAL_ROUTE.model_dump(mode="json"),
        trial_limits=trial_limits(bridge.limits, q.cell_timeout_s).model_dump(mode="json"),
        max_repository_files=MAX_REPOSITORY_FILES,
        max_repository_bytes=MAX_REPOSITORY_BYTES,
        worker_id="workflow-edit-repository-agent",
        package_layout="repository-agent",
    )
    runtime = RuntimeProfile(id="pier", version=binding.runtime_version,
                             configuration_ref=configuration_ref)
    return WorkflowEditWorker(adapter, bridge, q.store), runtime


def compile_workflow_plan(
    store: ObjectStore,
    kind: PlanKind,
    *,
    subjects: tuple[Subject, ...],
    arms: tuple[Arm, ...],
    realizations: tuple[Realization, ...],
    evaluator_configuration: dict[str, Any],
    runtime: RuntimeProfile,
    repeats: int,
    ceiling: ExecutionCeiling,
    check: Callable[[ExecutionPlanV3], None] | None = None,
) -> tuple[StudySnapshot, bytes]:
    """Snapshot and canonical 0.3.0 plan bytes; ``check`` runs before they are returned.

    The caller derives the authorization from the returned bytes, so a
    ``check`` that raises leaves nothing to authorize.
    """

    def publish(value: Any) -> str:
        return str(store.publish_json(value))

    identity = {
        "property": "functional_correctness",
        "target": "output",
        "technique": "deterministic",
        "evaluation_basis": {
            "kind": "invariant",
            "ref": publish({"categories": list(CORRECTNESS_CATEGORIES),
                            "definition": "Frozen visible, hidden regression and new-behavior "
                                          "groups pass on the reconstructed patch."}),
        },
        "epistemic_status": "proxy",
        "version": "1",
        "authority": "advisory",
    }
    schema = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "$id": kind.payload_schema,
        "allOf": [
            {"$ref": "https://paa.dev/paa-evidence-record.schema.json"},
            {"properties": {"verdict": {"properties": {
                "value": {"enum": list(CORRECTNESS_CATEGORIES)}}}}},
        ],
    }
    declaration = EvaluatorDeclaration(
        id="correctness",
        identity=identity,
        payload_schema=kind.payload_schema,
        payload_schema_ref=publish(schema),
        configuration=evaluator_configuration,
        basis_ref=publish({"invariant": "frozen test groups on the reconstructed patch"}),
        repeats=1,
    )
    task_declaration = {
        "task": kind.task,
        "version": 1,
        "description": kind.description,
        "boundary": {"input": "task_repository", "output": "candidate_patch"},
        "initial_position": "manual",
        "deployment": "shadow",
        "evaluators": [identity],
        "position_policy": {"manual": "offline", "hitl": "blocking"},
        "promotion": {
            "from": "manual", "to": "hitl", "report": f"{kind.task}_report",
            "window": {"kind": "cases", "size": 10}, "execution": "operator_approval",
        },
        "demotion": {
            "from": "hitl", "to": "manual", "trigger": "operator_decision",
            "window": {"kind": "cases", "size": 1},
        },
    }
    snapshot = StudySnapshot(
        subjects=subjects,
        arms=arms,
        realizations=realizations,
        evaluators=(declaration,),
        paa_task_ref=publish(task_declaration),
        pricing_catalog_ref=publish({"local": "unpriced: Smithers reports no billing"}),
        task_schema_ref=publish(paa_contracts.load_schema("paa-task")),
        evidence_schema_ref=publish(paa_contracts.load_schema("paa-evidence-record")),
        operating_schema_ref=publish(paa_contracts.load_schema("paa-operating-record")),
    )
    snapshot_ref = publish(snapshot.model_dump(mode="json"))
    # compile_plan references each declaration and the arm conditions directly.
    for item in (*snapshot.arms, *snapshot.evaluators):
        publish(item.model_dump(mode="json"))
    publish([arm.conditions for arm in snapshot.arms])
    base = compile_plan_v2(snapshot, snapshot_ref=snapshot_ref, worker_repeats=repeats,
                           runtime=runtime, concurrency=1)
    plan = ExecutionPlanV3.model_validate(
        {**base.model_dump(mode="json"), "schema_version": "assay-execution-plan/0.3.0",
         "ceiling": ceiling.model_dump(mode="json")}
    )
    if check is not None:
        check(plan)
    plan_bytes = canonical_json(plan.model_dump(mode="json"))
    store.publish_bytes(plan_bytes)
    return snapshot, plan_bytes


def prepare(q: Qualification, *, repeats: int, ceiling: ExecutionCeiling) -> Prepared:
    """The single-arm wf-13 smoke; its subject is refused by the study grid by design."""
    store = q.store
    fixture = load_fixture()
    worker, runtime = bridge_worker(q)
    manifest = fixture_manifest(
        store, fixture, image=q.image,
        routing_digest=q.factory().configuration()["routing_config_digest"],
    )
    evaluator = CorrectnessEvaluator(store, fixture, manifest, q.runner())
    subject_ref = str(store.publish_json(
        {"task": fixture.task, "fixture": fixture_identity(manifest)}
    ))
    realization_ref = str(store.publish_json(
        {"task": fixture.task, "repository": fixture.repository}
    ))
    snapshot, plan_bytes = compile_workflow_plan(
        store,
        SMOKE_PLAN,
        subjects=(Subject(id=SMOKE_EDIT_SUBJECT_ID, label="wf-13 smoke-edit task",
                          partition=SMOKE_PLAN.partition, digest=subject_ref,
                          payload_ref=subject_ref),),
        arms=(Arm(id=MESS_00, worker=worker.configuration(MESS_00),
                  intervention={"repository": "smoke-edit"}),),
        realizations=(Realization(subject_id=SMOKE_EDIT_SUBJECT_ID, arm_id=MESS_00,
                                  digest=realization_ref, artifact_ref=realization_ref),),
        evaluator_configuration=evaluator.configuration(),
        runtime=runtime,
        repeats=repeats,
        ceiling=ceiling,
    )
    return Prepared(
        snapshot=snapshot,
        plan_bytes=plan_bytes,
        authorization=digest_bytes(plan_bytes),
        worker=worker,
        evaluator=evaluator,
        manifest=manifest,
    )


async def run(prepared: Prepared, store: ObjectStore) -> dict[str, Any]:
    result = await execute_plan(
        plan_bytes=prepared.plan_bytes,
        authorization=prepared.authorization,
        snapshot=prepared.snapshot,
        store=store,
        workers={arm.id: prepared.worker for arm in prepared.snapshot.arms},
        evaluators={"correctness": prepared.evaluator},
    )
    manifest = result.manifest
    return {
        "plan_ref": digest_bytes(prepared.plan_bytes),
        "fixture_identity": fixture_identity(prepared.manifest),
        "fixture_manifest": prepared.manifest.model_dump(mode="json"),
        "worker_configuration": prepared.worker.configuration(MESS_00),
        "evaluator_configuration": prepared.evaluator.configuration(),
        "run": {
            "result": type(result).__name__,
            "error": None if not isinstance(result, RunFailed) else
            {"type": result.error_type, "message": result.message},
            "manifest_ref": None if result.manifest_ref is None else str(result.manifest_ref),
            "run_id": None if manifest is None else manifest.run_id,
            "status": None if manifest is None else manifest.status,
            "missing_coordinates": [] if manifest is None else list(manifest.missing_coordinates),
        },
        "cells": prepared.worker.records,
        "evaluations": prepared.evaluator.records,
    }


def machine_status(name: str = MACHINE) -> str:
    with urllib.request.urlopen(f"{SMITHERS}/machines", timeout=10) as response:
        machines = json.loads(response.read())["machines"]
    return str(next(item["status"] for item in machines if item["name"] == name))


def wake(name: str = MACHINE, *, limit_s: float = 900.0) -> dict[str, Any]:
    """Wake through Smithers and time it; an awake machine is recorded, not timed."""
    before = machine_status(name)
    if before == "awake":
        return {"machine": name, "status_before": before, "cold_wake_seconds": None}
    started = time.monotonic()
    request = urllib.request.Request(f"{SMITHERS}/machines/{name}/wake", method="POST")
    # Smithers answers only once the wake has finished: "awake" or "failed".
    with urllib.request.urlopen(request, timeout=limit_s) as response:
        reported = json.loads(response.read())["status"]
    if reported != "awake":
        raise RuntimeError(f"Smithers reported wake {reported!r} for {name}")
    while machine_status(name) != "awake":
        if time.monotonic() - started > limit_s:
            raise TimeoutError(f"{name} did not wake within {limit_s}s")
        time.sleep(2)
    return {
        "machine": name,
        "status_before": before,
        "cold_wake_seconds": round(time.monotonic() - started, 1),
        "observed_at": datetime.now(UTC).isoformat(),
    }


def hosted_pricing(model: str = HOSTED_MODEL) -> dict[str, Any]:
    """Public OpenRouter catalogue entry for the proposed hosted model; no key, no call."""
    with urllib.request.urlopen("https://openrouter.ai/api/v1/models", timeout=30) as response:
        catalogue = json.loads(response.read())
    entry = next(item for item in catalogue["data"] if item["id"] == model)
    with urllib.request.urlopen(
        f"https://openrouter.ai/api/v1/models/{model}/endpoints", timeout=30
    ) as response:
        endpoints = json.loads(response.read())
    return {
        "fetched_at": datetime.now(UTC).isoformat(),
        "model": entry,
        "endpoints": endpoints.get("data", {}).get("endpoints", []),
    }


def write_evidence(name: str, value: Mapping[str, Any]) -> Path:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    path = EVIDENCE / f"{name}.json.gz"
    # mtime=0 keeps the compressed bytes a pure function of the evidence.
    path.write_bytes(gzip.compress(canonical_json(dict(value)), mtime=0))
    return path


def read_evidence(name: str) -> dict[str, Any]:
    value: dict[str, Any] = json.loads(gzip.decompress((EVIDENCE / f"{name}.json.gz").read_bytes()))
    return value


def _qualification(args: argparse.Namespace, label: str) -> Qualification:
    return Qualification(
        store=ObjectStore(args.store),
        image=args.image,
        routing_config=args.routing_config,
        runs_root=args.store.parent / "runs",
        run_label=label,
        docker_client_version=args.docker_client_version,
        docker_server_version=args.docker_server_version,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("smoke", "probes", "wake", "pricing", "diagnose"))
    parser.add_argument("--image", required=False, default="")
    parser.add_argument("--store", type=Path, default=Path.home() / ".assay-wf13" / "store")
    parser.add_argument("--routing-config", type=Path,
                        default=Path.home() / "codes/rol/smithers/routing_config.yaml")
    parser.add_argument("--repeats", type=int, default=20)
    parser.add_argument("--docker-client-version", default="29.9.0")
    parser.add_argument("--docker-server-version", default="29.1.2")
    args = parser.parse_args()
    if args.command == "wake":
        print(write_evidence("wake", wake()))
    elif args.command == "pricing":
        print(write_evidence("pricing", hosted_pricing()))
    elif args.command == "diagnose":
        scratch = args.store.parent / "diagnose"
        scratch.mkdir(parents=True, exist_ok=True)
        print(write_evidence("diagnosis", diagnose(read_evidence("smoke"), scratch=scratch)))
    elif args.command == "smoke":
        label = f"wf13-smoke-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
        q = _qualification(args, label)
        warm = wake()
        ceiling = ExecutionCeiling(
            max_cells=args.repeats,
            max_wall_time_seconds=args.repeats * (CELL_TIMEOUT_S + 600.0),
            max_fleet_occupancy=1,
        )
        prepared = prepare(q, repeats=args.repeats, ceiling=ceiling)
        evidence = asyncio.run(run(prepared, q.store))
        evidence.update({"label": label, "image": args.image, "wake": warm,
                         "ceiling": ceiling.model_dump(mode="json")})
        print(write_evidence("smoke", evidence))
    else:
        from workflow_edit.probes import run_probes

        label = f"wf13-probes-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
        print(write_evidence("probes", asyncio.run(run_probes(_qualification(args, label)))))


if __name__ == "__main__":
    main()
