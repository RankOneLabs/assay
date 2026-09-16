"""Closed wire contracts for the Pier bridge: exactly one trial per cell.

This module never imports a real Pier SDK. ``PierTrialClient`` is the local
boundary contract a real client must satisfy; the bridge is injected with an
implementation, never bound to one at import time, so the isolated bridge
project has no dependency on Pier's own package (see integrations/pier/README.md
for why that dependency cannot be pinned from this environment today).
"""

from __future__ import annotations

from typing import Annotated, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Sha256Ref = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]
Identifier = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")]
# Mirrors assay.models.CellCoordinate.id: "<subject_id>:<arm_id>:w<worker_repeat>".
CellId = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*:[A-Za-z0-9][A-Za-z0-9_.-]*:w[0-9]+$"),
]

TrialStatus = Literal["succeeded", "failed", "timeout", "cancelled"]


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
    memory_mb: int = Field(ge=64, le=8192)
    pids: int = Field(ge=1, le=256)
    timeout_s: float = Field(gt=0, le=1800, allow_inf_nan=False)


class BridgeIdentity(ClosedModel):
    """Runtime identity inputs pinned for a bridge sync; never mutated at serve time."""

    pier_revision: str = Field(min_length=1)
    mini_swe_agent_revision: str = Field(min_length=1)
    lock_digest: Sha256Ref
    bridge_image_digest: Sha256Ref


class TrialRequest(ClosedModel):
    """One authorized cell. ``verify`` is always disabled: Assay is the authority."""

    cell_id: CellId
    package_digest: Sha256Ref
    model_route: ModelRoute
    limits: TrialLimits
    verify: Literal[False] = False
    network_policy: Literal["egress-openrouter-only"] = "egress-openrouter-only"


class TrialUsage(ClosedModel):
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    cost_usd: float = Field(ge=0, allow_inf_nan=False)
    requests: int = Field(ge=0)


class EffectiveEnforcement(ClosedModel):
    """Observed, not declared: what the trial's execution boundary actually did."""

    uid: int = Field(ge=1)
    gid: int = Field(ge=1)
    workspace_read_only: bool
    submission_mount: str = Field(pattern=r"^/submission$")
    scratch_mount: str = Field(pattern=r"^/scratch$")
    network_policy: str = Field(min_length=1)
    cpu_limit: float = Field(gt=0, allow_inf_nan=False)
    memory_limit_mb: int = Field(ge=1)
    pids_limit: int = Field(ge=1)
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


class TrialResult(ClosedModel):
    cell_id: CellId
    status: TrialStatus
    submission_ref: Sha256Ref | None = None
    usage: TrialUsage | None = None
    error_type: str | None = None
    error_message: str | None = None
    effective: EffectiveEnforcement

    @model_validator(mode="after")
    def consistent_status(self) -> TrialResult:
        if self.status == "succeeded":
            if self.submission_ref is None or self.error_type is not None:
                raise ValueError("a succeeded trial needs a submission and no error")
        elif self.submission_ref is not None or not self.error_type:
            raise ValueError("a non-succeeded trial needs an error and no submission")
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
