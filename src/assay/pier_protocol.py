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

import json
from pathlib import PurePosixPath
from typing import Final, Literal

from pydantic import Field, model_validator

from assay.canonical import digest_bytes
from assay.models import CellCoordinate, NonEmpty, Sha256Ref, WireModel

MAX_ARTIFACT_BYTES = 8_000_000
MAX_AGGREGATE_ARTIFACT_BYTES = 32_000_000
MAX_ARTIFACT_COUNT = 1_024

ArtifactKind = Literal["raw_trajectory", "candidate", "result", "configuration", "transcript"]

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

# The four checked artifacts a success is bound to; "transcript" (ATIF) is an
# optional derived view and is deliberately excluded from this set.
REQUIRED_SUCCESS_KINDS: frozenset[str] = frozenset(
    {"raw_trajectory", "candidate", "result", "configuration"}
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
        parts = PurePosixPath(self.path).parts
        if PurePosixPath(self.path).is_absolute() or any(part in {"", ".", ".."} for part in parts):
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

    schema_version: Literal[
        "assay-pier-artifact-manifest/0.1.0"
    ] = "assay-pier-artifact-manifest/0.1.0"
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


def reject_on_binding_mismatch(expected: RuntimeBinding, actual: RuntimeBinding) -> None:
    if expected != actual:
        raise ManifestRejected("bridge response binding differs from the authorized runtime")


# mini-swe-agent's own terminal signal for the agent loop: only this exact
# value means the agent actually produced and submitted a candidate. Every
# other value (e.g. "LimitsExceeded", "Error") is a partial/failed run, and
# Pier's own reported failure (a non-"succeeded" ``status``, a set
# ``error_type``, or a missing ``submission_ref``) is independently terminal.
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
    ``bridge_reports_failure`` treats ``None`` as "not the succeeded sentinel",
    so a malformed or absent result artifact is conservatively a failure.
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


def bridge_reports_failure(
    *,
    status: str,
    submission_ref: str | None,
    error_type: str | None,
    mini_exit_status: str | None,
) -> bool:
    """Both Pier's own trial status and mini's embedded exit_status must pass.

    Mirrors ``assay_pier_bridge.protocol.TrialResult``'s own consistency rule
    (a "succeeded" trial has a submission and no error; anything else is a
    failure) as an independent, defense-in-depth check on this side of the
    isolation boundary -- a bridge response is never trusted structurally
    just because it claims ``status="succeeded"``.
    """
    pier_signal_ok = status == "succeeded" and submission_ref is not None and error_type is None
    return not pier_signal_ok or mini_exit_status != SUCCEEDED_EXIT_STATUS


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
    "bridge_reports_failure",
    "exchanges_match",
    "mini_exit_status_from_result_bytes",
    "reject_on_binding_mismatch",
    "trial_name_for",
    "verify_artifact_bytes",
]
