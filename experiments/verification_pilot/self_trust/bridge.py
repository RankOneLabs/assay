"""Run self-trust cells through the pilot's bridge, agent bounds and spend gate.

Only the rendering changes: the self-trust system prompt, and the session
prefix from ``session.py`` in place of the pilot's contributor blocks.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from typing import Any, cast

from assay.adapters.pier import PierAdapter
from assay.execution import AdmissionHalt, WorkerFailure, WorkerResult
from assay.models import CellCoordinate, RuntimeProfile
from assay.pier_protocol import PierExchange, RuntimeBinding
from assay.store import ObjectStore
from verification_pilot.bridge import (
    DockerTmpfsStagingStorage,
    DockerTmpfsToolSandbox,
    PilotBridgeClient,
    SandboxLimits,
    SmithersTurnCompletion,
    create_pilot_agent,
)
from verification_pilot.dispatch import cell_idempotency_key
from verification_pilot.fixtures import read_raw_repository
from verification_pilot.self_trust import refactor_session
from verification_pilot.self_trust.ladder import REFACTOR, RUNGS
from verification_pilot.self_trust.prompts import (
    T2_TEXT,
    T3_TEXT,
    build_system_prompt,
    framing_for,
)
from verification_pilot.self_trust.session import (
    SYSTEM_PROMPT,
    Placement,
    session_prefix,
)
from verification_pilot.self_trust.session import (
    matched_prefix as rename_matched_prefix,
)
from verification_pilot.self_trust.study import (
    MATCHED_ARMS,
    SelfTrustSubject,
    order_for,
    placement_for,
    realization_payload,
)

RUNTIME_VERSION = "self-trust-v1"


def subject_prefix(subject: SelfTrustSubject, arm_id: str) -> list[dict[str, Any]]:
    """The recorded session after the task message, for either fixture."""
    placement: Placement = placement_for(arm_id)
    if subject.fixture in RUNGS:
        rung = RUNGS[subject.fixture]
        if arm_id in MATCHED_ARMS:
            return refactor_session.matched_prefix(
                subject.remnant_owner or subject.own, subject.remnant_owner,
                arm_id == MATCHED_ARMS[0], rung)
        return refactor_session.session_prefix(subject.own, subject.remnant_owner, placement,
                                               order_for(arm_id), rung)
    if order_for(arm_id) != "own_first":
        raise ValueError(f"{subject.id}: the rename fixture does not vary log order")
    if subject.concept is None:
        raise ValueError(f"{subject.id}: a rename subject needs its concept")
    if arm_id in MATCHED_ARMS:
        return rename_matched_prefix(read_raw_repository(), subject.concept,
                                     subject.remnant_owner or subject.own, subject.remnant_owner,
                                     arm_id == MATCHED_ARMS[0])
    return session_prefix(read_raw_repository(), subject.concept, subject.own,
                          subject.remnant_owner, placement)


def subject_system_prompt(subject: SelfTrustSubject, arm_id: str) -> str:
    if subject.fixture not in RUNGS:
        return SYSTEM_PROMPT
    rung = RUNGS[subject.fixture]
    framing = "matched" if arm_id in MATCHED_ARMS else framing_for(rung, subject.own)
    return build_system_prompt(rung, framing)


def subject_turns() -> tuple[str, str]:
    return T2_TEXT, T3_TEXT


@dataclass
class SelfTrustBridgeClient(PilotBridgeClient):
    """One fresh agent and sealed Pier trial per self-trust cell."""

    system_prompt: str = build_system_prompt(REFACTOR, framing_for(REFACTOR, "group_a"))

    def configuration(self, subject: SelfTrustSubject | None = None,
                      arm_id: str = "st-native") -> dict[str, Any]:
        prompt = (subject_system_prompt(subject, arm_id) if subject is not None
                  else self.system_prompt)
        return self._configuration_for(
            system_prompt=prompt, next_user_turns=subject_turns(),
            subject_rendering="self-trust-session-v2",
            writable_prefixes=(RUNGS[subject.fixture].writable_prefixes
                               if subject is not None and subject.fixture in RUNGS else None),
        )

    def create(self, *, exchange: PierExchange, package: Any) -> Any:
        from assay_pier_bridge import protocol as bridge_protocol
        from assay_pier_bridge.repository_trial import RepositoryAgentTrialClient
        from assay_pier_bridge.runtime import BridgeRuntime
        from workflow_edit.bridge import WorkflowEditHandle, trial_limits

        coordinate = CellCoordinate.model_validate(exchange.coordinate.model_dump(mode="json"))
        subject = cast(SelfTrustSubject, self.subjects[coordinate.subject_id])
        prefix = tuple(subject_prefix(subject, coordinate.arm_id))
        completion = (SmithersTurnCompletion(self.factory,
                                             cell_idempotency_key(self.run_label, coordinate),
                                             authorized=self.authorized_smithers)
                      if self.factory is not None else None)
        agent = create_pilot_agent(
            settings=self.settings, image=self.image, runs_root=self.runs_root,
            model_route=self.model_route, completion=completion,
            next_user_turns=subject_turns(), api_key=self.api_key,
            message_prefix=prefix,
            system_prompt=subject_system_prompt(subject, coordinate.arm_id),
            writable_prefixes=(RUNGS[subject.fixture].writable_prefixes
                               if subject.fixture in RUNGS else None),
            sandbox_factory=partial(DockerTmpfsToolSandbox, limits=SandboxLimits()),
            storage_factory=DockerTmpfsStagingStorage, spend_gate=self.spend_gate,
        )
        limits = SandboxLimits()
        trial = RepositoryAgentTrialClient(agent=agent, package=package, limits=limits,
                                           configuration=self.configuration(subject,
                                                                            coordinate.arm_id))
        request = bridge_protocol.TrialRequest(
            cell_id=coordinate.id, package_digest=exchange.binding.package_digest,
            exchange=bridge_protocol.PierExchange.model_validate_json(exchange.model_dump_json()),
            model_route=self.model_route, limits=trial_limits(limits, self.timeout_s),
            network_policy="toolchain-only",
        )
        return WorkflowEditHandle(exchange, BridgeRuntime(trial), request)


@dataclass
class SelfTrustWorker:
    adapter: PierAdapter
    bridge: SelfTrustBridgeClient
    supports_cell_coordinates: bool = True

    def configuration(self, arm_id: str) -> dict[str, Any]:
        return {**self.adapter.configuration(arm_id), "runtime": self.bridge.configuration()}

    async def run_cell(self, *, input_value: Any, coordinate: CellCoordinate) -> WorkerResult:
        subject = cast(SelfTrustSubject, self.bridge.subjects[coordinate.subject_id])
        if input_value != realization_payload(subject, coordinate.arm_id):
            return WorkerFailure("RealizationMismatch", "input differs from its subject")
        gate = self.bridge.spend_gate
        if gate is not None and gate.halt is not None:
            raise AdmissionHalt(gate.halt, f"spend cap halted the run: {gate.halt}")
        result = await self.adapter.run_cell(input_value=input_value, coordinate=coordinate)
        if gate is not None and gate.halt is not None:
            raise AdmissionHalt(gate.halt, f"spend cap halted the run: {gate.halt}",
                                accounting=result.accounting, trace=result.trace)
        return result


def self_trust_worker(
    store: ObjectStore, bridge: SelfTrustBridgeClient,
) -> tuple[SelfTrustWorker, RuntimeProfile]:
    from workflow_edit.bridge import trial_limits

    configuration_ref = str(store.publish_json(bridge.configuration()))
    binding = RuntimeBinding(runtime_version=RUNTIME_VERSION, image_digest=bridge.image,
                             configuration_ref=configuration_ref,
                             package_digest="sha256:" + "0" * 64)
    adapter = PierAdapter(
        store=store, bridge=bridge, binding=binding,
        model_route=bridge.model_route.model_dump(mode="json"),
        trial_limits=trial_limits(SandboxLimits(), bridge.timeout_s).model_dump(mode="json"),
        max_repository_files=200, max_repository_bytes=1_000_000,
        worker_id="self-trust-agent", package_layout="repository-agent",
    )
    return (SelfTrustWorker(adapter, bridge),
            RuntimeProfile(id="pier", version=RUNTIME_VERSION,
                           configuration_ref=configuration_ref))
