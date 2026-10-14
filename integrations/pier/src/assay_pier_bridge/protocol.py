"""Closed wire contracts for the Pier bridge: exactly one trial per cell.

This module never imports a real Pier SDK. ``PierTrialClient`` is the local
boundary contract a real client must satisfy; the bridge is injected with an
implementation, never bound to one at import time, so the isolated bridge
project has no dependency on Pier's own package (see integrations/pier/README.md
for why that dependency cannot be pinned from this environment today).
"""

from __future__ import annotations

from ipaddress import IPv4Address, IPv4Network
from typing import Annotated, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from assay_pier_bridge.paths import safe_relative_path

Sha256Ref = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]
Identifier = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")]
# Mirrors assay.models.CellCoordinate.id: "<subject_id>:<arm_id>:w<worker_repeat>".
CellId = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*:[A-Za-z0-9][A-Za-z0-9_.-]*:w[0-9]+$"),
]

NetworkPolicy = Literal["egress-openrouter-only", "egress-lan-host-port", "toolchain-only"]
TRIAL_SCHEMA_VERSION = "assay-pier-trial/0.3.0"
_LAN_NETWORKS = (
    IPv4Network("10.0.0.0/8"),
    IPv4Network("172.16.0.0/12"),
    IPv4Network("192.168.0.0/16"),
)

# Mirrors assay.pier_protocol's ceilings. Artifact bytes are bounded here,
# at the point they are collected, as well as by the consumer: a trial whose
# submission mount filled up must fail as an oversized result, not stream an
# unbounded read into the caller's memory first.
MAX_ARTIFACT_BYTES = 8_000_000
MAX_AGGREGATE_ARTIFACT_BYTES = 32_000_000
# The reserved manifest is the document binding the artifacts, not one of
# the artifacts it declares, so it is excluded from this count just as it is
# excluded from the aggregate byte limit.
MAX_ARTIFACT_COUNT = 1_024
# Filesystem enumeration needs a separate ceiling because directories are
# not artifacts but still consume host memory before collection can sort the
# paths. Keep this local operational bound distinct from the wire artifact
# count so directories never consume advertised artifact slots.
MAX_SUBMISSION_ENTRIES = 4_096

# Mirrors assay.pier_protocol.MANIFEST_PATH: the reserved path of the document
# that binds the artifacts, which is never one of them. Both projects exempt
# it from the aggregate ceiling and both still bound it per-artifact; the
# shared fixture asserted by tests/test_wire_contract.py pins that rule, since
# nothing else connects the two copies.
MANIFEST_PATH = "manifest.json"


class ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ModelRoute(ClosedModel):
    """The exact guarded OpenRouter route a trial is authorized to call.

    Exact ``Literal`` values, not permissive patterns: this is the only
    route ``GuardedOpenRouterClient`` (provider.py) ever calls, so a caller
    must not be able to authorize a route that execution then silently
    ignores in favor of a different one.
    """

    endpoint: Literal["https://openrouter.ai/api/v1"] = "https://openrouter.ai/api/v1"
    model: Literal["anthropic/claude-3-haiku"] = "anthropic/claude-3-haiku"
    provider: Literal["amazon-bedrock"] = "amazon-bedrock"


class TrialLimits(ClosedModel):
    cpu: float = Field(gt=0, le=8, allow_inf_nan=False)
    # Provisional storage/memory/PID bounds: replace after the footprint runs
    # in experiments/workflow_edit/SMOKE.md (wf-12).
    memory_mb: int = Field(ge=64, le=8192)
    pids: int = Field(ge=1, le=256)
    timeout_s: float = Field(gt=0, le=1800, allow_inf_nan=False)
    # /scratch is a quota-backed host bind mount, independent of the memory cgroup.
    storage_mb: int = Field(ge=16, le=8192)

    @model_validator(mode="after")
    def separate_budgets(self) -> TrialLimits:
        if self.memory_mb <= self.storage_mb:
            raise ValueError("memory_mb must exceed storage_mb")
        return self


class BridgeIdentity(ClosedModel):
    """Runtime identity inputs pinned for a bridge sync; never mutated at serve time."""

    pier_revision: str = Field(min_length=1)
    mini_swe_agent_revision: str = Field(min_length=1)
    lock_digest: Sha256Ref
    bridge_image_digest: Sha256Ref


class CellCoordinate(ClosedModel):
    subject_id: Identifier
    arm_id: Identifier
    worker_repeat: int = Field(ge=0)
    realization_ref: Sha256Ref

    @property
    def id(self) -> str:
        return f"{self.subject_id}:{self.arm_id}:w{self.worker_repeat}"


class RuntimeBinding(ClosedModel):
    runtime_id: Literal["pier"] = "pier"
    runtime_version: str = Field(min_length=1)
    image_digest: Sha256Ref
    configuration_ref: Sha256Ref
    package_digest: Sha256Ref


class PierExchange(ClosedModel):
    coordinate: CellCoordinate
    binding: RuntimeBinding
    trial_name: str = Field(min_length=1)

    @model_validator(mode="after")
    def valid_name(self) -> PierExchange:
        subject = self.coordinate.subject_id.replace("-", "--")
        arm = self.coordinate.arm_id.replace("-", "--")
        if self.trial_name != f"{subject}-{arm}-w{self.coordinate.worker_repeat}":
            raise ValueError("trial name does not match the bound cell coordinate")
        return self


class TrialRequest(ClosedModel):
    """One authorized cell. ``verify`` is always disabled: Assay is the authority."""

    schema_version: Literal["assay-pier-trial/0.3.0"] = "assay-pier-trial/0.3.0"
    cell_id: CellId
    package_digest: Sha256Ref
    exchange: PierExchange
    model_route: ModelRoute
    limits: TrialLimits
    verify: Literal[False] = False
    network_policy: NetworkPolicy = "egress-openrouter-only"
    egress_host: str | None = None
    egress_port: int | None = Field(default=None, ge=1, le=65535)

    @model_validator(mode="after")
    def closed_egress(self) -> TrialRequest:
        if self.exchange.coordinate.id != self.cell_id:
            raise ValueError("exchange coordinate does not match cell_id")
        if self.exchange.binding.package_digest != self.package_digest:
            raise ValueError("exchange package digest does not match package_digest")
        if self.network_policy == "egress-lan-host-port":
            if self.egress_host is None or self.egress_port is None:
                raise ValueError("LAN posture requires egress_host and egress_port")
            try:
                address = IPv4Address(self.egress_host)
            except ValueError as error:
                raise ValueError("egress_host must be a LAN IPv4 address") from error
            if not any(address in network for network in _LAN_NETWORKS):
                raise ValueError("egress_host must be a LAN IPv4 address")
        elif self.egress_host is not None or self.egress_port is not None:
            raise ValueError("egress_host and egress_port require the LAN posture")
        return self


class TrialUsage(ClosedModel):
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    cost_usd: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    requests: int = Field(ge=0)


class EffectiveEnforcement(ClosedModel):
    """Observed, not declared: what the trial's execution boundary actually did."""

    uid: int = Field(ge=0)
    gid: int = Field(ge=0)
    workspace_read_only: bool
    root_read_only: bool = False
    submission_mount: str = Field(pattern=r"^/submission$")
    scratch_mount: str = Field(pattern=r"^/scratch$")
    scratch_mount_kind: str = "unknown"
    scratch_quota_mb: int = Field(default=0, ge=0)
    network_policy: str = Field(min_length=1)
    cpu_limit: float = Field(ge=0, allow_inf_nan=False)
    memory_limit_mb: int = Field(ge=0)
    pids_limit: int = Field(ge=0)
    storage_limit_mb: int = Field(ge=0)
    containers_remaining: int = Field(ge=0)
    child_processes_remaining: int = Field(ge=0)
    teardown_completed: bool

    @model_validator(mode="after")
    def clean_teardown(self) -> EffectiveEnforcement:
        if self.teardown_completed and (
            self.containers_remaining != 0 or self.child_processes_remaining != 0
        ):
            raise ValueError("teardown cannot be complete with resources still remaining")
        return self


class CandidateSubmission(ClosedModel):
    kind: Literal["candidate"] = "candidate"
    patch_ref: Sha256Ref
    tree_digest: Sha256Ref
    baseline_tree_digest: Sha256Ref


CandidateCause = Literal[
    "no_submission",
    "symlink_submission",
    "traversal",
    "escaping_symlink",
    "binary_payload",
    "oversized_artifact",
    "aggregate_artifact_limit",
    "entry_limit",
    "out_of_scope_edit",
    "tampering",
    "candidate_test_timeout",
    "nonzero_exit",
    "storage_exhausted",
    "memory_limit",
]
InfrastructureCause = Literal[
    "harness_deadline",
    "cancelled",
    "container_start",
    "enforcement",
    "unexpected_exception",
    "mismatched_cell",
]


class CandidateFailure(ClosedModel):
    kind: Literal["candidate_failure"] = "candidate_failure"
    cause: CandidateCause
    detail: str = ""
    exception_type: str | None = None


class InfrastructureFailure(ClosedModel):
    kind: Literal["infrastructure_failure"] = "infrastructure_failure"
    cause: InfrastructureCause
    detail: str = ""
    exception_type: str | None = None


TrialOutcome = Annotated[
    CandidateSubmission | CandidateFailure | InfrastructureFailure,
    Field(discriminator="kind"),
]


class TrialResult(ClosedModel):
    """One trial's outcome, including whatever evidence bytes it produced.

    ``artifacts`` maps a relative path to the exact bytes the trial wrote --
    the candidate source at minimum, plus whatever trajectory/result/
    configuration files a sandboxed agent loop writes alongside it. It is a
    real part of this contract rather than the caller's problem: the bytes
    exist only inside the trial's own submission mount, which ``teardown``
    destroys, so a result that did not carry them out could never be
    turned into durable evidence.

    Successful handles bind their observed artifact bytes to the request's
    authorized exchange in ``manifest.json`` before teardown.
    """

    cell_id: CellId
    outcome: TrialOutcome
    usage: TrialUsage | None = None
    effective: EffectiveEnforcement
    artifacts: dict[str, bytes] = Field(default_factory=dict)

    @model_validator(mode="after")
    def bounded_artifacts(self) -> TrialResult:
        """The per-artifact ceiling applies to every blob; the aggregate one
        does not apply to ``manifest.json``.

        ``MAX_AGGREGATE_ARTIFACT_BYTES`` bounds what a manifest may *declare*,
        and the manifest is never one of its own entries. Charging the binding
        document to the budget it bounds would make a manifest declaring the
        maximum permitted aggregate impossible to return at all: the bytes
        would fit, and then the few hundred bytes describing them would push
        the result over and fail the whole trial. An honest bridge at the
        ceiling would have no way to report what it produced. What a trial can
        hand back is still bounded, just by ``MAX_AGGREGATE_ARTIFACT_BYTES +
        MAX_ARTIFACT_BYTES``.
        """
        artifact_count = sum(path != MANIFEST_PATH for path in self.artifacts)
        if artifact_count > MAX_ARTIFACT_COUNT:
            raise ValueError("artifacts exceed the artifact count limit")
        total = 0
        for path, data in self.artifacts.items():
            safe_relative_path(path)
            if len(data) > MAX_ARTIFACT_BYTES:
                raise ValueError(f"artifact exceeds the per-artifact byte limit: {path}")
            if path != MANIFEST_PATH:
                total += len(data)
        if total > MAX_AGGREGATE_ARTIFACT_BYTES:
            raise ValueError("artifacts exceed the aggregate byte limit")
        return self


class TrialHandle(Protocol):
    """One created trial. Every method after ``teardown`` must be a no-op-safe read."""

    def run(self) -> TrialResult: ...

    def effective_enforcement(self) -> EffectiveEnforcement: ...

    def teardown(self) -> EffectiveEnforcement: ...


class PierTrialClient(Protocol):
    """The local contract a real Pier SDK client must satisfy.

    ``create`` is called exactly once per bridge request (see runtime.py); a
    client that resolves dependencies, installs packages, or mutates a
    pricing map inside ``create``/``run`` violates the locked-runtime
    decision and must fail the lifecycle tests.
    """

    def create(self, request: TrialRequest) -> TrialHandle: ...
