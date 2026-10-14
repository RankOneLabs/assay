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

import shutil
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType

from assay_pier_bridge.__main__ import FALLBACK_SYSTEM_PROMPT, run_one_cell
from assay_pier_bridge.identity import canonical_json, digest_bytes, package_digest
from assay_pier_bridge.paths import (
    ArtifactCollectionRejected,
    collect_artifacts,
    materialize_under,
    regular_tree,
    submission_patch,
)
from assay_pier_bridge.protocol import (
    MANIFEST_PATH,
    MAX_AGGREGATE_ARTIFACT_BYTES,
    MAX_ARTIFACT_BYTES,
    MAX_SUBMISSION_ENTRIES,
    CandidateSubmission,
    EffectiveEnforcement,
    TrialLimits,
    TrialRequest,
    TrialResult,
    TrialUsage,
)
from assay_pier_bridge.runtime import (
    CandidateTrialError,
    TrialTimeoutError,
    seal_observed_artifacts,
)

INSTRUCTION_PATH = "instruction.md"
_DEFAULT_RUNS_ROOT = Path(__file__).resolve().parents[2] / ".trial-runs"
_DEFAULT_SYSTEM_PROMPT_PATH = Path(__file__).resolve().parents[2] / "config" / "system_prompt.md"


def _default_system_prompt() -> str:
    if _DEFAULT_SYSTEM_PROMPT_PATH.is_file():
        return _DEFAULT_SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
    return FALLBACK_SYSTEM_PROMPT


def _validated_snapshot(request: TrialRequest, package: Mapping[str, str]) -> Mapping[str, str]:
    snapshot = dict(package)
    instruction = snapshot.get(INSTRUCTION_PATH)
    if not isinstance(instruction, str) or not instruction.strip():
        raise ValueError(f"sealed package is missing a nonblank {INSTRUCTION_PATH!r}")
    if package_digest(snapshot) != request.package_digest:
        raise ValueError("sealed package does not match the authorized package_digest")
    return MappingProxyType(snapshot)


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
    # Set after construction by set_deadline; not part of the handle's identity.
    deadline: float | None = field(default=None, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "package", _validated_snapshot(self.request, self.package))

    def set_deadline(self, deadline: float) -> None:
        """Record the acceptance deadline; this route can only check it between steps.

        The guarded trial is one blocking OpenRouter call made from this
        process (see the module docstring), and ``provider.TIMEOUT_S`` is
        what bounds it. Nothing here can interrupt that call once it is in
        flight, so a cell whose inference already spent the budget is
        refused before the call rather than cut off during it.
        """
        object.__setattr__(self, "deadline", deadline)

    def _check_deadline(self) -> None:
        if self.deadline is not None and time.monotonic() >= self.deadline:
            raise TrialTimeoutError("trial exceeded its worker-acceptance deadline")

    def run(self) -> TrialResult:
        self._check_deadline()
        repository = {
            path[len("workspace/") :]: content
            for path, content in self.package.items()
            if path.startswith("workspace/")
        }
        baseline = self.submission_dir.parent / f"{self.submission_dir.name}-baseline"
        worktree = self.submission_dir / "worktree"
        baseline.mkdir()
        worktree.mkdir()
        materialize_under(baseline, repository)
        materialize_under(worktree, repository)
        instruction = self.package[INSTRUCTION_PATH]
        # Materializing two trees can itself spend what was left, so the
        # budget is read again here: this is the last point the route can
        # still refuse the cell, and nothing can interrupt the call after it.
        self._check_deadline()
        response = run_one_cell(
            instruction=instruction,
            system_prompt=self.system_prompt,
            api_key=self.api_key,
            submission_output=self.submission_dir / "output",
        )
        marker = self.submission_dir / "output"
        if marker.is_symlink():
            raise CandidateTrialError(
                "symlink_submission",
                "submission marker is a symlink",
                artifacts=self._retained_submission(),
            )
        if not marker.is_file():
            raise CandidateTrialError(
                "no_submission",
                "guarded route wrote no submission marker",
                artifacts=self._retained_submission(),
            )
        expected_baseline = {path: content.encode("utf-8") for path, content in repository.items()}
        if regular_tree(baseline) != expected_baseline:
            raise CandidateTrialError(
                "tampering",
                "immutable arm baseline changed during guarded trial",
                artifacts=self._retained_submission(),
            )
        if response.submission.source:
            (worktree / "output").write_text(response.submission.source, encoding="utf-8")
        patch = submission_patch(baseline, worktree)
        (self.submission_dir / "trajectory.json").write_bytes(
            canonical_json(
                {"messages": [response.message], "submitted_call_id": response.submission.call_id}
            )
        )
        (self.submission_dir / "result.json").write_bytes(
            canonical_json(
                {
                    "exit_status": "Submitted",
                    "usage": {
                        "prompt_tokens": response.usage.prompt_tokens,
                        "completion_tokens": response.usage.completion_tokens,
                        "cost_usd": response.usage.cost_usd,
                        "requests": 1,
                    },
                }
            )
        )
        (self.submission_dir / "configuration.json").write_bytes(
            canonical_json(
                {
                    "model_route": self.request.model_route.model_dump(mode="json"),
                    "limits": self.request.limits.model_dump(mode="json"),
                }
            )
        )
        artifacts = collect_artifacts(
            self.submission_dir,
            max_bytes=MAX_ARTIFACT_BYTES,
            max_aggregate_bytes=MAX_AGGREGATE_ARTIFACT_BYTES,
            max_entries=MAX_SUBMISSION_ENTRIES,
            aggregate_exempt_path=MANIFEST_PATH,
            excluded_roots=frozenset({"worktree"}),
        )
        if "candidate.patch" in artifacts:
            raise CandidateTrialError(
                "tampering", "candidate attempted to replace host patch", artifacts=artifacts
            )
        artifacts["candidate.patch"] = patch.patch
        artifacts = seal_observed_artifacts(
            self.request.exchange, artifacts, regular_tree(worktree), patch.final_tree_digest
        )
        (self.submission_dir / MANIFEST_PATH).write_bytes(artifacts[MANIFEST_PATH])
        return TrialResult(
            cell_id=self.request.cell_id,
            outcome=CandidateSubmission(
                patch_ref=digest_bytes(patch.patch),
                tree_digest=patch.final_tree_digest,
                baseline_tree_digest=patch.baseline_tree_digest,
            ),
            usage=TrialUsage(
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
                cost_usd=response.usage.cost_usd,
                requests=1,
            ),
            effective=self.effective_enforcement(),
            artifacts=artifacts,
        )

    def partial_artifacts(self) -> dict[str, bytes]:
        return collect_artifacts(
            self.submission_dir,
            max_bytes=MAX_ARTIFACT_BYTES,
            max_aggregate_bytes=MAX_AGGREGATE_ARTIFACT_BYTES,
            max_entries=MAX_SUBMISSION_ENTRIES,
            aggregate_exempt_path=MANIFEST_PATH,
            excluded_roots=frozenset({"worktree"}),
        )

    def _retained_submission(self) -> dict[str, bytes]:
        try:
            return self.partial_artifacts()
        except ArtifactCollectionRejected as rejection:
            return rejection.artifacts
        except Exception:
            return {}

    def effective_enforcement(self) -> EffectiveEnforcement:
        return _host_enforcement(self.request.limits)

    def teardown(self) -> EffectiveEnforcement:
        shutil.rmtree(self.submission_dir, ignore_errors=True)
        shutil.rmtree(
            self.submission_dir.parent / f"{self.submission_dir.name}-baseline", ignore_errors=True
        )
        return _host_enforcement(self.request.limits)


@dataclass(frozen=True, slots=True)
class GuardedCompletionTrialClient:
    """Creates exactly one ``GuardedCompletionTrialHandle`` per ``create`` call."""

    package: Mapping[str, str]
    api_key: str
    runs_root: Path = _DEFAULT_RUNS_ROOT
    system_prompt: str = field(default_factory=_default_system_prompt)

    def create(self, request: TrialRequest) -> GuardedCompletionTrialHandle:
        package = _validated_snapshot(request, self.package)
        submission_dir = self.runs_root / f"guarded-{uuid.uuid4().hex[:12]}"
        submission_dir.mkdir(parents=True, exist_ok=True)
        return GuardedCompletionTrialHandle(
            request=request,
            package=package,
            api_key=self.api_key,
            submission_dir=submission_dir,
            system_prompt=self.system_prompt,
        )


__all__ = ["GuardedCompletionTrialClient", "GuardedCompletionTrialHandle"]
