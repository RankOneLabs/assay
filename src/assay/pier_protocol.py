"""Core-side Pier protocol models: bind one bridge exchange to one authorized cell.

Every field a bridge request or response claims about identity/configuration is
checked here against what execution actually authorized -- the exact runtime,
image, resolved configuration, sealed package, and trial name. A mismatch on
any of them means the exchange under review is not, in fact, the one that was
priced and gated for this cell, so it is a terminal rejection here, never a
warning a caller could choose to ignore.

This module never talks to a bridge, a container, or the network -- it is
pure data and pure validation, mirroring ``integrations/pier``'s wire
contract (``TrialRequest``/``TrialResult``/``EffectiveEnforcement``) without
importing it, since the bridge project is deliberately isolated from this
one (see ``integrations/pier/README.md``).
"""

from __future__ import annotations

import hashlib
import json
from ipaddress import IPv4Address, IPv4Network
from pathlib import PurePosixPath
from typing import Annotated, Final, Literal

from pydantic import Field, model_validator

from assay.canonical import digest_bytes
from assay.models import CellCoordinate, NonEmpty, Sha256Ref, WireModel

MAX_ARTIFACT_BYTES = 8_000_000
MAX_AGGREGATE_ARTIFACT_BYTES = 32_000_000
MAX_ARTIFACT_COUNT = 1_024

ArtifactKind = Literal[
    "raw_trajectory", "candidate", "patch", "tree_digest", "result", "configuration", "transcript"
]
NetworkPolicy = Literal["egress-openrouter-only", "egress-lan-host-port", "toolchain-only"]
TRIAL_SCHEMA_VERSION = "assay-pier-trial/0.4.0"
_LAN_NETWORKS = (
    IPv4Network("10.0.0.0/8"),
    IPv4Network("172.16.0.0/12"),
    IPv4Network("192.168.0.0/16"),
)


def _canonical_relative_path(raw_path: str) -> bool:
    """Mirror the bridge's safe_relative_path wire spelling rule."""
    path = PurePosixPath(raw_path)
    return bool(
        raw_path
        and "\\" not in raw_path
        and not path.is_absolute()
        and path.parts
        and ".." not in path.parts
        and path.as_posix() == raw_path
    )


class ModelRoute(WireModel):
    endpoint: Literal["https://openrouter.ai/api/v1", "http://willie:8900"] = (
        "https://openrouter.ai/api/v1"
    )
    model: Literal[
        "anthropic/claude-3-haiku", "qwen-coder-32b", "qwen3.6-27b",
        "anthropic/claude-sonnet-5.5",
        "openai/gpt-6.1-sol", "google/gemini-4-argon", "qwen/qwen3.8-2.4t-a95b",
        "deepseek/deepseek-v4-pro", "moonshotai/kimi-k2.7-code",
        "anthropic/claude-haiku-5.5", "openai/gpt-6-luna", "google/gemini-3.8-flash",
        "qwen/qwen3.8-27b", "openai/gpt-oss-20b", "mistralai/ministral-14b-2512",
    ] = "anthropic/claude-3-haiku"
    provider: Literal[
        "amazon-bedrock", "smithers-local", "azure/us", "google-vertex/global",
        "siliconflow/fp8", "moonshotai/int4", "azure", "deepinfra/bf16", "mistral/zdr",
    ] = "amazon-bedrock"

    @model_validator(mode="after")
    def exact_route(self) -> ModelRoute:
        if (self.endpoint, self.model, self.provider) not in {
            ("https://openrouter.ai/api/v1", "anthropic/claude-3-haiku", "amazon-bedrock"),
            # Verification-pilot screening routes; OpenRouter ZDR catalogue checked
            # 2026-10-18. Claude 3 Haiku above has had no endpoints since 2026-09-30
            # and stays only so recorded wire fixtures still validate.
            ("https://openrouter.ai/api/v1", "anthropic/claude-sonnet-5.5", "amazon-bedrock"),
            ("https://openrouter.ai/api/v1", "openai/gpt-6.1-sol", "azure/us"),
            ("https://openrouter.ai/api/v1", "google/gemini-4-argon", "google-vertex/global"),
            ("https://openrouter.ai/api/v1", "qwen/qwen3.8-2.4t-a95b", "siliconflow/fp8"),
            ("https://openrouter.ai/api/v1", "deepseek/deepseek-v4-pro", "siliconflow/fp8"),
            ("https://openrouter.ai/api/v1", "moonshotai/kimi-k2.7-code", "moonshotai/int4"),
            # Self-trust small-model routes; ZDR catalogue checked 2026-10-18.
            ("https://openrouter.ai/api/v1", "anthropic/claude-haiku-5.5", "amazon-bedrock"),
            ("https://openrouter.ai/api/v1", "openai/gpt-6-luna", "azure"),
            ("https://openrouter.ai/api/v1", "google/gemini-3.8-flash", "google-vertex/global"),
            ("https://openrouter.ai/api/v1", "qwen/qwen3.8-27b", "deepinfra/bf16"),
            ("https://openrouter.ai/api/v1", "openai/gpt-oss-20b", "deepinfra/bf16"),
            ("https://openrouter.ai/api/v1", "mistralai/ministral-14b-2512", "mistral/zdr"),
            ("http://willie:8900", "qwen-coder-32b", "smithers-local"),
            ("http://willie:8900", "qwen3.6-27b", "smithers-local"),
        }:
            raise ValueError("model route fields must identify one exact route")
        return self

    @property
    def paid_route_reachable(self) -> bool:
        return self.endpoint == "https://openrouter.ai/api/v1"


class TrialLimits(WireModel):
    cpu: float = Field(gt=0, le=8, allow_inf_nan=False)
    # Wire ranges only; the workflow-edit values are qualified in
    # experiments/workflow_edit/SMOKE.md.
    memory_mb: int = Field(ge=64, le=8192)
    pids: int = Field(ge=1, le=256)
    timeout_s: float = Field(gt=0, le=1800, allow_inf_nan=False)
    storage_mb: int = Field(ge=16, le=8192)

    @model_validator(mode="after")
    def separate_budgets(self) -> TrialLimits:
        if self.memory_mb <= self.storage_mb:
            raise ValueError("memory_mb must exceed storage_mb")
        return self


class TrialRequest(WireModel):
    schema_version: Literal["assay-pier-trial/0.4.0"] = "assay-pier-trial/0.4.0"
    cell_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*:[A-Za-z0-9][A-Za-z0-9_.-]*:w[0-9]+$")
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
        if not self.model_route.paid_route_reachable and self.network_policy != "toolchain-only":
            raise ValueError("local Smithers route requires the network-disabled toolchain posture")
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


class EffectiveEnforcement(WireModel):
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


class CandidateSubmission(WireModel):
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
    # The cell's own budget ran out inside the agent loop. Distinct from the
    # infrastructure ``harness_deadline``: running out of time is the
    # candidate's outcome, not a lost coordinate.
    "agent_deadline",
    "invalid_tool_output_encoding",
    "patch_capture_conflict",
    "non_utf8_path",
    "workspace_capture_permission",
    "hard_link_submission",
]
InfrastructureCause = Literal[
    "harness_deadline",
    "cancelled",
    "container_start",
    "enforcement",
    "unexpected_exception",
    "mismatched_cell",
]


class CandidateFailure(WireModel):
    kind: Literal["candidate_failure"] = "candidate_failure"
    cause: CandidateCause
    detail: str = ""
    exception_type: str | None = None


class InfrastructureFailure(WireModel):
    kind: Literal["infrastructure_failure"] = "infrastructure_failure"
    cause: InfrastructureCause
    detail: str = ""
    exception_type: str | None = None


TrialOutcome = Annotated[
    CandidateSubmission | CandidateFailure | InfrastructureFailure,
    Field(discriminator="kind"),
]


# The manifest is what binds artifacts; it is never one of them. A "manifest"
# kind used to be required here and no honest bridge could satisfy it: the
# entry would have to declare the checksum of the very bytes containing that
# checksum. Every writer that satisfied the requirement hit the wall and
# worked around it the same way -- pointing the kind at a decoy file -- so the
# "required manifest evidence" a success was gated on was reliably satisfied
# by something that was not the manifest. ``manifest.json``'s integrity comes
# from parsing it and binding it to the authorized exchange, not from a
# self-checksum, so the kind is gone and the path is reserved instead.
MANIFEST_PATH: Final = "manifest.json"

# The checked artifacts a success is bound to; "transcript" (ATIF) is an
# optional derived view and is deliberately excluded from this set.
REQUIRED_SUCCESS_KINDS: frozenset[str] = frozenset(
    {"raw_trajectory", "candidate", "patch", "tree_digest", "result", "configuration"}
)


class RuntimeBinding(WireModel):
    """The exact runtime/image/configuration/package identity a cell's exchange is bound to."""

    runtime_id: Literal["pier"] = "pier"
    runtime_version: NonEmpty
    image_digest: Sha256Ref
    configuration_ref: Sha256Ref
    package_digest: Sha256Ref


def trial_name_for(coordinate: CellCoordinate) -> str:
    """A filesystem-safe, injective encoding of the cell's id: no colons on disk.

    A plain ``coordinate.id.replace(":", "-")`` is not injective -- ``Identifier``
    permits hyphens, so ``(subject_id="a-b", arm_id="c")`` and
    ``(subject_id="a", arm_id="b-c")`` would both normalize to ``a-b-c-w0``.
    Doubling every hyphen already present in ``subject_id``/``arm_id`` before
    joining on a single, un-doubled hyphen keeps the encoding reversible: a
    lone hyphen in the result is always a field separator, never part of a
    component's own text.
    """
    subject = coordinate.subject_id.replace("-", "--")
    arm = coordinate.arm_id.replace("-", "--")
    return f"{subject}-{arm}-w{coordinate.worker_repeat}"


class PierExchange(WireModel):
    """One bridge request/response, pinned to one ``CellCoordinate`` and ``RuntimeBinding``."""

    coordinate: CellCoordinate
    binding: RuntimeBinding
    trial_name: NonEmpty

    @model_validator(mode="after")
    def trial_name_matches_cell(self) -> PierExchange:
        if self.trial_name != trial_name_for(self.coordinate):
            raise ValueError("trial name does not match the bound cell coordinate")
        return self


def bind_exchange(*, coordinate: CellCoordinate, binding: RuntimeBinding) -> PierExchange:
    return PierExchange(
        coordinate=coordinate, binding=binding, trial_name=trial_name_for(coordinate)
    )


TrialRequest.model_rebuild()


def exchanges_match(expected: PierExchange, actual: PierExchange) -> bool:
    """A bridge response is only ever accepted against the exact exchange it was sent for."""
    return expected == actual


# Structured, JSON-shaped kinds: always UTF-8, and (checked separately, in
# ``verify_artifact_bytes``) their declared bytes must actually parse as
# JSON, not merely decode as text. "candidate" is arbitrary source in
# whatever language the trial produced -- it may or may not be UTF-8, and is
# never required to parse as anything. "transcript" (ATIF) is an optional
# derived view with the same latitude as "candidate".
JSON_STRUCTURED_ARTIFACT_KINDS: frozenset[str] = frozenset(
    {"raw_trajectory", "result", "configuration"}
)


class ArtifactEntry(WireModel):
    path: NonEmpty
    kind: ArtifactKind
    size_bytes: int = Field(ge=0, le=MAX_ARTIFACT_BYTES, strict=True)
    checksum: Sha256Ref
    utf8: bool

    @model_validator(mode="after")
    def safe_path(self) -> ArtifactEntry:
        if not _canonical_relative_path(self.path):
            raise ValueError(f"artifact path is unsafe: {self.path}")
        if self.path == MANIFEST_PATH:
            # Not merely redundant: an entry here would be checked against
            # whatever bytes arrive at ``manifest.json``, so declaring it is
            # either impossible (a self-referential checksum) or a claim
            # about a decoy. Reserving the path makes that a typed rejection
            # rather than something a writer discovers by trial and error.
            raise ValueError(f"the manifest cannot declare itself as an artifact: {self.path}")
        return self

    @model_validator(mode="after")
    def utf8_matches_kind_rule(self) -> ArtifactEntry:
        """The UTF-8 declaration is not a free per-entry choice for every kind.

        A structured JSON kind (``raw_trajectory``/``result``/
        ``configuration``) cannot declare ``utf8=False`` --
        nothing about those kinds is ever legitimately binary. ``candidate``
        and ``transcript`` are unconstrained here: whether they happen to be
        UTF-8 is a fact about the trial's own output, not something this
        type can require one way or the other.
        """
        if self.kind in JSON_STRUCTURED_ARTIFACT_KINDS and not self.utf8:
            raise ValueError(
                f"artifact kind {self.kind!r} is structured JSON and must declare utf8=True"
            )
        return self


class ArtifactManifest(WireModel):
    """Bounded, checked evidence set for one ``PierExchange``.

    ``entries`` are declared-size/checksum/type/UTF-8-rule records; the bytes
    themselves are verified against this manifest by ``verify_artifact_bytes``,
    which is the only place actual artifact content is trusted.
    """

    schema_version: Literal["assay-pier-artifact-manifest/0.2.0"] = (
        "assay-pier-artifact-manifest/0.2.0"
    )
    exchange: PierExchange
    entries: tuple[ArtifactEntry, ...]
    aggregate_bytes: int = Field(ge=0, le=MAX_AGGREGATE_ARTIFACT_BYTES, strict=True)

    @model_validator(mode="after")
    def bounded_and_unique(self) -> ArtifactManifest:
        if len(self.entries) > MAX_ARTIFACT_COUNT:
            raise ValueError("artifact manifest exceeds the artifact count limit")
        paths = [entry.path for entry in self.entries]
        if len(set(paths)) != len(paths):
            raise ValueError("duplicate artifact path in manifest")
        singular_kinds = [entry.kind for entry in self.entries if entry.kind != "candidate"]
        if len(set(singular_kinds)) != len(singular_kinds):
            raise ValueError("duplicate singular artifact kind in manifest")
        # Distinct paths may legitimately carry identical bytes (e.g. an
        # empty candidate and an empty transcript) -- the object store
        # already dedupes by content, and neither the bridge model nor this
        # manifest requires checksum uniqueness. Only path uniqueness is
        # checked.
        total = sum(entry.size_bytes for entry in self.entries)
        if total != self.aggregate_bytes:
            raise ValueError("aggregate_bytes does not match declared entry sizes")
        if total > MAX_AGGREGATE_ARTIFACT_BYTES:
            raise ValueError("artifact manifest exceeds the aggregate byte limit")
        return self

    def kinds(self) -> frozenset[str]:
        return frozenset(entry.kind for entry in self.entries)

    def has_required_success_evidence(self) -> bool:
        return self.kinds() >= REQUIRED_SUCCESS_KINDS

    def entry(self, kind: ArtifactKind) -> ArtifactEntry | None:
        if kind == "candidate":
            for candidate in self.entries:
                if candidate.kind == kind and candidate.path == "candidate-index.json":
                    return candidate
        for candidate in self.entries:
            if candidate.kind == kind:
                return candidate
        return None


class ManifestRejected(ValueError):
    """A typed, terminal rejection of one artifact manifest or its declared bytes."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def verify_artifact_bytes(manifest: ArtifactManifest, *, artifact_bytes: dict[str, bytes]) -> None:
    """Check every declared entry against the actual bytes crossing the bridge boundary.

    Raises ``ManifestRejected`` on the first mismatch -- missing, oversized,
    wrong checksum, not valid UTF-8 for a UTF-8-declared entry, or (the
    "type" half of the kind rule, distinct from the UTF-8 half) not valid
    JSON for a structured JSON kind declared UTF-8. This is the sole place
    where artifact content is trusted; the manifest's own declarations are
    otherwise just claims.
    """
    for entry in manifest.entries:
        data = artifact_bytes.get(entry.path)
        if data is None:
            raise ManifestRejected(f"declared artifact is missing: {entry.path}")
        if len(data) != entry.size_bytes:
            raise ManifestRejected(f"artifact size mismatch: {entry.path}")
        if digest_bytes(data) != entry.checksum:
            raise ManifestRejected(f"artifact checksum mismatch: {entry.path}")
        if not entry.utf8:
            continue
        try:
            text = data.decode("utf-8", errors="strict")
        except UnicodeDecodeError as error:
            raise ManifestRejected(f"artifact is not valid UTF-8: {entry.path}") from error
        if entry.kind in JSON_STRUCTURED_ARTIFACT_KINDS:
            try:
                json.loads(text)
            except ValueError as error:
                raise ManifestRejected(
                    f"artifact kind {entry.kind!r} must be valid JSON: {entry.path}"
                ) from error


def candidate_tree_digest(manifest: ArtifactManifest, *, artifact_bytes: dict[str, bytes]) -> str:
    """Recompute the observed tree from the manifest's candidate file entries."""
    indexes = [
        entry
        for entry in manifest.entries
        if entry.kind == "candidate" and entry.path == "candidate-index.json"
    ]
    if len(indexes) != 1:
        raise ManifestRejected("candidate index is missing")
    index = indexes[0]
    try:
        listed = json.loads(artifact_bytes[index.path])
    except (KeyError, ValueError) as error:
        raise ManifestRejected("candidate index is invalid") from error
    if not isinstance(listed, list) or any(not isinstance(path, str) for path in listed):
        raise ManifestRejected("candidate index must list file paths")
    files = {
        entry.path.removeprefix("candidate_files/"): artifact_bytes[entry.path]
        for entry in manifest.entries
        if entry.kind == "candidate" and entry.path.startswith("candidate_files/")
    }
    if len(listed) != len(set(listed)) or set(listed) != set(files):
        raise ManifestRejected("candidate index does not match candidate files")
    if any(
        entry.kind == "candidate"
        and entry.path != "candidate-index.json"
        and not entry.path.startswith("candidate_files/")
        for entry in manifest.entries
    ):
        raise ManifestRejected("candidate has an unexpected path")
    digest = hashlib.sha256()
    for path in sorted(files, key=lambda value: value.encode("utf-8")):
        if not _canonical_relative_path(path):
            raise ManifestRejected(f"candidate file path is unsafe: {path}")
        digest.update(path.encode("utf-8") + b"\x00100644\x00" + files[path] + b"\x00")
    return f"sha256:{digest.hexdigest()}"


def reject_on_binding_mismatch(expected: RuntimeBinding, actual: RuntimeBinding) -> None:
    if expected != actual:
        raise ManifestRejected("bridge response binding differs from the authorized runtime")


# mini-swe-agent's own terminal signal for the agent loop: only this exact
# value means the agent produced and submitted a candidate.
SUCCEEDED_EXIT_STATUS = "Submitted"


# The real bridge's ``TrialResult`` (integrations/pier's
# ``assay_pier_bridge.protocol.TrialResult``) has no top-level field for
# mini-swe-agent's own exit_status -- that signal lives inside mini's own
# result/trajectory JSON, produced entirely inside the (currently unbuilt)
# sandboxed agent loop. There is no shipped schema for that JSON today (see
# ``integrations/pier``'s "known_issue" notes), so this module makes one
# conservative, documented assumption: the parsed "result" artifact's bytes,
# if they parse as a JSON object, carry mini's own terminal status under a
# top-level ``"exit_status"`` key. Anything that fails to parse, or carries
# no such key, is treated as "not the succeeded sentinel" -- i.e. a failure,
# never silently treated as a pass.
def mini_exit_status_from_result_bytes(result_bytes: bytes | None) -> str | None:
    """Best-effort extraction of mini's own exit_status from the "result" artifact.

    Returns ``None`` on anything but a clean top-level string value -- missing
    bytes, non-UTF-8, non-JSON, a non-object payload, or a non-string value.
    ``None`` is not the succeeded sentinel, so a malformed or absent result
    artifact is conservatively a failure.
    """
    if result_bytes is None:
        return None
    try:
        value = json.loads(result_bytes.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(value, dict):
        return None
    status = value.get("exit_status")
    return status if isinstance(status, str) else None


__all__ = [
    "JSON_STRUCTURED_ARTIFACT_KINDS",
    "MANIFEST_PATH",
    "MAX_AGGREGATE_ARTIFACT_BYTES",
    "MAX_ARTIFACT_BYTES",
    "MAX_ARTIFACT_COUNT",
    "REQUIRED_SUCCESS_KINDS",
    "SUCCEEDED_EXIT_STATUS",
    "ArtifactEntry",
    "ArtifactKind",
    "ArtifactManifest",
    "ManifestRejected",
    "PierExchange",
    "RuntimeBinding",
    "bind_exchange",
    "exchanges_match",
    "mini_exit_status_from_result_bytes",
    "reject_on_binding_mismatch",
    "trial_name_for",
    "verify_artifact_bytes",
]
