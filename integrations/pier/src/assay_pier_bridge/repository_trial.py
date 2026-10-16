"""A ``PierTrialClient`` whose trial is one repository-agent attempt.

The loop runs on the host and drives a network-disabled tool container. A
submitted cell is sealed exactly like any other bridge trial: the observed
patch, final tree, trajectory, result, and resolved configuration are bound to
the authorized exchange before teardown. A cell that stops without submitting
returns a typed failure that still carries its trajectory and whatever patch
the model left behind.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping
from dataclasses import asdict
from typing import Any

from assay_pier_bridge.agent_loop import (
    CANDIDATE_STOP_CAUSES,
    SYSTEM_PROMPT,
    TOOLS,
    AgentLoopError,
    LoopBounds,
    LoopResult,
    RepositoryAgentClient,
    SandboxLimits,
)
from assay_pier_bridge.identity import canonical_json, digest_bytes, package_digest
from assay_pier_bridge.protocol import (
    CandidateSubmission,
    EffectiveEnforcement,
    ModelRoute,
    TrialRequest,
    TrialResult,
    TrialUsage,
)
from assay_pier_bridge.runtime import (
    CandidateTestTimeoutError,
    CandidateTrialError,
    InfrastructureTrialError,
    seal_observed_artifacts,
)

SUBMITTED_EXIT_STATUS = "Submitted"


def agent_configuration(
    *,
    bounds: LoopBounds,
    limits: SandboxLimits,
    writable_prefixes: tuple[str, ...],
    model_route: ModelRoute,
    extra: Mapping[str, Any] | None = None,
    tools: list[dict[str, Any]] | None = None,
    system_prompt: str = SYSTEM_PROMPT,
    message_prefix: tuple[dict[str, Any], ...] = (),
) -> dict[str, Any]:
    """The stable, authorizable description of how this loop runs a cell."""
    return {
        "loop": "assay-repository-agent/1",
        "bounds": asdict(bounds),
        "sandbox": asdict(limits),
        "storage": "docker-tmpfs",
        "network": "none",
        "writable_prefixes": list(writable_prefixes),
        "tools_sha256": digest_bytes(canonical_json(TOOLS if tools is None else tools)),
        "system_prompt_sha256": digest_bytes(system_prompt.encode("utf-8")),
        "model_route": model_route.model_dump(mode="json"),
        "attempts": 1,
        "provider_retries": 0,
        **({"message_prefix_sha256": digest_bytes(canonical_json(message_prefix))}
           if message_prefix else {}),
        **dict(extra or {}),
    }


def _tmpfs_mb(option: object) -> int:
    if not isinstance(option, str):
        return 0
    for part in option.split(","):
        if part.startswith("size="):
            size = part.removeprefix("size=")
            if size.endswith("m"):
                return int(size[:-1])
            if size.endswith("k"):
                return int(size[:-1]) // 1024
            return int(size) // (1024 * 1024)
    return 0


def _container_count(name: str) -> int | None:
    try:
        listed = subprocess.run(
            ["docker", "ps", "-aq", "--filter", f"name=^{name}$"],
            capture_output=True, text=True, timeout=30, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if listed.returncode:
        return None
    return len([line for line in listed.stdout.splitlines() if line.strip()])


class RepositoryAgentTrialHandle:
    def __init__(
        self,
        *,
        request: TrialRequest,
        agent: RepositoryAgentClient,
        package: Mapping[str, str],
        limits: SandboxLimits,
        configuration: Mapping[str, Any],
    ) -> None:
        self._request = request
        self._agent = agent
        self._package = dict(package)
        self._limits = limits
        self._configuration = dict(configuration)
        self._deadline: float | None = None
        self._partial: dict[str, bytes] = {}
        self._trajectory: dict[str, Any] = {"events": []}
        self._torn_down: EffectiveEnforcement | None = None

    def set_deadline(self, deadline: float) -> None:
        self._deadline = deadline

    def partial_artifacts(self) -> dict[str, bytes]:
        return dict(self._partial)

    def _check_request(self) -> None:
        request = self._request
        if package_digest(self._package) != request.package_digest:
            raise InfrastructureTrialError(
                "enforcement", "package does not match the request's authorized package_digest"
            )
        if request.model_route != self._agent.model_route:
            raise InfrastructureTrialError(
                "enforcement", "agent model route differs from the authorized route"
            )
        if request.network_policy != "toolchain-only":
            raise InfrastructureTrialError(
                "enforcement", "the repository agent's container has no network"
            )
        limits = request.limits
        if (
            limits.memory_mb != self._limits.memory_mb
            or limits.pids != self._limits.pids
            or limits.cpu != self._limits.cpus
            or limits.storage_mb != self._limits.storage_mb
        ):
            raise InfrastructureTrialError(
                "enforcement", "sandbox limits differ from the authorized trial limits"
            )

    def run(self) -> TrialResult:
        self._check_request()
        try:
            result = self._agent.run_cell(
                cell_id=self._request.cell_id, package=self._package, deadline=self._deadline
            )
        except AgentLoopError as error:
            self._trajectory = error.trajectory
            self._partial = {
                "trajectory.json": canonical_json(error.trajectory),
                **{f"stopped/{path}": data for path, data in error.evidence.items()},
            }
            raise self._typed(error) from error
        return self._sealed(result)

    def _typed(self, error: AgentLoopError) -> Exception:
        cause = error.cause
        if error.rejection is not None:
            return error.rejection
        if cause == "agent_deadline":
            # The candidate spent its own cell budget; the coordinate is an
            # outcome. A deadline the harness hits outside the loop (before
            # the trial starts) stays ``harness_deadline``.
            return CandidateTrialError(
                "agent_deadline", "the cell's budget expired in the agent loop"
            )
        if cause in CANDIDATE_STOP_CAUSES:
            return CandidateTrialError(
                "no_submission", f"agent stopped without submitting: {cause}"
            )
        if cause == "storage_exhausted":
            return CandidateTrialError(
                "storage_exhausted", "agent container exhausted its storage quota"
            )
        if cause == "memory_limit":
            return CandidateTrialError(
                "memory_limit", "agent container exceeded its memory ceiling"
            )
        if cause == "tool_timeout":
            return CandidateTestTimeoutError("an agent tool command exceeded its deadline")
        if cause == "container_start":
            return InfrastructureTrialError("container_start", cause)
        return InfrastructureTrialError("enforcement", f"agent loop stopped: {cause}")

    def _sealed(self, result: LoopResult) -> TrialResult:
        self._trajectory = result.trajectory
        artifacts = {
            "trajectory.json": canonical_json(result.trajectory),
            "candidate.patch": result.patch,
            "result.json": canonical_json(
                {
                    "exit_status": SUBMITTED_EXIT_STATUS,
                    "summary": result.summary,
                    "requests": result.requests,
                    "baseline_tree_digest": result.baseline_tree_digest,
                    "tree_digest": result.final_tree_digest,
                }
            ),
            "configuration.json": canonical_json(self._configuration),
        }
        self._partial = dict(artifacts)
        sealed = seal_observed_artifacts(
            self._request.exchange, artifacts, result.files, result.final_tree_digest
        )
        return TrialResult(
            cell_id=self._request.cell_id,
            outcome=CandidateSubmission(
                patch_ref=digest_bytes(result.patch),
                tree_digest=result.final_tree_digest,
                baseline_tree_digest=result.baseline_tree_digest,
            ),
            usage=TrialUsage(
                prompt_tokens=result.prompt_tokens,
                completion_tokens=result.completion_tokens,
                cost_usd=result.cost_usd,
                requests=result.requests,
            ),
            effective=self.effective_enforcement(),
            artifacts=sealed,
        )

    def _observed(self) -> tuple[str | None, dict[str, Any]]:
        for event in self._trajectory.get("events", []):
            if event.get("kind") == "sandbox_created" and isinstance(event.get("observed"), dict):
                return event.get("container"), event["observed"]
        return None, {}

    def effective_enforcement(self, *, remaining: int | None = None) -> EffectiveEnforcement:
        name, observed = self._observed()
        user = str(observed.get("user") or "0:0")
        uid, _, gid = user.partition(":")
        tmpfs = observed.get("tmpfs") or {}
        quota = _tmpfs_mb(tmpfs.get("/workspace")) + _tmpfs_mb(tmpfs.get("/cache"))
        nano_cpus = observed.get("nano_cpus") or 0
        memory = observed.get("memory_bytes") or 0
        # ``None`` means not yet verified: the result carries this before teardown.
        completed = remaining == 0
        return EffectiveEnforcement(
            uid=int(uid or 0),
            gid=int(gid or uid or 0),
            workspace_read_only=False,
            root_read_only=observed.get("readonly_rootfs") is True,
            submission_mount="/submission",
            scratch_mount="/scratch",
            scratch_mount_kind="tmpfs" if tmpfs else "unknown",
            scratch_quota_mb=quota,
            network_policy=str(observed.get("network_mode") or "unknown"),
            cpu_limit=nano_cpus / 1e9,
            memory_limit_mb=memory // (1024 * 1024),
            pids_limit=observed.get("pids_limit") or 0,
            storage_limit_mb=quota,
            containers_remaining=remaining if remaining is not None else 0,
            child_processes_remaining=0,
            teardown_completed=completed,
        )

    def teardown(self) -> EffectiveEnforcement:
        """The loop removes its own container; this verifies it is really gone."""
        if self._torn_down is None:
            name, _ = self._observed()
            remaining = _container_count(name) if name is not None else 0
            self._torn_down = self.effective_enforcement(remaining=remaining)
        return self._torn_down


class RepositoryAgentTrialClient:
    """Creates exactly one handle per ``create``; the package is fixed per client."""

    def __init__(
        self,
        *,
        agent: RepositoryAgentClient,
        package: Mapping[str, str],
        limits: SandboxLimits,
        configuration: Mapping[str, Any],
    ) -> None:
        self._agent = agent
        self._package = dict(package)
        self._limits = limits
        self._configuration = json.loads(canonical_json(dict(configuration)))

    def create(self, request: TrialRequest) -> RepositoryAgentTrialHandle:
        return RepositoryAgentTrialHandle(
            request=request,
            agent=self._agent,
            package=self._package,
            limits=self._limits,
            configuration=self._configuration,
        )
