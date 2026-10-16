"""Compile and run the pilot's Tier 1 grid.

The default ``scripted`` command executes every planned cell with sealed,
model-free traces. ``live`` requires an explicit route and image.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any, cast

from workflow_edit.bridge import LOCAL_ROUTE

from assay.adapters.smithers import SmithersFactory
from assay.canonical import digest_bytes
from assay.execution import EvaluationResult, RunFailed, WorkerResult, WorkerSuccess, execute_plan
from assay.models import CellCoordinate, EvaluationCoordinate, RuntimeProfile
from assay.store import ObjectStore
from verification_pilot.arms import ALL_ARMS
from verification_pilot.bridge import (
    DockerTmpfsStagingStorage,
    DockerTmpfsToolSandbox,
    PilotBridgeClient,
    SandboxLimits,
    SmithersTurnCompletion,
    create_pilot_agent,
    pilot_worker,
)
from verification_pilot.evaluation import PilotEvaluator
from verification_pilot.fixture import load_fixture
from verification_pilot.ground_truth import GroundTruth, Location, Remnant, build_specimens
from verification_pilot.settings import VerificationPilotSettings
from verification_pilot.study import PilotSubject, PreparedPilot, compile_pilot_plan, pilot_subjects


def measure_local_on_policy(
    *, image: str, runs_root: Path, routing_config: Path
) -> dict[str, Any]:
    """Generate one migration's four blocks outside the cell runtime."""
    fixture = load_fixture()
    subjects = [s for s in pilot_subjects(fixture)
                if s.migration.name == "json_value" and s.rotation == 0]
    factory = SmithersFactory(model="qwen-coder-32b", machine="mcbain",
                              routing_config=routing_config, dispatch_url="http://willie:8900")
    authorized = factory.configuration()
    results: list[dict[str, Any]] = []
    for subject in subjects:
        share = sorted(path for path, group in subject.migration.ownership_groups.items()
                       if group == subject.group)
        agent = create_pilot_agent(
            settings=VerificationPilotSettings(), image=image, runs_root=runs_root,
            model_route=LOCAL_ROUTE,
            completion=SmithersTurnCompletion(
                factory, f"on-policy-v2:{runs_root.name}:{subject.id}",
                                               authorized=authorized),
            next_user_turns=("Review the migration.", "Submit your final finding."),
            sandbox_factory=partial(DockerTmpfsToolSandbox, limits=SandboxLimits()),
            storage_factory=DockerTmpfsStagingStorage,
        )
        instruction = (
            f"Repair the remaining {subject.migration.old_symbol} spelling in your "
            f"assigned share only: {', '.join(share)}. Run bun test, then submit "
            "an honest finding. Do not edit other files."
        )
        package = {"instruction.md": instruction,
                   **{f"workspace/{path}": content for path, content
                      in subject.repository.items()}}
        try:
            outcome = agent.run_cell(cell_id=f"on-policy:{subject.id}:w0", package=package)
            after = outcome.files
            changed = sorted(path for path in set(subject.repository) | set(after)
                             if subject.repository.get(path, "").encode() != after.get(path, b""))
            outside_share = any(path not in share for path in changed)
            old_left = any(subject.migration.old_symbol in after.get(path, b"").decode(
                errors="replace") for path in share)
            with tempfile.TemporaryDirectory(prefix="vp-on-policy-") as temporary:
                root = Path(temporary)
                for path, content in after.items():
                    target = root / path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(content)
                installed = subprocess.run(["bun", "install", "--frozen-lockfile"],
                                           cwd=root, capture_output=True, text=True,
                                           timeout=180, check=False)
                tested = (subprocess.run(["bun", "test"], cwd=root, capture_output=True,
                                         text=True, timeout=180, check=False)
                          if installed.returncode == 0 else installed)
            tests_pass = installed.returncode == 0 and tested.returncode == 0
            results.append({"subject_id": subject.id,
                            "discard": outside_share or old_left or not tests_pass,
                            "changed_paths": changed, "outside_share": outside_share,
                            "old_symbol_in_share": old_left, "tests_pass": tests_pass,
                            "tests_tail": tested.stdout[-300:] + tested.stderr[-300:],
                            "trajectory_sha256": digest_bytes(json.dumps(
                                outcome.trajectory, sort_keys=True).encode()),
                            "block": outcome.summary})
        except Exception as error:
            results.append({"subject_id": subject.id, "discard": True,
                            "error": f"{type(error).__name__}: {error}"})
    return {"route": "smithers-local", "migration": "json_value",
            "discarded": sum(bool(item["discard"]) for item in results),
            "generated": len(results), "blocks": results}


def subject_truth(subject: PilotSubject) -> GroundTruth:
    """Locate the single injected old spelling by comparing against the renamed tree."""
    fixture = load_fixture()
    original = fixture.renamed[subject.migration.name][subject.location].splitlines()
    changed = subject.repository[subject.location].splitlines()
    lines = [index for index, (left, right) in enumerate(zip(original, changed, strict=True), 1)
             if left != right]
    if len(lines) != 1:
        raise ValueError(f"{subject.id}: expected one changed line")
    location = Location(subject.migration.name, subject.location, lines[0],
                        subject.migration.old_symbol, subject.group)
    remnant = Remnant("fallback_object_key" if subject.migration.kind == "object_key"
                      else "stale_type_reference", location)
    _, fixture_truth = build_specimens(fixture)
    return GroundTruth(cast(Any, (remnant, remnant, remnant)), fixture_truth.decoys)


@dataclass
class GridEvaluator:
    store: ObjectStore
    subjects: dict[str, PilotSubject]
    truths: dict[str, GroundTruth]

    def configuration(self) -> dict[str, Any]:
        from verification_pilot.evaluation import EVALUATOR_IDS

        return {"id_set": list(EVALUATOR_IDS), "version": "section-10-v1"}

    async def evaluate(self, *, input_value: Any, output: Any,
                       coordinate: EvaluationCoordinate) -> EvaluationResult:
        subject_id = coordinate.cell_id.split(":", 1)[0]
        subject = self.subjects[subject_id]
        evaluator = PilotEvaluator(self.store, subject.migration, self.truths[subject_id])
        return await evaluator.evaluate(input_value=input_value, output=output,
                                        coordinate=coordinate)


@dataclass
class ScriptedWorker:
    store: ObjectStore
    supports_cell_coordinates: bool = True

    def configuration(self, arm_id: str) -> dict[str, Any]:
        return {"id": "pilot-scripted", "version": "1"}

    async def run_cell(self, *, input_value: Any, coordinate: CellCoordinate) -> WorkerResult:
        """Produce one deterministic three-turn trace with no model dispatch."""
        submissions = [
            {"title": "scripted verification", "body": "checking migration"},
            {"verdict": "incomplete", "remaining_v1": "one remnant",
             "checks_performed": "none"},
            {"verdict": "incomplete", "remaining_v1": "one remnant",
             "checks_performed": "none"},
        ]
        trajectory: dict[str, Any] = {"turns": [
            {"turn": f"T{index}", "tool_calls": [], "submission": submission,
             "workspace_diff": None}
            for index, submission in enumerate(submissions, 1)
        ]}

        def seal(value: dict[str, Any]) -> str:
            content = json.dumps(value, sort_keys=True).encode()
            return str(self.store.publish_json({
                "content_base64": base64.b64encode(content).decode()}))

        return WorkerSuccess({
            "cell_id": coordinate.id,
            "raw_trajectory_ref": seal(trajectory),
            "result_ref": seal({"exit_status": "Submitted", "submissions": submissions}),
        })


async def run_scripted(store: ObjectStore) -> tuple[PreparedPilot, Any]:
    subjects = pilot_subjects()
    runtime = RuntimeProfile(id="scripted", version="1",
                             configuration_ref=str(store.publish_json({"scripted": True})))
    worker = ScriptedWorker(store)
    prepared = compile_pilot_plan(store, runtime,
                                  worker_configuration=worker.configuration("t1-native"),
                                  subjects_data=subjects)
    by_id = {subject.id: subject for subject in subjects}
    evaluator = GridEvaluator(store, by_id,
                              {subject.id: subject_truth(subject) for subject in subjects})
    result = await execute_plan(
        plan_bytes=prepared.plan_bytes, authorization=prepared.authorization,
        snapshot=prepared.snapshot, store=store,
        workers={arm.id: worker for arm in prepared.snapshot.arms},
        evaluators={declaration.id: evaluator for declaration in prepared.snapshot.evaluators},
    )
    return prepared, result


async def run_live(
    store: ObjectStore, *, image: str, runs_root: Path, routing_config: Path,
    route: str, api_key: str | None, smoke: bool = False
) -> tuple[PreparedPilot, Any]:
    subjects = pilot_subjects()
    if route != "smithers-local":
        raise ValueError("frontier route is supplied by the vp-frontier-route cohort")
    factory = SmithersFactory(model="qwen-coder-32b", machine="mcbain",
                              routing_config=routing_config, dispatch_url="http://willie:8900")
    bridge = PilotBridgeClient(
        image=image, runs_root=runs_root, run_label="verification-pilot-tier1",
        model_route=LOCAL_ROUTE, subjects={s.id: s for s in subjects},
        settings=VerificationPilotSettings(), factory=factory, api_key=api_key,
    )
    worker, runtime = pilot_worker(store, bridge)
    smoke_ids = tuple(s.id for s in subjects if s.rotation == 0 and
                      s.migration.name in {"json_value", "stage_instance_id"})
    prepared = compile_pilot_plan(store, runtime,
                                  worker_configuration=worker.configuration("t1-native"),
                                  worker_configurations={a: worker.configuration(a)
                                                         for a in ALL_ARMS},
                                  subjects_data=subjects,
                                  active_subject_ids=smoke_ids if smoke else None)
    by_id = {subject.id: subject for subject in subjects}
    evaluator = GridEvaluator(store, by_id,
                              {subject.id: subject_truth(subject) for subject in subjects})
    result = await execute_plan(
        plan_bytes=prepared.plan_bytes, authorization=prepared.authorization,
        snapshot=prepared.snapshot, store=store,
        workers={arm.id: worker for arm in prepared.snapshot.arms},
        evaluators={declaration.id: evaluator for declaration in prepared.snapshot.evaluators},
    )
    return prepared, result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("scripted", "live", "live-smoke",
                                            "on-policy-local"))
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--image", default="")
    parser.add_argument("--runs-root", type=Path, default=Path("/tmp/verification-pilot-runs"))
    parser.add_argument("--routing-config", type=Path, default=Path("/tmp/routing.yaml"))
    parser.add_argument("--route", default="smithers-local")
    args = parser.parse_args()
    store = ObjectStore(args.store)
    if args.command == "on-policy-local":
        if not args.image:
            parser.error("on-policy generation requires --image")
        evidence = measure_local_on_policy(
            image=args.image, runs_root=args.runs_root,
            routing_config=args.routing_config)
        evidence["evidence_ref"] = str(store.publish_json(evidence))
        print(json.dumps(evidence))
        return
    if args.command == "scripted":
        prepared, result = asyncio.run(run_scripted(store))
    else:
        if not args.image:
            parser.error("live runs require --image")
        prepared, result = asyncio.run(run_live(
            store, image=args.image, runs_root=args.runs_root,
            routing_config=args.routing_config, route=args.route,
            api_key=os.getenv("OPENROUTER_API_KEY"), smoke=args.command == "live-smoke",
        ))
    print(json.dumps({"plan_ref": prepared.authorization,
                      "result": type(result).__name__,
                      "error": result.message if isinstance(result, RunFailed) else None,
                      "manifest_ref": str(result.manifest_ref) if result.manifest_ref else None}))


if __name__ == "__main__":
    main()
