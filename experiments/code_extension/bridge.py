"""Bind one extension arm to the repository-agent bridge before dispatch."""
# ruff: noqa: I001

from __future__ import annotations

import subprocess
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from functools import partial
from typing import Any

from workflow_edit.bridge import (
    SmithersTurnCompletion,
    TurnCompletion,
    WorkflowEditBridgeClient,
    WorkflowEditHandle,
    trial_limits,
)

from assay_pier_bridge import protocol as bridge_protocol
from assay_pier_bridge.agent_loop import (
    DockerTmpfsStagingStorage,
    DockerTmpfsToolSandbox,
    EXTENSION_TOOLS,
    LoopBounds,
    RepositoryAgentClient,
    SandboxLimits,
)
from assay_pier_bridge.repository_trial import RepositoryAgentTrialClient, agent_configuration
from assay_pier_bridge.runtime import BridgeRuntime

from assay.code_intel.delivery import CodeIntelDeliveryConfig
from assay.code_intel.models import BaselineMode, ToolDelivery
from assay.code_intel.query_script import QUERY_SCRIPT
from assay.code_intel.snapshot import delivered_workspace
from assay.fixture_manifest import CodeIntelligenceModeArmSet, ExtensionArmSet, ExtensionScenario
from assay.models import CellCoordinate
from assay.pier_protocol import PierExchange
from code_extension.arms import require_declared_codeintel_arm
from code_extension.codeintel import PreparedExtensionCodeIntel, prepare_extension_codeintel
from code_extension.dispatch import cell_idempotency_key
from code_extension.fixture import ADDED_SCENARIOS, SUBJECT_ID
from code_extension.fixtures import ExtensionScenarioSidecar, sidecar_for_subject
from code_extension.prompts import render_arm_prompts
from code_extension.settings import ExtensionAgentSettings

# The study's complete authorized model matrix. The underlying wire protocol
# accepts more historical routes; these two local routes are this study's arms.
AUTHORIZED_MODEL_ROUTES = frozenset({
    ("http://willie:8900", "qwen-coder-32b", "smithers-local"),
    ("http://willie:8900", "qwen3.6-27b", "smithers-local"),
})
LEGACY_WRITABLE_PREFIXES = ("src/", "tests/visible/")
LEGACY_SUBJECT_IDS = frozenset(
    {SUBJECT_ID, *(item.subject_id for item in ADDED_SCENARIOS.values())}
)
EXTENSION_SYSTEM_PROMPT = (
    "You are editing one repository copy in /workspace. Read instruction.md and use "
    "the repository tools to implement and check the feature. Call submit_output when "
    "finished; the files are the submission. Give a summary and your own assessment "
    "of completion, checks performed, and remaining work. Hidden checks and reference "
    "answers are unavailable. Do not use network access or install packages."
)


class UnauthorizedModelRoute(ValueError):
    """A route outside the declared study matrix was refused before model dispatch."""


class CodeIntelLeakRejected(ValueError):
    """A pre-run scan found hidden source in deliverable index material."""


def require_authorized_route(route: bridge_protocol.ModelRoute) -> None:
    key = (route.endpoint, route.model, route.provider)
    if key not in AUTHORIZED_MODEL_ROUTES:
        raise UnauthorizedModelRoute(f"unauthorized extension model route: {key}")


def observed_image_digest(image: str) -> str:
    """Bind the digest Docker reports for the built image, never its tag."""
    result = subprocess.run(
        ["docker", "image", "inspect", "--format", "{{.Id}}", image],
        capture_output=True, text=True, check=True,
    )
    digest = result.stdout.strip()
    if not digest.startswith("sha256:") or len(digest) != 71:
        raise ValueError("docker image inspect did not return a sha256 image digest")
    return digest


def index_sandbox_options(
    prepared: PreparedExtensionCodeIntel | None,
    delivery: CodeIntelDeliveryConfig | None,
    limits: SandboxLimits,
) -> dict[str, Any]:
    """Mount the index outside workspace; readability is recorded policy only."""
    options: dict[str, Any] = {"limits": limits}
    if prepared is not None and prepared.index_files is not None and delivery is not None:
        options.update({
            "index_mount": delivery.index_mount,
            "index_files": prepared.index_files,
            "index_agent_readable": True,
        })
    return options


@dataclass
class ExtensionBridgeClient(WorkflowEditBridgeClient):
    """One arm's declared prompt, route, tool surface and provider delivery."""

    scenario: ExtensionScenario | None = None
    scenario_sidecar: ExtensionScenarioSidecar | None = None
    arm_set: ExtensionArmSet | None = None
    arm_id: str = "baseline"
    route: bridge_protocol.ModelRoute = bridge_protocol.ModelRoute(
        endpoint="http://willie:8900", model="qwen-coder-32b", provider="smithers-local"
    )
    settings: ExtensionAgentSettings | None = None
    codeintel_delivery: CodeIntelDeliveryConfig | None = None
    repository_snapshot: Mapping[str, str] | None = None
    hidden_check_paths: frozenset[str] = frozenset()
    hidden_source_texts: tuple[str, ...] = ()
    leak_terms: tuple[str, ...] = ()
    preflight_queries: tuple[tuple[str, str], ...] = ()
    prepared: PreparedExtensionCodeIntel | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        self.route = bridge_protocol.ModelRoute.model_validate(
            self.route.model_dump(mode="json")
        )

    def _prompt(self) -> str:
        if self.scenario is None or self.arm_set is None:
            raise ValueError("extension scenario and arm set are required")
        return render_arm_prompts(self.arm_set, self.scenario)[self.arm_id]

    def _writable_prefixes(self) -> tuple[str, ...]:
        if self.scenario is None:
            raise ValueError("extension scenario is required for writable scope")
        sidecar = self.scenario_sidecar or sidecar_for_subject(self.scenario.subject_id)
        if sidecar is not None:
            if sidecar.subject_id != self.scenario.subject_id:
                raise ValueError("extension sidecar subject differs from scenario")
            prefixes = sidecar.writable_implementation_scope
            if any(not prefix.endswith("/") for prefix in prefixes):
                raise ValueError("extension writable scope must contain directory prefixes")
            return prefixes
        if self.scenario.subject_id in LEGACY_SUBJECT_IDS:
            return LEGACY_WRITABLE_PREFIXES
        raise ValueError("extension scenario has no writable-scope sidecar")

    def _bounds(self) -> LoopBounds:
        settings = self._settings()
        return LoopBounds(
            max_turns=settings.max_turns,
            max_tool_schema_bytes=settings.max_tool_schema_bytes,
            max_tool_output_bytes=settings.max_tool_output_bytes,
            max_conversation_bytes=settings.max_conversation_bytes,
            max_request_bytes=settings.max_request_bytes,
            max_response_bytes=settings.max_response_bytes,
            max_output_tokens=settings.max_output_tokens,
            max_storage_mb=settings.max_storage_mb,
        )

    def _settings(self) -> ExtensionAgentSettings:
        expected = ExtensionAgentSettings.for_model(self.route.model)
        if self.settings is not None and self.settings != expected:
            raise ValueError("extension ceilings differ from the authorized served context")
        return self.settings or expected

    def _prepare(self, package: Mapping[str, str]) -> PreparedExtensionCodeIntel | None:
        config = self.codeintel_delivery
        if config is None:
            return None
        if self.scenario is not None and self.scenario.hidden_tests and not self.hidden_check_paths:
            raise ValueError("codeintel_hidden_paths_required: hidden check paths are missing")
        snapshot = delivered_workspace(package)
        try:
            return prepare_extension_codeintel(
                snapshot=snapshot, hidden_paths=self.hidden_check_paths,
                hidden_source_texts=self.hidden_source_texts, term_patterns=self.leak_terms,
                preflight_queries=self.preflight_queries,
                image_digest=observed_image_digest(self.image),
                index_root=self.runs_root / "codeintel-indexes", config=config,
                baseline_tools=deepcopy(EXTENSION_TOOLS),
            )
        except ValueError as error:
            if str(error).startswith("codeintel_leak:"):
                raise CodeIntelLeakRejected(str(error)) from error
            raise

    def configuration(self) -> dict[str, Any]:
        require_authorized_route(self.route)
        require_declared_codeintel_arm(
            self.arm_set if isinstance(self.arm_set, CodeIntelligenceModeArmSet) else None,
            self.arm_id, self.codeintel_delivery,
        )
        settings = self._settings()
        if self.codeintel_delivery is not None and self.prepared is None:
            if self.repository_snapshot is None:
                raise ValueError("codeintel_repository_snapshot_required")
            self.prepared = self._prepare({
                f"workspace/{path}": source
                for path, source in self.repository_snapshot.items()
            })
        tools = self.prepared.tools if self.prepared is not None else EXTENSION_TOOLS
        prefix: tuple[dict[str, Any], ...] = ()
        if self.prepared is not None and self.prepared.prompt_block is not None:
            prefix = ({"role": "user", "content": self.prepared.prompt_block},)
        return agent_configuration(
            bounds=self._bounds(), limits=self.limits,
            writable_prefixes=self._writable_prefixes(), model_route=self.route,
            tools=tools, system_prompt=EXTENSION_SYSTEM_PROMPT, message_prefix=prefix,
            extra={
                "image": self.image, "image_digest": observed_image_digest(self.image),
                "timeout_s": settings.timeout_s,
                "arm_prompt": self._prompt(),
                "code_intel_delivery": (
                    self.codeintel_delivery.model_dump(mode="json")
                    if self.codeintel_delivery is not None else None
                ),
                "index_agent_readable": (
                    self.codeintel_delivery.index_agent_readable
                    if self.codeintel_delivery is not None else None
                ),
                "served_context_tokens": settings.served_context_tokens,
                "turns": {"backend": "smithers", "smithers": self.factory.configuration()},
            },
        )

    def create(self, *, exchange: PierExchange, package: Mapping[str, str]) -> WorkflowEditHandle:
        require_authorized_route(self.route)
        require_declared_codeintel_arm(
            self.arm_set if isinstance(self.arm_set, CodeIntelligenceModeArmSet) else None,
            self.arm_id, self.codeintel_delivery,
        )
        if self.factory.model != self.route.model:
            raise UnauthorizedModelRoute("Smithers factory model differs from the extension route")
        coordinate = CellCoordinate.model_validate(exchange.coordinate.model_dump(mode="json"))
        if coordinate.arm_id != self.arm_id or package.get("instruction.md") != self._prompt():
            raise ValueError("extension arm prompt differs from its declared realization")
        image_digest = observed_image_digest(self.image)
        if exchange.binding.image_digest != image_digest:
            raise ValueError("extension image digest differs from observed built image")
        if self.repository_snapshot is not None and delivered_workspace(package) != dict(
            self.repository_snapshot
        ):
            raise ValueError("extension repository differs from its authorized snapshot")
        expected_delivery = self.prepared
        self.prepared = self._prepare(package)
        if expected_delivery is not None and self.prepared is not None and (
            expected_delivery.manifest.cache_key != self.prepared.manifest.cache_key
            or expected_delivery.tools != self.prepared.tools
            or expected_delivery.prompt_block != self.prepared.prompt_block
        ):
            raise ValueError("codeintel delivery differs from authorized configuration")
        delivery = self.codeintel_delivery
        sandbox_options = index_sandbox_options(self.prepared, delivery, self.limits)
        prefix: tuple[dict[str, Any], ...] = ()
        if self.prepared is not None and self.prepared.prompt_block is not None:
            prefix = ({"role": "user", "content": self.prepared.prompt_block},)
        cell_key = cell_idempotency_key(self.run_label, coordinate)
        completion: TurnCompletion = (
            self.completion_for(cell_key)
            if self.completion_for is not None
            else SmithersTurnCompletion(
                self.factory, cell_key, authorized=self.authorized_smithers,
            )
        )
        agent = RepositoryAgentClient(
            api_key=None, image=self.image, runs_root=self.runs_root,
            model_route=self.route, completion=completion, bounds=self._bounds(),
            tools=deepcopy(self.prepared.tools if self.prepared is not None else EXTENSION_TOOLS),
            extension_mode=True, system_prompt=EXTENSION_SYSTEM_PROMPT,
            message_prefix=prefix, writable_prefixes=self._writable_prefixes(),
            codeintel_query_script=(
                QUERY_SCRIPT if self.prepared is not None and isinstance(
                    delivery.delivery, ToolDelivery
                ) and not isinstance(delivery.mode, BaselineMode) else None
            ) if delivery is not None else None,
            codeintel_index_mount=(
                delivery.index_mount if self.prepared is not None
                and self.prepared.index_files is not None and delivery is not None else None
            ),
            codeintel_index_agent_readable=(
                delivery.index_agent_readable if delivery is not None else None
            ),
            codeintel_max_context_tokens=(
                delivery.max_context_tokens if delivery is not None else 0
            ),
            codeintel_query_limit=delivery.query_limit if delivery is not None else 0,
            sandbox_factory=self.sandbox_factory or partial(
                DockerTmpfsToolSandbox, **sandbox_options
            ),
            storage_factory=DockerTmpfsStagingStorage, sandbox_limits=self.limits,
        )
        trial = RepositoryAgentTrialClient(
            agent=agent, package=package, limits=self.limits, configuration=self.configuration()
        )
        request = bridge_protocol.TrialRequest(
            cell_id=coordinate.id, package_digest=exchange.binding.package_digest,
            exchange=bridge_protocol.PierExchange.model_validate_json(exchange.model_dump_json()),
            model_route=self.route, limits=trial_limits(self.limits, self._settings().timeout_s),
            network_policy="toolchain-only",
        )
        return WorkflowEditHandle(exchange, BridgeRuntime(trial), request)
