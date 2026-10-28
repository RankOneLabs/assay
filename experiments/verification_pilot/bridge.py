"""Construct the verification pilot's repository agent from its frozen settings."""

from __future__ import annotations

import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import Any, cast

_BRIDGE_SRC = Path(__file__).resolve().parents[2] / "integrations" / "pier" / "src"
if str(_BRIDGE_SRC) not in sys.path:
    sys.path.insert(0, str(_BRIDGE_SRC))

from assay_pier_bridge.agent_loop import (  # noqa: E402
    CellStorage,
    DockerTmpfsStagingStorage,
    DockerTmpfsToolSandbox,
    LoopBounds,
    RepositoryAgentClient,
    SandboxFactory,
    SandboxLimits,  # noqa: E402
    TurnCompletion,
)
from assay_pier_bridge.protocol import ModelRoute  # noqa: E402
from assay_pier_bridge.repository_trial import (  # noqa: E402
    RepositoryAgentTrialClient,
    agent_configuration,
)
from assay_pier_bridge.runtime import BridgeRuntime  # noqa: E402
from workflow_edit.bridge import (  # noqa: E402
    SmithersTurnCompletion,
    WorkflowEditHandle,
    trial_limits,
)

from assay.adapters.pier import PierAdapter  # noqa: E402
from assay.adapters.smithers import SmithersFactory  # noqa: E402
from assay.execution import AdmissionHalt, WorkerFailure, WorkerResult  # noqa: E402
from assay.models import CellCoordinate, RuntimeProfile  # noqa: E402
from assay.pier_protocol import PierExchange, RuntimeBinding  # noqa: E402
from assay.store import ObjectStore  # noqa: E402
from verification_pilot.arms import arm, placement_for  # noqa: E402
from verification_pilot.budget import BudgetedAgentClient, SpendGate  # noqa: E402
from verification_pilot.dispatch import cell_idempotency_key  # noqa: E402
from verification_pilot.inputs import PILOT_SYSTEM_PROMPT, T2_TEXT, T3_TEXT  # noqa: E402
from verification_pilot.prompts import task_prompt  # noqa: E402
from verification_pilot.render import render_prefix  # noqa: E402
from verification_pilot.session import contributor_blocks, rotated_blocks  # noqa: E402
from verification_pilot.settings import VerificationPilotSettings  # noqa: E402


def create_pilot_agent(
    *,
    settings: VerificationPilotSettings,
    image: str,
    runs_root: Path,
    model_route: ModelRoute,
    completion: TurnCompletion | None,
    next_user_turns: tuple[str, ...],
    api_key: str | None = None,
    sandbox_factory: SandboxFactory = DockerTmpfsToolSandbox,
    storage_factory: Callable[[Path, int], CellStorage] = DockerTmpfsStagingStorage,
    message_prefix: tuple[dict[str, Any], ...] = (),
    spend_gate: SpendGate | None = None,
    system_prompt: str = PILOT_SYSTEM_PROMPT,
    writable_prefixes: tuple[str, ...] | None = None,
    pilot_tools_by_turn: dict[str, list[dict[str, Any]]] | None = None,
) -> RepositoryAgentClient:
    """Use the pilot's declared scope and call budgets for the actual loop.

    A ``spend_gate`` puts every paid request behind the operator's dollar cap.
    """
    if spend_gate is not None and not model_route.paid_route_reachable:
        raise ValueError("the zero-paid local route takes no spend gate")
    budgeted: dict[str, Any] = {"spend_gate": spend_gate} if spend_gate is not None else {}
    client = BudgetedAgentClient if spend_gate is not None else RepositoryAgentClient
    return client(
        api_key=api_key,
        image=image,
        runs_root=runs_root,
        model_route=model_route,
        completion=completion,
        bounds=LoopBounds(
            max_turns=settings.max_turns,
            max_tool_schema_bytes=settings.max_tool_schema_bytes,
            max_tool_output_bytes=settings.max_tool_output_bytes,
            max_conversation_bytes=settings.max_conversation_bytes,
            max_request_bytes=settings.max_request_bytes,
            max_response_bytes=settings.max_response_bytes,
            max_output_tokens=settings.max_output_tokens,
            max_storage_mb=settings.max_storage_mb,
        ),
        pilot_mode=True,
        pilot_tools_by_turn=pilot_tools_by_turn or {},
        system_prompt=system_prompt,
        next_user_turns=next_user_turns,
        message_prefix=message_prefix,
        writable_prefixes=(settings.writable_prefixes if writable_prefixes is None
                           else writable_prefixes),
        max_tool_calls_per_turn=settings.max_tool_calls_per_turn,
        max_tool_calls_per_cell=settings.max_tool_calls_per_cell,
        sandbox_factory=sandbox_factory,
        storage_factory=storage_factory,
        sandbox_limits=SandboxLimits(
            workspace_mb=settings.max_storage_mb // 2,
            cache_mb=settings.max_storage_mb - settings.max_storage_mb // 2,
        ),
        **budgeted,
    )


@dataclass
class PilotBridgeClient:
    """One fresh pilot agent and sealed Pier trial per planned cell."""

    image: str
    runs_root: Path
    run_label: str
    model_route: ModelRoute
    subjects: dict[str, Any]
    settings: VerificationPilotSettings
    factory: SmithersFactory | None = None
    api_key: str | None = None
    timeout_s: float = 900.0
    # Operator-held and outside the runtime fingerprint; required on the paid route.
    spend_gate: SpendGate | None = None
    system_prompt: str = PILOT_SYSTEM_PROMPT
    authorized_smithers: dict[str, Any] | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        if self.model_route.paid_route_reachable and self.spend_gate is None:
            raise ValueError("the paid route requires an operator spend cap")
        if not self.model_route.paid_route_reachable and self.spend_gate is not None:
            raise ValueError("the zero-paid local route takes no spend gate")
        if self.factory is not None:
            self.authorized_smithers = self.factory.configuration()

    def configuration(self) -> dict[str, Any]:
        return self._configuration_for(
            system_prompt=self.system_prompt, next_user_turns=(T2_TEXT, T3_TEXT),
            subject_rendering="realization-ref-v1",
        )

    def _configuration_for(self, *, system_prompt: str,
                           next_user_turns: tuple[str, ...],
                           subject_rendering: str,
                           writable_prefixes: tuple[str, ...] | None = None) -> dict[str, Any]:
        probe = create_pilot_agent(
            settings=self.settings, image=self.image, runs_root=self.runs_root,
            model_route=self.model_route,
            completion=(cast(TurnCompletion, lambda **_: None)
                        if self.factory is not None else None),
            next_user_turns=next_user_turns,
            api_key=self.api_key, system_prompt=system_prompt,
            writable_prefixes=writable_prefixes,
        )
        configuration: dict[str, Any] = agent_configuration(
            bounds=probe.bounds, limits=SandboxLimits(),
            writable_prefixes=probe.writable_prefixes,
            model_route=self.model_route, system_prompt=probe.system_prompt,
            pilot_mode=True, pilot_tools_by_turn=probe.pilot_tools_by_turn,
            next_user_turns=probe.next_user_turns,
            max_tool_calls_per_turn=probe.max_tool_calls_per_turn,
            max_tool_calls_per_cell=probe.max_tool_calls_per_cell,
            extra={"image": self.image, "timeout_s": self.timeout_s,
                   "subject_rendering": subject_rendering,
                   "turns": {"backend": "smithers" if self.factory else "openrouter",
                             "smithers": self.factory.configuration()
                             if self.factory is not None else None}},
        )
        return configuration

    def create(self, *, exchange: PierExchange,
               package: Mapping[str, str]) -> WorkflowEditHandle:
        coordinate = CellCoordinate.model_validate(exchange.coordinate.model_dump(mode="json"))
        subject = self.subjects[coordinate.subject_id]
        blocks = rotated_blocks(contributor_blocks(subject.migration), subject.rotation)
        prefix = render_prefix(blocks, arm(
            placement_for(coordinate.arm_id),
            "smithers-local" if self.factory is not None else "openrouter",
        ))
        cell_key = cell_idempotency_key(self.run_label, coordinate)
        completion = (SmithersTurnCompletion(self.factory, cell_key,
                                             authorized=self.authorized_smithers)
                      if self.factory is not None else None)
        agent = create_pilot_agent(
            settings=self.settings, image=self.image, runs_root=self.runs_root,
            model_route=self.model_route, completion=completion,
            next_user_turns=(T2_TEXT, T3_TEXT),
            api_key=self.api_key, message_prefix=prefix,
            sandbox_factory=partial(DockerTmpfsToolSandbox, limits=SandboxLimits()),
            storage_factory=DockerTmpfsStagingStorage,
            spend_gate=self.spend_gate,
        )
        limits = SandboxLimits()
        trial = RepositoryAgentTrialClient(agent=agent, package=package, limits=limits,
                                           configuration=self.configuration())
        from assay_pier_bridge import protocol as bridge_protocol

        request = bridge_protocol.TrialRequest(
            cell_id=coordinate.id, package_digest=exchange.binding.package_digest,
            exchange=bridge_protocol.PierExchange.model_validate_json(exchange.model_dump_json()),
            model_route=self.model_route, limits=trial_limits(limits, self.timeout_s),
            network_policy="toolchain-only",
        )
        return WorkflowEditHandle(exchange, BridgeRuntime(trial), request)


@dataclass
class PilotWorker:
    adapter: PierAdapter
    bridge: PilotBridgeClient
    supports_cell_coordinates: bool = True

    def configuration(self, arm_id: str) -> dict[str, Any]:
        return {**self.adapter.configuration(arm_id), "runtime": self.bridge.configuration()}

    async def run_cell(self, *, input_value: Any, coordinate: CellCoordinate) -> WorkerResult:
        subject = self.bridge.subjects[coordinate.subject_id]
        blocks = rotated_blocks(contributor_blocks(subject.migration), subject.rotation)
        if not isinstance(input_value, dict) or any((
            input_value.get("task") != task_prompt(subject.migration),
            input_value.get("repository") != subject.repository,
            input_value.get("migration") != subject.migration.name,
            input_value.get("location") != subject.location,
            input_value.get("rotation") != subject.rotation,
            input_value.get("blocks") != [block.text for block in blocks],
            input_value.get("placement") != placement_for(coordinate.arm_id),
        )):
            return WorkerFailure("RealizationMismatch", "pilot input differs from its subject")
        gate = self.bridge.spend_gate
        if gate is not None and gate.halt is not None:
            raise AdmissionHalt(gate.halt, f"spend cap halted the run: {gate.halt}")
        result = await self.adapter.run_cell(input_value=input_value, coordinate=coordinate)
        if gate is not None and gate.halt is not None:
            # The cell keeps its trace and accounting; no later cell is admitted,
            # and the run cannot report success with its spend ledger halted.
            raise AdmissionHalt(gate.halt, f"spend cap halted the run: {gate.halt}",
                                accounting=result.accounting, trace=result.trace)
        return result


def pilot_worker(
    store: ObjectStore, bridge: PilotBridgeClient
) -> tuple[PilotWorker, RuntimeProfile]:
    configuration_ref = str(store.publish_json(bridge.configuration()))
    binding = RuntimeBinding(runtime_version="verification-pilot-v1",
                             image_digest=bridge.image, configuration_ref=configuration_ref,
                             package_digest="sha256:" + "0" * 64)
    adapter = PierAdapter(
        store=store, bridge=bridge, binding=binding,
        model_route=bridge.model_route.model_dump(mode="json"),
        trial_limits=trial_limits(SandboxLimits(), bridge.timeout_s).model_dump(mode="json"),
        max_repository_files=200, max_repository_bytes=1_000_000,
        worker_id="verification-pilot-agent", package_layout="repository-agent",
    )
    return (PilotWorker(adapter, bridge),
            RuntimeProfile(id="pier", version=binding.runtime_version,
                           configuration_ref=configuration_ref))


__all__ = [
    "DockerTmpfsStagingStorage", "DockerTmpfsToolSandbox", "ModelRoute", "PilotBridgeClient",
    "PilotWorker", "SandboxLimits", "SmithersTurnCompletion", "SpendGate", "create_pilot_agent",
    "pilot_worker",
]
