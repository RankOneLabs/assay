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
import uuid
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from functools import partial
from pathlib import Path
from typing import Any, cast

from workflow_edit.bridge import LOCAL_ROUTE

from assay.adapters.smithers import SmithersFactory
from assay.canonical import digest_bytes
from assay.execution import (
    EvaluationResult,
    RunFailed,
    RunResult,
    RunSucceeded,
    WorkerResult,
    WorkerSuccess,
    execute_plan,
)
from assay.models import CellCoordinate, EvaluationCoordinate, RuntimeProfile
from assay.store import ObjectStore
from verification_pilot.arms import ALL_ARMS
from verification_pilot.bridge import (
    DockerTmpfsStagingStorage,
    DockerTmpfsToolSandbox,
    ModelRoute,
    PilotBridgeClient,
    SandboxLimits,
    SmithersTurnCompletion,
    SpendGate,
    create_pilot_agent,
    pilot_worker,
)
from verification_pilot.evaluation import PilotEvaluator
from verification_pilot.fixture import load_fixture
from verification_pilot.fixtures import base_subjects
from verification_pilot.ground_truth import GroundTruth
from verification_pilot.ground_truth import subject_truth as fixture_subject_truth
from verification_pilot.inputs import T2_TEXT, T3_TEXT
from verification_pilot.observations import RecordedTrace, observe
from verification_pilot.settings import VerificationPilotSettings
from verification_pilot.study import (
    PilotSubject,
    PreparedPilot,
    compile_pilot_plan,
    pilot_subjects,
    smoke_subject_ids,
)

# Screening routes for the paid arm; see DECISIONS.md D17. Each name is one exact
# ModelRoute whose pinned turn settings live in the bridge's PAID_TURN_ROUTES.
PAID_ROUTES: dict[str, tuple[str, str]] = {
    "sonnet-5.5": ("anthropic/claude-sonnet-5.5", "amazon-bedrock"),
    "gpt-6.1-sol": ("openai/gpt-6.1-sol", "azure/us"),
    "gpt-6.1-sol-eu": ("openai/gpt-6.1-sol", "azure/eu"),
    "gemini-4-argon": ("google/gemini-4-argon", "google-vertex/global"),
    "qwen3.8": ("qwen/qwen3.8-2.4t-a95b", "siliconflow/fp8"),
    "deepseek-v4-pro": ("deepseek/deepseek-v4-pro", "siliconflow/fp8"),
    "kimi-k2.7-code": ("moonshotai/kimi-k2.7-code", "moonshotai/int4"),
    "haiku-5.5": ("anthropic/claude-haiku-5.5", "amazon-bedrock"),
    "gpt-6-luna": ("openai/gpt-6-luna", "azure"),
    "gemini-3.8-flash": ("google/gemini-3.8-flash", "google-vertex/global"),
    "qwen3.8-27b": ("qwen/qwen3.8-27b", "deepinfra/bf16"),
    "gpt-oss-20b": ("openai/gpt-oss-20b", "deepinfra/bf16"),
    "ministral-14b": ("mistralai/ministral-14b-2512", "mistral/zdr"),
}


def paid_model_route(name: str | None) -> ModelRoute:
    """The exact OpenRouter route for one named screening route."""
    if name not in PAID_ROUTES:
        raise ValueError(f"the paid route requires one of {sorted(PAID_ROUTES)}")
    model, provider = PAID_ROUTES[name]
    return ModelRoute(model=model, provider=provider)  # type: ignore[arg-type]


def measure_on_policy(
    *, image: str, runs_root: Path, routing_config: Path, route: str,
    api_key: str | None = None, spend_gate: SpendGate | None = None,
    paid_route: str | None = None,
) -> dict[str, Any]:
    """Generate one migration's three ownership blocks outside the cell runtime."""
    fixture = load_fixture()
    subjects = [s for s in pilot_subjects(fixture)
                if s.migration.name == "stage_run_id" and s.group is not None]
    if route == "smithers-local":
        if api_key is not None:
            raise ValueError("local route cannot receive an OpenRouter credential")
        if spend_gate is not None:
            raise ValueError("the zero-paid local route takes no spend gate")
        local_factory = SmithersFactory(
            model="qwen-coder-32b", machine="mcbain",
            routing_config=routing_config, dispatch_url="http://willie:8900",
        )
        factory: SmithersFactory | None = local_factory
        model_route = LOCAL_ROUTE
        authorized = local_factory.configuration()
    elif route == "openrouter":
        if not api_key or any(char.isspace() for char in api_key):
            raise ValueError("OPENROUTER_API_KEY is required for the paid route")
        if spend_gate is None:
            raise ValueError("the paid route requires an operator spend cap")
        factory = None
        model_route = paid_model_route(paid_route)
        authorized = None
    else:
        raise ValueError(f"unknown model route: {route}")
    results: list[dict[str, Any]] = []
    for subject in subjects:
        share = sorted(path for path, group in subject.migration.ownership_groups.items()
                       if group == subject.group)
        agent = create_pilot_agent(
            settings=VerificationPilotSettings(), image=image, runs_root=runs_root,
            model_route=model_route,
            completion=(SmithersTurnCompletion(
                factory, f"on-policy-v2:{runs_root.name}:{subject.id}",
                authorized=authorized) if factory is not None else None),
            next_user_turns=(T2_TEXT, T3_TEXT),
            api_key=api_key,
            sandbox_factory=partial(DockerTmpfsToolSandbox, limits=SandboxLimits()),
            storage_factory=DockerTmpfsStagingStorage,
            spend_gate=spend_gate,
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
    return {"route": route, "model": model_route.model, "migration": "stage_run_id",
            "discarded": sum(bool(item["discard"]) for item in results),
            "attempted": len(results),
            "submitted": sum("block" in item for item in results),
            "spend": spend_gate.record() if spend_gate is not None else None,
            "blocks": results}


def measure_local_on_policy(
    *, image: str, runs_root: Path, routing_config: Path
) -> dict[str, Any]:
    """Compatibility entry point for the local qualification command."""
    return measure_on_policy(image=image, runs_root=runs_root,
                             routing_config=routing_config, route="smithers-local")


def subject_truth(subject: PilotSubject) -> GroundTruth:
    """Find the operator-held truth for one fixture-derived subject."""
    fixture = load_fixture()
    source = next(item for item in base_subjects() if item.id == subject.id)
    return fixture_subject_truth(source, fixture)


@dataclass
class GridEvaluator:
    store: ObjectStore
    subjects: dict[str, PilotSubject]
    truths: dict[str, GroundTruth]

    def configuration(self) -> dict[str, Any]:
        from verification_pilot.evaluation import EVALUATOR_IDS

        return {"id_set": list(EVALUATOR_IDS), "version": "fixture-derived-v2"}

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
             "workspace_diff": "",
             "usage": {"prompt_tokens": 0, "completion_tokens": 0,
                       "requests": 0, "cost_usd": None}}
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


def save_run_trace(
    store: ObjectStore, result: RunResult, archive_root: Path,
    subjects: Mapping[str, PilotSubject],
) -> Path | None:
    """Save cell traces and derived measures under raw/runs/<run_id>."""
    if result.manifest is None or result.manifest_ref is None:
        return None
    return archive_manifest(store, str(result.manifest_ref), archive_root, subjects)


def _pilot_measures(trace: Any, subject: Any) -> list[dict[str, Any]]:
    return [asdict(item) for item in observe(cast(RecordedTrace, trace), subject)]


def archive_manifest(
    store: ObjectStore, manifest_ref: str, archive_root: Path,
    subjects: Mapping[str, Any],
    measure: Callable[[Any, Any], list[dict[str, Any]]] = _pilot_measures,
) -> Path:
    """Archive one stored run manifest; a run whose save failed is re-archived from the store.

    ``measure`` derives each cell's measures from its trajectory and subject;
    the pilot's own observations are the default.
    """
    manifest_bytes = store.read_bytes(manifest_ref)
    manifest = json.loads(manifest_bytes)
    destination: Path = archive_root / str(manifest["run_id"])
    destination.mkdir(parents=True, exist_ok=False)
    (destination / "manifest.json").write_bytes(manifest_bytes)
    traces = destination / "traces"
    traces.mkdir()
    index: dict[str, dict[str, str | None]] = {}
    for number, (cell_id, record_ref) in enumerate(sorted(manifest["execution_records"].items()),
                                                   1):
        record = json.loads(store.read_bytes(record_ref))
        entry: dict[str, str | None] = {"record_ref": str(record_ref), "status": record["status"]}
        trace_ref = record.get("trace_ref")
        if trace_ref is not None:
            trace_name = f"{number:03d}-worker.json"
            (traces / trace_name).write_bytes(store.read_bytes(trace_ref))
            entry["worker_trace"] = trace_name
        output_ref = record.get("output_ref")
        output = json.loads(store.read_bytes(output_ref)) if output_ref is not None else None
        raw_ref = output.get("raw_trajectory_ref") if output is not None else None
        if raw_ref is None and trace_ref is not None:
            worker_trace = json.loads(store.read_bytes(trace_ref))
            raw_ref = worker_trace.get("artifact_refs", {}).get("trajectory.json")
        if raw_ref is not None:
            envelope = json.loads(store.read_bytes(raw_ref))
            trajectory = base64.b64decode(envelope["content_base64"], validate=True)
            trace_name = f"{number:03d}-trajectory.json"
            (traces / trace_name).write_bytes(trajectory)
            entry["trajectory"] = trace_name
            trace = cast(RecordedTrace, json.loads(trajectory))
            subject_id = cell_id.split(":", 1)[0]
            measures = measure(trace, subjects[subject_id])
            measures_name = f"{number:03d}-measures.json"
            (traces / measures_name).write_text(
                json.dumps(measures, sort_keys=True, indent=2) + "\n", encoding="utf-8"
            )
            entry["measures"] = measures_name
        index[cell_id] = entry
    (destination / "index.json").write_text(
        json.dumps(index, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    return destination


def remeasure_archive(archive: Path, subjects: Mapping[str, PilotSubject]) -> int:
    """Re-derive every archived measures file from its own trajectory (D18).

    Measures are a pure function of a trajectory and its subject, so a
    measure-definition change re-scores a recorded run without a re-run.
    """
    index = json.loads((archive / "index.json").read_text(encoding="utf-8"))
    rewritten = 0
    for cell_id, entry in sorted(index.items()):
        if "trajectory" not in entry or "measures" not in entry:
            continue
        trace = cast(RecordedTrace, json.loads(
            (archive / "traces" / entry["trajectory"]).read_text(encoding="utf-8")))
        measures = [asdict(item) for item in observe(trace, subjects[cell_id.split(":", 1)[0]])]
        dated_measures_path(archive / "traces" / entry["measures"]).write_text(
            json.dumps(measures, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        rewritten += 1
    return rewritten


def dated_measures_path(original: Path) -> Path:
    """Choose a new measures path without replacing archived evidence."""
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    return original.with_name(f"{original.stem}-{stamp}-{uuid.uuid4().hex}{original.suffix}")


async def run_scripted(
    store: ObjectStore, *, archive_root: Path | None = None
) -> tuple[PreparedPilot, Any]:
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
    if isinstance(result, RunFailed | RunSucceeded):
        save_run_trace(store, result, archive_root or store.root.parent / "runs", by_id)
    return prepared, result


async def run_live(
    store: ObjectStore, *, image: str, runs_root: Path, routing_config: Path,
    route: str, smoke: bool = False, api_key: str | None = None,
    archive_root: Path | None = None, spend_gate: SpendGate | None = None,
    paid_route: str | None = None,
) -> tuple[PreparedPilot, Any]:
    subjects = pilot_subjects()
    if route == "smithers-local":
        if api_key is not None:
            raise ValueError("local route cannot receive an OpenRouter credential")
        factory: SmithersFactory | None = SmithersFactory(
            model="qwen-coder-32b", machine="mcbain",
            routing_config=routing_config, dispatch_url="http://willie:8900",
        )
        model_route = LOCAL_ROUTE
    elif route == "openrouter":
        if not api_key or any(char.isspace() for char in api_key):
            raise ValueError("OPENROUTER_API_KEY is required for the paid route")
        factory = None
        model_route = paid_model_route(paid_route)
    else:
        raise ValueError(f"unknown model route: {route}")
    bridge = PilotBridgeClient(
        image=image, runs_root=runs_root, run_label="verification-pilot-tier1",
        model_route=model_route, subjects={s.id: s for s in subjects},
        settings=VerificationPilotSettings(), factory=factory, api_key=api_key,
        spend_gate=spend_gate,
    )
    worker, runtime = pilot_worker(store, bridge)
    smoke_ids = smoke_subject_ids(subjects)
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
    if isinstance(result, RunFailed | RunSucceeded):
        destination = save_run_trace(store, result, archive_root or store.root.parent / "runs",
                                     by_id)
        if destination is not None and spend_gate is not None:
            (destination / "spend.json").write_text(
                json.dumps(spend_gate.record(), sort_keys=True, indent=2) + "\n",
                encoding="utf-8")
    return prepared, result


def _spend_cap(value: str) -> Decimal:
    try:
        cap = Decimal(value)
    except InvalidOperation as error:
        raise argparse.ArgumentTypeError("--max-spend-usd must be a dollar amount") from error
    if not cap.is_finite() or cap <= 0:
        raise argparse.ArgumentTypeError("--max-spend-usd must be positive")
    return cap


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("scripted", "live", "live-smoke",
                                            "on-policy-local", "on-policy-paid", "remeasure",
                                            "archive"))
    parser.add_argument("--store", type=Path)
    parser.add_argument("--archive", type=Path, action="append", default=[],
                        help="raw/runs/<run_id> directory to re-derive measures for")
    parser.add_argument("--manifest-ref", default=None,
                        help="stored run manifest to archive under raw/runs")
    parser.add_argument("--image", default="")
    parser.add_argument("--runs-root", type=Path, default=Path("/tmp/verification-pilot-runs"))
    parser.add_argument("--routing-config", type=Path, default=Path("/tmp/routing.yaml"))
    parser.add_argument("--route", choices=("smithers-local", "openrouter"),
                        default="smithers-local")
    parser.add_argument("--paid-route", choices=sorted(PAID_ROUTES), default=None,
                        help="named OpenRouter screening route; required on the paid route")
    parser.add_argument("--max-spend-usd", type=_spend_cap, default=None,
                        help="run-wide dollar cap; required on the paid route")
    args = parser.parse_args()
    if args.command == "remeasure":
        if not args.archive:
            parser.error("remeasure requires --archive")
        by_id = {subject.id: subject for subject in pilot_subjects()}
        print(json.dumps({str(path): remeasure_archive(path, by_id) for path in args.archive}))
        return
    if args.store is None:
        parser.error("--store is required")
    if args.command == "archive":
        if args.manifest_ref is None:
            parser.error("archive requires --manifest-ref")
        by_id = {subject.id: subject for subject in pilot_subjects()}
        root = Path(__file__).resolve().parent / "raw" / "runs"
        print(json.dumps({"archive": str(archive_manifest(
            ObjectStore(args.store), args.manifest_ref, root, by_id))}))
        return
    paid = args.command == "on-policy-paid" or (
        args.command in {"live", "live-smoke"} and args.route == "openrouter")
    if paid and args.max_spend_usd is None:
        parser.error("the paid route requires --max-spend-usd")
    if not paid and args.max_spend_usd is not None:
        parser.error("--max-spend-usd applies only to the paid route")
    if paid and args.paid_route is None:
        parser.error("the paid route requires --paid-route")
    if not paid and args.paid_route is not None:
        parser.error("--paid-route applies only to the paid route")
    spend_gate = SpendGate(args.max_spend_usd) if paid else None
    store = ObjectStore(args.store)
    archive_root = Path(__file__).resolve().parent / "raw" / "runs"
    if args.command in {"on-policy-local", "on-policy-paid"}:
        if not args.image:
            parser.error("on-policy generation requires --image")
        probe_route = "openrouter" if args.command == "on-policy-paid" else "smithers-local"
        evidence = measure_on_policy(
            image=args.image, runs_root=args.runs_root,
            routing_config=args.routing_config, route=probe_route,
            api_key=os.environ.get("OPENROUTER_API_KEY") if probe_route == "openrouter" else None,
            spend_gate=spend_gate, paid_route=args.paid_route,
        )
        evidence["evidence_ref"] = str(store.publish_json(evidence))
        print(json.dumps(evidence))
        return
    if args.command == "scripted":
        prepared, result = asyncio.run(run_scripted(store, archive_root=archive_root))
    else:
        if not args.image:
            parser.error("live runs require --image")
        prepared, result = asyncio.run(run_live(
            store, image=args.image, runs_root=args.runs_root,
            routing_config=args.routing_config, route=args.route,
            smoke=args.command == "live-smoke",
            api_key=os.environ.get("OPENROUTER_API_KEY") if args.route == "openrouter" else None,
            archive_root=archive_root, spend_gate=spend_gate, paid_route=args.paid_route,
        ))
    print(json.dumps({"plan_ref": prepared.authorization,
                      "result": type(result).__name__,
                      "error": result.message if isinstance(result, RunFailed) else None,
                      "manifest_ref": str(result.manifest_ref) if result.manifest_ref else None,
                      "spend": spend_gate.record() if spend_gate is not None else None}))


if __name__ == "__main__":
    main()
