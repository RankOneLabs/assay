"""The real, currently-functional one-cell trial client — no Docker involved.

Review-round discussion (PR #24, "Y"): ``DockerTrialClient`` always starts a
container with ``--network none`` — required, since Pier's own
``NetworkPolicyFieldsMixin`` has no egress-allowlist mode (README.md, "Pier
revision") — which means a process running *inside* that container can
never reach OpenRouter. Until a real sandboxed agent loop exists to run
inside the container (see ``pier_adapter.py``'s module docstring, recorded
as a ``known_issue``), the one guarded model call *is* the entire trial,
and it can only be made from this host process — never from inside the
network-isolated sandbox.

``GuardedCompletionTrialClient`` is the ``PierTrialClient`` a real trial is
actually run through today. ``DockerTrialClient`` remains the tested,
real-Docker lifecycle harness proving the sandbox's mount/uid/resource/
teardown guarantees for whatever sandboxed agent work the real mini-swe-agent
loop adds later — the two are not competing implementations of the same
thing, they cover different halves of the eventual design.
"""

from __future__ import annotations

import hashlib
import shutil
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from assay_pier_bridge.__main__ import FALLBACK_SYSTEM_PROMPT, run_one_cell
from assay_pier_bridge.protocol import (
    EffectiveEnforcement,
    TrialLimits,
    TrialRequest,
    TrialResult,
)

INSTRUCTION_PATH = "instruction.md"
_DEFAULT_RUNS_ROOT = Path(__file__).resolve().parents[2] / ".trial-runs"
_DEFAULT_SYSTEM_PROMPT_PATH = Path(__file__).resolve().parents[2] / "config" / "system_prompt.md"


def _default_system_prompt() -> str:
    if _DEFAULT_SYSTEM_PROMPT_PATH.is_file():
        return _DEFAULT_SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
    return FALLBACK_SYSTEM_PROMPT


def _digest(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def _host_enforcement(limits: TrialLimits) -> EffectiveEnforcement:
    """No container runs for this client: every sandbox field reports what
    is actually true of a bare host call, never a claim about isolation
    this client does not provide."""
    return EffectiveEnforcement(
        uid=1000,
        gid=1000,
        workspace_read_only=True,
        submission_mount="/submission",
        scratch_mount="/scratch",
        network_policy="host-process-guarded-route-only",
        cpu_limit=limits.cpu,
        memory_limit_mb=limits.memory_mb,
        pids_limit=limits.pids,
        storage_limit_mb=limits.storage_mb,
        containers_remaining=0,
        child_processes_remaining=0,
        teardown_completed=True,
    )


@dataclass(frozen=True, slots=True)
class GuardedCompletionTrialHandle:
    """One trial's guarded call, made from this host process."""

    request: TrialRequest
    package: Mapping[str, str]
    api_key: str
    submission_dir: Path
    system_prompt: str = field(default_factory=_default_system_prompt)

    def run(self) -> TrialResult:
        instruction = self.package.get(INSTRUCTION_PATH)
        if not instruction:
            raise ValueError(f"sealed package is missing {INSTRUCTION_PATH!r}")
        source = run_one_cell(
            instruction=instruction,
            system_prompt=self.system_prompt,
            api_key=self.api_key,
            submission_output=self.submission_dir / "output",
        )
        return TrialResult(
            cell_id=self.request.cell_id,
            status="succeeded",
            submission_ref=_digest(source.encode("utf-8")),
            effective=self.effective_enforcement(),
        )

    def effective_enforcement(self) -> EffectiveEnforcement:
        return _host_enforcement(self.request.limits)

    def teardown(self) -> EffectiveEnforcement:
        shutil.rmtree(self.submission_dir, ignore_errors=True)
        return _host_enforcement(self.request.limits)


@dataclass(frozen=True, slots=True)
class GuardedCompletionTrialClient:
    """Creates exactly one ``GuardedCompletionTrialHandle`` per ``create`` call."""

    package: Mapping[str, str]
    api_key: str
    runs_root: Path = _DEFAULT_RUNS_ROOT
    system_prompt: str = field(default_factory=_default_system_prompt)

    def create(self, request: TrialRequest) -> GuardedCompletionTrialHandle:
        submission_dir = self.runs_root / f"guarded-{uuid.uuid4().hex[:12]}"
        submission_dir.mkdir(parents=True, exist_ok=True)
        return GuardedCompletionTrialHandle(
            request=request,
            package=self.package,
            api_key=self.api_key,
            submission_dir=submission_dir,
            system_prompt=self.system_prompt,
        )


__all__ = ["GuardedCompletionTrialClient", "GuardedCompletionTrialHandle"]
