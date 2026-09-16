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

from pathlib import PurePosixPath
from typing import Literal

from pydantic import Field, model_validator

from assay.canonical import digest_bytes
from assay.models import CellCoordinate, NonEmpty, Sha256Ref, WireModel

MAX_ARTIFACT_BYTES = 8_000_000
MAX_AGGREGATE_ARTIFACT_BYTES = 32_000_000

ArtifactKind = Literal[
    "raw_trajectory", "candidate", "result", "configuration", "manifest", "transcript"
]

# The five checked artifacts a success is bound to; "transcript" (ATIF) is an
# optional derived view and is deliberately excluded from this set.
REQUIRED_SUCCESS_KINDS: frozenset[str] = frozenset(
    {"raw_trajectory", "candidate", "result", "configuration", "manifest"}
)


class RuntimeBinding(WireModel):
    """The exact runtime/image/configuration/package identity a cell's exchange is bound to."""

    runtime_id: Literal["pier"] = "pier"
    runtime_version: NonEmpty
    image_digest: Sha256Ref
    configuration_ref: Sha256Ref
    package_digest: Sha256Ref


def trial_name_for(coordinate: CellCoordinate) -> str:
    """Mirror ``assay_pier_bridge.pier_adapter.sanitized_trial_name``: no colons on disk."""
    return coordinate.id.replace(":", "-")


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


def exchanges_match(expected: PierExchange, actual: PierExchange) -> bool:
    """A bridge response is only ever accepted against the exact exchange it was sent for."""
    return expected == actual


class ArtifactEntry(WireModel):
    path: NonEmpty
    kind: ArtifactKind
    size_bytes: int = Field(ge=0, le=MAX_ARTIFACT_BYTES, strict=True)
    checksum: Sha256Ref
    utf8: bool

    @model_validator(mode="after")
    def safe_path(self) -> ArtifactEntry:
        parts = PurePosixPath(self.path).parts
        if PurePosixPath(self.path).is_absolute() or any(part in {"", ".", ".."} for part in parts):
            raise ValueError(f"artifact path is unsafe: {self.path}")
        return self


class ArtifactManifest(WireModel):
    """Bounded, checked evidence set for one ``PierExchange``.

    ``entries`` are declared-size/checksum/type/UTF-8-rule records; the bytes
    themselves are verified against this manifest by ``verify_artifact_bytes``,
    which is the only place actual artifact content is trusted.
    """

    schema_version: Literal[
        "assay-pier-artifact-manifest/0.1.0"
    ] = "assay-pier-artifact-manifest/0.1.0"
    exchange: PierExchange
    entries: tuple[ArtifactEntry, ...]
    aggregate_bytes: int = Field(ge=0, le=MAX_AGGREGATE_ARTIFACT_BYTES, strict=True)

    @model_validator(mode="after")
    def bounded_and_unique(self) -> ArtifactManifest:
        paths = [entry.path for entry in self.entries]
        if len(set(paths)) != len(paths):
            raise ValueError("duplicate artifact path in manifest")
        checksums = [entry.checksum for entry in self.entries]
        if len(set(checksums)) != len(checksums):
            raise ValueError("duplicate artifact checksum in manifest")
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
    wrong checksum, or (for a UTF-8-declared entry) not valid UTF-8. This is
    the sole point where artifact content is trusted; the manifest's own
    declarations are otherwise just claims.
    """
    for entry in manifest.entries:
        data = artifact_bytes.get(entry.path)
        if data is None:
            raise ManifestRejected(f"declared artifact is missing: {entry.path}")
        if len(data) != entry.size_bytes:
            raise ManifestRejected(f"artifact size mismatch: {entry.path}")
        if digest_bytes(data) != entry.checksum:
            raise ManifestRejected(f"artifact checksum mismatch: {entry.path}")
        if entry.utf8:
            try:
                data.decode("utf-8", errors="strict")
            except UnicodeDecodeError as error:
                raise ManifestRejected(f"artifact is not valid UTF-8: {entry.path}") from error


def reject_on_binding_mismatch(expected: RuntimeBinding, actual: RuntimeBinding) -> None:
    if expected != actual:
        raise ManifestRejected("bridge response binding differs from the authorized runtime")


# mini-swe-agent's own terminal signal for the agent loop: only this exact
# value means the agent actually produced and submitted a candidate. Every
# other value (e.g. "LimitsExceeded", "Error") is a partial/failed run, and
# Pier's own ``exception_info`` being non-null is independently terminal.
SUCCEEDED_EXIT_STATUS = "Submitted"


def bridge_reports_failure(*, exception_info: str | None, exit_status: str | None) -> bool:
    """Neither Pier's ``exception_info`` nor mini's ``exit_status`` may indicate failure."""
    if exception_info is not None:
        return True
    return exit_status != SUCCEEDED_EXIT_STATUS


__all__ = [
    "MAX_AGGREGATE_ARTIFACT_BYTES",
    "MAX_ARTIFACT_BYTES",
    "REQUIRED_SUCCESS_KINDS",
    "SUCCEEDED_EXIT_STATUS",
    "ArtifactEntry",
    "ArtifactKind",
    "ArtifactManifest",
    "ManifestRejected",
    "PierExchange",
    "RuntimeBinding",
    "bind_exchange",
    "bridge_reports_failure",
    "exchanges_match",
    "reject_on_binding_mismatch",
    "trial_name_for",
    "verify_artifact_bytes",
]
