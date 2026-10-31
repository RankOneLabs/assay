"""Operator entry point for qualified extension launches."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

from assay_pier_bridge import protocol as bridge_protocol
from verification_pilot.budget import SpendGate
from workflow_edit.bridge import SmithersTurnCompletion, trial_limits, turn_idempotency_key

from assay.adapters.pier import PierAdapter
from assay.adapters.smithers import SmithersFactory
from assay.canonical import canonical_json, digest_bytes
from assay.execution import AdmissionHalt, WorkerFailure, WorkerResult
from assay.investigations.workflow_correctness import DockerWorkflowRunner, WorkflowRunnerSettings
from assay.models import (
    CellCoordinate,
    ExecutionCeiling,
    ExecutionPlanV3,
    RuntimeProfile,
    parse_execution_plan,
)
from assay.pier_protocol import RuntimeBinding
from assay.planning import authorize
from assay.store import ObjectStore
from code_extension import qualify
from code_extension.bridge import ExtensionBridgeClient
from code_extension.budget import AttemptJournal, RequestBudget
from code_extension.config import RunConfiguration
from code_extension.dispatch import cell_idempotency_key
from code_extension.fixture import PILOT
from code_extension.fixtures import load_scenario
from code_extension.study import PreparedStudy, load_qualified_study_fixture, plan_study, run_study


class LaunchRefused(ValueError):
    """A launch gate named an operator-repairable blocker."""


@dataclass
class ExtensionStudyWorker:
    """One declared arm, with a frozen bridge for each chosen scenario."""

    arm_id: str
    bridges: dict[str, ExtensionBridgeClient]
    adapters: dict[str, PierAdapter]
    config_digest: str
    journal: AttemptJournal | None = None
    gate: SpendGate | None = None
    request_bound: Decimal | None = None
    supports_cell_coordinates: bool = True

    def configuration(self, arm_id: str) -> dict[str, Any]:
        if arm_id != self.arm_id:
            raise LaunchRefused("arm identity differs from frozen worker")
        return {
            "id": "code-extension-runner",
            "version": "ce-v1",
            "config_digest": self.config_digest,
            "scenarios": {
                key: {
                    "adapter": self.adapters[key].configuration(arm_id),
                    "bridge": bridge.configuration(),
                }
                for key, bridge in sorted(self.bridges.items())
            },
        }

    async def run_cell(self, *, input_value: Any, coordinate: CellCoordinate) -> WorkerResult:
        if coordinate.subject_id not in self.adapters or coordinate.arm_id != self.arm_id:
            raise LaunchRefused("coordinate is not one of the plan's declared cells")
        if self.journal is None or self.gate is None or self.request_bound is None:
            raise LaunchRefused("attempt budget and durable journal are required")
        if self.gate.halt is not None:
            raise AdmissionHalt(self.gate.halt, "run spending gate halted")
        bridge = self.bridges[coordinate.subject_id]
        attempt_id = cell_idempotency_key(bridge.run_label, coordinate)
        self.journal.claim_attempt(coordinate.id, attempt_id)
        return await self.adapters[coordinate.subject_id].run_cell(
            input_value=input_value,
            coordinate=coordinate,
        )


def _build(
    config: RunConfiguration,
    store: ObjectStore,
    *,
    live: bool,
    plan_digest: str | None = None,
) -> PreparedStudy:
    if config.pricing.conservative_request_bound_usd is None:
        raise LaunchRefused("pricing_basis_unusable: local Smithers route has no billed price")
    routing_name = os.environ.get("CODE_EXTENSION_ROUTING_CONFIG")
    if not routing_name:
        raise LaunchRefused("routing_artifact_unavailable: set CODE_EXTENSION_ROUTING_CONFIG")
    routing_path = Path(routing_name)
    if not routing_path.is_file():
        raise LaunchRefused("routing_artifact_unavailable: routing configuration is missing")
    refs = {ref.scenario: ref.manifest_digest for ref in config.scenario_qualifications}
    fixture = load_qualified_study_fixture(store, refs, image=config.image_digest)
    if fixture.manifest.routing_config_digest is not None and (
        digest_bytes(routing_path.read_bytes()) != fixture.manifest.routing_config_digest
    ):
        raise LaunchRefused("routing_identity_drift: qualified route file changed")
    factory = SmithersFactory(
        model=config.route.model,
        machine=config.profile,
        routing_config=routing_path,
        dispatch_url=config.route.endpoint,
        requester="assay-code-extension",
    )
    route = bridge_protocol.ModelRoute.model_validate(config.route.model_dump(mode="json"))
    gate = SpendGate(config.total_cap_usd) if live else None
    journal = (
        AttemptJournal(store.root / "attempts.jsonl", plan_digest or "", config.digest())
        if live
        else None
    )
    if journal is not None and gate is not None:
        journal.reconcile(gate)
        if gate.halt is not None:
            raise LaunchRefused(f"resume halted: {gate.halt}")
    workers: dict[str, ExtensionStudyWorker] = {}
    run_label = f"extension-{config.digest().removeprefix('sha256:')[:20]}"
    for arm_id in fixture.manifest.arm_set.arm_ids:
        bridges: dict[str, ExtensionBridgeClient] = {}
        adapters: dict[str, PierAdapter] = {}
        for scenario in fixture.manifest.scenarios:

            def completion_for(cell_key: str, *, _factory: SmithersFactory = factory) -> Any:
                base = SmithersTurnCompletion(
                    _factory, cell_key, authorized=_factory.configuration()
                )
                if gate is None or journal is None:
                    raise AssertionError("prepare cannot construct a model completion")
                bound = config.pricing.conservative_request_bound_usd
                if bound is None:
                    raise LaunchRefused("pricing_basis_unusable: route has no measured billing")
                budget = RequestBudget(gate, bound, journal, SpendGate(config.per_attempt_cap_usd))

                def complete(**kwargs: Any) -> Any:
                    request_id = turn_idempotency_key(cell_key, int(kwargs["turn"]))
                    return budget.call(cell_key, request_id, lambda: base(**kwargs))

                return complete

            bridge = ExtensionBridgeClient(
                image=config.image_digest,
                runs_root=store.root / "runs",
                factory=factory,
                run_label=run_label,
                route=route,
                scenario=scenario,
                arm_set=fixture.manifest.arm_set,
                arm_id=arm_id,
                settings=config.bounds,
                completion_for=completion_for if live else None,
                repository_snapshot=next(
                    item.realizations[arm_id]
                    for item in fixture.scenarios
                    if item.subject_id == scenario.subject_id
                ),
            )
            description = bridge.configuration()
            reference = str(store.publish_json(description))
            binding = RuntimeBinding(
                runtime_version="code-extension-ce-v1",
                image_digest=config.image_digest,
                configuration_ref=reference,
                package_digest="sha256:" + "0" * 64,
            )
            adapter = PierAdapter(
                store=store,
                bridge=bridge,
                binding=binding,
                model_route=config.route.model_dump(mode="json"),
                trial_limits=trial_limits(bridge.limits, config.bounds.timeout_s).model_dump(
                    mode="json"
                ),
                worker_id="code-extension-runner",
                package_layout="repository-agent",
            )
            bridges[scenario.subject_id] = bridge
            adapters[scenario.subject_id] = adapter
        workers[arm_id] = ExtensionStudyWorker(
            arm_id,
            bridges,
            adapters,
            config.digest(),
            journal,
            gate,
            config.pricing.conservative_request_bound_usd,
        )
    runtime_ref = str(
        store.publish_json(
            {
                "config_digest": config.digest(),
                "workers": {arm: worker.configuration(arm) for arm, worker in workers.items()},
            }
        )
    )
    runtime = RuntimeProfile(
        id="pier", version="code-extension-ce-v1", configuration_ref=runtime_ref
    )
    runner = DockerWorkflowRunner(
        WorkflowRunnerSettings(
            image=config.image_digest,
            toolchain="bun",
        )
    )
    count = sum(len(manifest.scenarios) for manifest in [fixture.manifest])
    return plan_study(
        store,
        fixture,
        workers=workers,
        runner=runner,
        runtime=runtime,
        image=config.image_digest,
        routing_digest=fixture.manifest.routing_config_digest,
        repeats=config.repeats,
        ceiling=ExecutionCeiling(
            max_cells=count * len(workers) * config.repeats,
            max_wall_time_seconds=config.bounds.timeout_s * count * config.repeats,
            max_fleet_occupancy=1,
        ),
    )


def prepare(config_path: Path, store_path: Path) -> dict[str, Any]:
    config = RunConfiguration.load(config_path)
    store = ObjectStore(store_path)
    prepared = _build(config, store, live=False)
    plan = parse_execution_plan(json.loads(prepared.plan_bytes))
    if not isinstance(plan, ExecutionPlanV3):
        raise LaunchRefused("extension runner requires a v3 plan")
    digest = prepared.authorization
    launch_dir = store.root / "plans" / digest.removeprefix("sha256:")
    launch_dir.mkdir(parents=True, exist_ok=True)
    plan_path = launch_dir / "plan.json"
    config_archive = launch_dir / "config.json"
    for path, data in (
        (plan_path, prepared.plan_bytes),
        (config_archive, config.canonical_bytes()),
    ):
        if path.exists() and path.read_bytes() != data:
            raise LaunchRefused(f"immutable plan artifact changed: {path}")
        path.write_bytes(data)
    bound = config.pricing.conservative_request_bound_usd
    calls = 1 + len(plan.cells) * config.bounds.max_turns  # one charged route probe
    estimate = str(bound * calls) if bound is not None else None
    summary: dict[str, Any] = {
        "plan": str(plan_path),
        "digest": digest,
        "config_digest": config.digest(),
        "tasks": [cell.model_dump(mode="json") for cell in plan.cells],
        "model": config.route.model_dump(mode="json"),
        "seed": config.randomization_seed,
        "calls": calls,
        "route_probe_calls": 1,
        "attempts": len(plan.cells),
        "route_probe_attempts": 1,
        "effective_limits": {
            "bounds": config.bounds.model_dump(mode="json"),
            "ceiling": plan.ceiling.model_dump(mode="json"),
        },
        "estimated_spend_usd": estimate,
        "maximum_spend_usd": str(config.total_cap_usd),
        "coverage": {
            "pricing": "conservative_request_bound",
            "plan_catalogue": plan.cost_estimate.model_dump(mode="json"),
        },
        "unresolved_blockers": ["seeded dispatch order needs a shared planner schedule decision"],
    }
    (launch_dir / "launch-summary.json").write_bytes(canonical_json(summary) + b"\n")
    return summary


async def execute(plan_path: Path, authorization: str, store_path: Path) -> dict[str, Any]:
    plan_bytes = plan_path.read_bytes()
    actual = digest_bytes(plan_bytes)
    if actual != authorization:
        raise LaunchRefused(
            f"plan_authorization_mismatch: supplied {authorization}; actual {actual}"
        )
    authorize(plan_bytes, authorization)
    store = ObjectStore(store_path)
    launch_dir = store.root / "plans" / actual.removeprefix("sha256:")
    if plan_path.resolve() != (launch_dir / "plan.json").resolve():
        raise LaunchRefused("original frozen plan artifact is required")
    config = RunConfiguration.load(launch_dir / "config.json")
    prepared = _build(config, store, live=True, plan_digest=actual)
    if prepared.plan_bytes != plan_bytes:
        raise LaunchRefused("plan differs from frozen configuration; prepare a new plan")
    await _route_probe(config, store, actual, prepared)
    result = await run_study(prepared, store)
    worker = cast(ExtensionStudyWorker, next(iter(prepared.workers.values())))
    assert worker.gate is not None
    return {
        "status": type(result).__name__,
        "authorization": authorization,
        "spend": worker.gate.record(),
    }


async def _route_probe(
    config: RunConfiguration,
    store: ObjectStore,
    plan_digest: str,
    prepared: PreparedStudy,
) -> None:
    """A billed, authorized request confirming the exact model and output bound."""
    worker = cast(ExtensionStudyWorker, next(iter(prepared.workers.values())))
    gate, journal, bound = worker.gate, worker.journal, worker.request_bound
    if gate is None or journal is None or bound is None:
        raise LaunchRefused("route_probe_budget_unavailable")
    probe_id = f"{plan_digest}:route-probe"
    if any(
        record.get("attempt_id") == probe_id + ":request-1"
        and record.get("event") == "finished"
        and record.get("status") == "settled"
        for record in journal.records()
    ):
        return
    journal.claim_attempt("__route_probe__", probe_id)
    factory = next(iter(worker.bridges.values())).factory
    budget = RequestBudget(gate, bound, journal, SpendGate(config.per_attempt_cap_usd))

    def dispatch() -> Any:
        client = factory.create(idempotency_key=probe_id)

        async def one() -> Any:
            try:
                return await client.complete_payload(
                    {
                        "messages": [{"role": "user", "content": "Reply OK."}],
                        "max_tokens": config.bounds.max_output_tokens,
                        "temperature": 0.0,
                    }
                )
            finally:
                await client.aclose()

        response = asyncio.run(one())
        if isinstance(response, WorkerFailure):
            raise LaunchRefused(f"route_probe_failed: {response.error_type}")
        if response.worker_model != config.route.model:
            raise LaunchRefused(
                f"route_probe_model_mismatch: {response.worker_model} != {config.route.model}"
            )
        return response

    await asyncio.to_thread(budget.call, "__route_probe__", probe_id + ":request-1", dispatch)
    if gate.halt is not None:
        raise LaunchRefused(f"route_probe_halted: {gate.halt}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    q = commands.add_parser("qualify")
    q.add_argument("--scenario", required=True)
    q.add_argument("--image", required=True)
    q.add_argument("--routing-config")
    q.add_argument("--verify-committed", action="store_true")
    scripted = commands.add_parser("scripted")
    scripted.add_argument("--scenario", required=True)
    scripted.add_argument("--image", required=True)
    scripted.add_argument("--store", type=Path, required=True)
    p = commands.add_parser("prepare")
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--store", type=Path, required=True)
    e = commands.add_parser("execute")
    e.add_argument("--plan", type=Path, required=True)
    e.add_argument("--authorize", required=True)
    e.add_argument("--store", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "qualify":
        sys.argv = ["code_extension.qualify", "--scenario", args.scenario, "--image", args.image]
        if args.routing_config:
            sys.argv.extend(("--routing-config", args.routing_config))
        if args.verify_committed:
            sys.argv.append("--verify-committed")
        qualify.main()
    elif args.command == "scripted":
        from code_extension.probe import reference_submission

        fixture = load_scenario(args.scenario)
        manifest_path = PILOT.parent / args.scenario / "qualification" / "manifest.json"
        from assay.fixture_manifest import FixtureManifestV3

        manifest = FixtureManifestV3.model_validate_json(manifest_path.read_bytes())
        if manifest.observed_runtime_image_digest != args.image:
            raise LaunchRefused("scripted image differs from qualification")
        record = asyncio.run(reference_submission(fixture, manifest, args.image))
        ref = ObjectStore(args.store).publish_json(record)
        print(
            json.dumps(
                {"scripted_record": str(ref), "verdict": record["independent_evaluator_verdict"]}
            )
        )
    elif args.command == "prepare":
        print(json.dumps(prepare(args.config, args.store), sort_keys=True))
    else:
        print(
            json.dumps(asyncio.run(execute(args.plan, args.authorize, args.store)), sort_keys=True)
        )


if __name__ == "__main__":
    main()
