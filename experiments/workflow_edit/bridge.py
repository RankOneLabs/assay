"""Run a workflow-edit cell through Assay's PierAdapter and the repository-agent bridge.

``PierAdapter`` packages the arm repository, binds the exchange, and settles the
bridge's sealed evidence. This module is the boundary on the other side of it:
an Assay ``PierBridgeClient`` whose trial is one repository-agent attempt run by
the isolated bridge project, with every model turn dispatched through Assay's
pinned ``SmithersClient``. The bridge project stays free of any ``assay``
import; the two meet only here, over the wire models both sides already share.
"""

from __future__ import annotations

import asyncio
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

_BRIDGE_SRC = Path(__file__).resolve().parents[2] / "integrations" / "pier" / "src"
if str(_BRIDGE_SRC) not in sys.path:
    sys.path.insert(0, str(_BRIDGE_SRC))

from assay_pier_bridge import protocol as bridge  # noqa: E402
from assay_pier_bridge.agent_loop import (  # noqa: E402
    TOOLS,
    DockerTmpfsStagingStorage,
    DockerTmpfsToolSandbox,
    LoopBounds,
    ModelDispatchError,
    ModelTurn,
    RepositoryAgentClient,
    SandboxFactory,
    SandboxLimits,
    ToolOutput,
    TurnCompletion,
)
from assay_pier_bridge.repository_trial import (  # noqa: E402
    RepositoryAgentTrialClient,
    agent_configuration,
)
from assay_pier_bridge.runtime import BridgeRuntime  # noqa: E402

from assay.adapters.pier import BridgeEffectiveEnforcement, BridgeTrialResult  # noqa: E402
from assay.adapters.smithers import SmithersFactory  # noqa: E402
from assay.execution import WorkerFailure  # noqa: E402
from assay.models import CellCoordinate  # noqa: E402
from assay.pier_protocol import (  # noqa: E402
    CandidateFailure,
    CandidateSubmission,
    InfrastructureFailure,
    PierExchange,
)
from workflow_edit.dispatch import cell_idempotency_key  # noqa: E402

LOCAL_ROUTE = bridge.ModelRoute(
    endpoint="http://willie:8900", model="qwen-coder-32b", provider="smithers-local"
)
# The declared production scope plus optional visible tests (spec section 4.4).
WRITABLE_PREFIXES = ("src/", "tests/visible/")
# Qwen2.5-Coder's own generation default, made explicit so it is authorized.
TEMPERATURE = 0.7

_OUTCOME: TypeAdapter[CandidateSubmission | CandidateFailure | InfrastructureFailure] = (
    TypeAdapter(CandidateSubmission | CandidateFailure | InfrastructureFailure)
)


def turn_idempotency_key(cell_key: str, turn: int) -> str:
    """Stable for a re-dispatch of one turn; distinct across turns and cells."""
    return f"{cell_key}:t{turn}"


@dataclass(frozen=True)
class SmithersTurnCompletion:
    """One agent turn as one keyed Smithers job on the pinned machine."""

    factory: SmithersFactory
    cell_key: str
    temperature: float = TEMPERATURE
    # The Smithers identity the arm was authorized with. Each turn's client
    # re-reads the routing file, so without this a mid-run change would be
    # adopted as the new authority instead of failing the turn.
    authorized: Mapping[str, Any] | None = None

    def __call__(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int,
        turn: int,
        deadline: float | None,
    ) -> ModelTurn:
        payload = {
            "messages": messages,
            "tools": tools,
            # vLLM's Qwen parser otherwise answers in prose; every turn must act.
            "tool_choice": "required",
            "max_tokens": max_tokens,
            "temperature": self.temperature,
        }
        client = self.factory.create(idempotency_key=turn_idempotency_key(self.cell_key, turn))
        if self.authorized is not None and client.configuration() != dict(self.authorized):
            asyncio.run(client.aclose())
            raise ModelDispatchError(
                "ResolvedTagIdentityMismatch", "Smithers routing changed since authorization"
            )

        async def dispatch() -> Any:
            try:
                return await client.complete_payload(payload)
            finally:
                await client.aclose()

        timeout = None if deadline is None else max(deadline - time.monotonic(), 0.0)
        try:
            completion = asyncio.run(asyncio.wait_for(dispatch(), timeout))
        except TimeoutError as error:
            raise ValueError("agent_deadline") from error
        if isinstance(completion, WorkerFailure):
            raise ModelDispatchError(completion.error_type, completion.message)
        calls = completion.result.get("tool_calls") or []
        # Smithers forwards no finish_reason; a completion at the cap was cut off.
        finish = (
            "length" if completion.output_tokens >= max_tokens
            else "tool_calls" if calls else "stop"
        )
        return ModelTurn(
            message={
                "role": "assistant",
                "content": completion.result.get("content"),
                "tool_calls": calls,
            },
            finish_reason=finish,
            prompt_tokens=completion.input_tokens,
            completion_tokens=completion.output_tokens,
            cost_usd=None,
            observations={
                "smithers_job_id": completion.job_id,
                "queue_latency_seconds": completion.queue_latency_seconds,
                "time_from_acceptance_seconds": completion.time_from_acceptance_seconds,
                "worker_model": completion.worker_model,
            },
        )


def trial_limits(limits: SandboxLimits, timeout_s: float) -> bridge.TrialLimits:
    return bridge.TrialLimits(
        cpu=limits.cpus,
        memory_mb=limits.memory_mb,
        pids=limits.pids,
        timeout_s=timeout_s,
        storage_mb=limits.storage_mb,
    )


class WorkflowEditHandle:
    """Adapts one bridge trial to Assay's ``PierBridgeHandle`` over the shared wire."""

    def __init__(
        self, exchange: PierExchange, runtime: BridgeRuntime, request: bridge.TrialRequest
    ) -> None:
        self._exchange = exchange
        self._runtime = runtime
        self._request = request
        self._effective: bridge.EffectiveEnforcement | None = None

    def run(self) -> BridgeTrialResult:
        result = self._runtime.run_cell(self._request)
        self._effective = result.effective
        return BridgeTrialResult(
            exchange=self._exchange,
            outcome=_OUTCOME.validate_json(result.outcome.model_dump_json()),
            usage=None if result.usage is None else result.usage.model_dump(),
            artifacts=dict(result.artifacts),
        )

    def cancel(self) -> None:
        self._runtime.cancel()

    def teardown(self) -> BridgeEffectiveEnforcement:
        """``BridgeRuntime`` already tore the trial down; report what it verified."""
        if self._effective is None:
            return BridgeEffectiveEnforcement(
                containers_remaining=0, child_processes_remaining=0, teardown_completed=False
            )
        return BridgeEffectiveEnforcement(
            containers_remaining=self._effective.containers_remaining,
            child_processes_remaining=self._effective.child_processes_remaining,
            teardown_completed=self._effective.teardown_completed,
        )


@dataclass
class WorkflowEditBridgeClient:
    """Assay ``PierBridgeClient``: one fresh agent, container, and conversation per cell.

    ``completion_for`` replaces the Smithers turn backend only for scripted,
    model-free qualification probes; it never appears in an authorized run.
    """

    image: str
    runs_root: Path
    factory: SmithersFactory
    run_label: str
    bounds: LoopBounds = field(default_factory=LoopBounds)
    limits: SandboxLimits = field(default_factory=SandboxLimits)
    timeout_s: float = 900.0
    completion_for: Callable[[str], TurnCompletion] | None = None
    sandbox_factory: SandboxFactory | None = None
    authorized_smithers: dict[str, Any] = field(init=False)

    def __post_init__(self) -> None:
        self.authorized_smithers = self.factory.configuration()

    def configuration(self) -> dict[str, Any]:
        """The live runtime description an arm authorizes (no per-cell values).

        It re-reads the Smithers routing file, so ``execute_plan``'s check of
        worker configuration before every cell catches routing drift.
        """
        return agent_configuration(
            bounds=self.bounds,
            limits=self.limits,
            writable_prefixes=WRITABLE_PREFIXES,
            model_route=LOCAL_ROUTE,
            extra={
                "image": self.image,
                "timeout_s": self.timeout_s,
                "turns": {
                    "backend": "smithers",
                    "smithers": self.factory.configuration(),
                    "tool_choice": "required",
                    "temperature": TEMPERATURE,
                    "idempotency_key": "<cell key>:t<turn>",
                },
            },
        )

    def create(self, *, exchange: PierExchange, package: Mapping[str, str]) -> WorkflowEditHandle:
        coordinate = CellCoordinate.model_validate(exchange.coordinate.model_dump(mode="json"))
        cell_key = cell_idempotency_key(self.run_label, coordinate)
        completion: TurnCompletion = (
            self.completion_for(cell_key)
            if self.completion_for is not None
            else SmithersTurnCompletion(
                self.factory, cell_key, authorized=self.authorized_smithers
            )
        )
        agent = RepositoryAgentClient(
            api_key=None,
            image=self.image,
            runs_root=self.runs_root,
            model_route=LOCAL_ROUTE,
            completion=completion,
            bounds=self.bounds,
            writable_prefixes=WRITABLE_PREFIXES,
            sandbox_factory=self.sandbox_factory
            or partial(DockerTmpfsToolSandbox, limits=self.limits),
            storage_factory=DockerTmpfsStagingStorage,
            sandbox_limits=self.limits,
        )
        trial_client = RepositoryAgentTrialClient(
            agent=agent, package=package, limits=self.limits, configuration=self.configuration()
        )
        request = bridge.TrialRequest(
            cell_id=coordinate.id,
            package_digest=exchange.binding.package_digest,
            exchange=bridge.PierExchange.model_validate_json(exchange.model_dump_json()),
            model_route=LOCAL_ROUTE,
            limits=trial_limits(self.limits, self.timeout_s),
            network_policy="toolchain-only",
        )
        return WorkflowEditHandle(exchange, BridgeRuntime(trial_client), request)


__all__ = [
    "LOCAL_ROUTE",
    "TOOLS",
    "ModelDispatchError",
    "ModelTurn",
    "SmithersTurnCompletion",
    "ToolOutput",
    "TurnCompletion",
    "WorkflowEditBridgeClient",
    "WorkflowEditHandle",
    "trial_limits",
    "turn_idempotency_key",
]
