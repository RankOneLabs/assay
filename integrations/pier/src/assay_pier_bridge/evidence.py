"""Seal host-observed trial artifacts against the authorized exchange."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Literal

from pydantic import Field, model_validator

from assay_pier_bridge.identity import canonical_json, digest_bytes
from assay_pier_bridge.paths import ArtifactCollectionRejected, safe_relative_path
from assay_pier_bridge.protocol import (
    MANIFEST_PATH,
    MAX_AGGREGATE_ARTIFACT_BYTES,
    MAX_ARTIFACT_BYTES,
    MAX_ARTIFACT_COUNT,
    ClosedModel,
    PierExchange,
    Sha256Ref,
    TrialUsage,
)

ArtifactKind = Literal["raw_trajectory", "candidate", "result", "configuration", "transcript"]
KINDS: dict[str, ArtifactKind] = {
    "trajectory.json": "raw_trajectory",
    "candidate.patch": "candidate",
    "result.json": "result",
    "configuration.json": "configuration",
    "transcript.json": "transcript",
}
REQUIRED_PATHS = frozenset(
    {"trajectory.json", "candidate.patch", "result.json", "configuration.json"}
)


class ArtifactEntry(ClosedModel):
    path: str
    kind: ArtifactKind
    size_bytes: int = Field(ge=0, le=MAX_ARTIFACT_BYTES)
    checksum: Sha256Ref
    utf8: bool

    @model_validator(mode="after")
    def valid_path(self) -> ArtifactEntry:
        safe_relative_path(self.path)
        if self.path == MANIFEST_PATH:
            raise ValueError("manifest cannot declare itself")
        return self


class ArtifactManifest(ClosedModel):
    schema_version: Literal["assay-pier-artifact-manifest/0.1.0"] = (
        "assay-pier-artifact-manifest/0.1.0"
    )
    exchange: PierExchange
    entries: tuple[ArtifactEntry, ...]
    aggregate_bytes: int = Field(ge=0, le=MAX_AGGREGATE_ARTIFACT_BYTES)

    @model_validator(mode="after")
    def bounded(self) -> ArtifactManifest:
        if len(self.entries) > MAX_ARTIFACT_COUNT:
            raise ValueError("artifact manifest exceeds the artifact count limit")
        if len({entry.path for entry in self.entries}) != len(self.entries):
            raise ValueError("artifact manifest has duplicate paths")
        if sum(entry.size_bytes for entry in self.entries) != self.aggregate_bytes:
            raise ValueError("aggregate_bytes does not match entries")
        return self


def _nonnegative_int(value: object) -> int | None:
    """One count, or ``None`` if it is not a usable one.

    ``bool`` is an ``int`` subclass, so a JSON ``true`` would otherwise pass
    as the count 1.
    """
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def worker_usage_from_result_bytes(result_bytes: bytes | None) -> TrialUsage | None:
    """Best-effort token counts from the worker's own ``result.json``.

    Mirrors ``assay.pier_protocol.mini_exit_status_from_result_bytes``: the
    worker's result artifact is untrusted input read defensively, so anything
    but clean nonnegative integer counts yields ``None`` -- which Assay
    reports as ``uncertain`` coverage rather than inventing a number.

    ``cost_usd`` is always ``None``. A worker behind no pricing model cannot
    observe a cost, and reporting 0.0 would be recorded downstream as a
    confident measured zero in USD. Unlike the patch, these counts are
    worker-attested rather than host-observed; see docs/pier-integration.md.
    """
    if result_bytes is None:
        return None
    try:
        payload = json.loads(result_bytes.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return None
    prompt = _nonnegative_int(usage.get("prompt_tokens"))
    completion = _nonnegative_int(usage.get("completion_tokens"))
    requests = _nonnegative_int(usage.get("requests", 1))
    if prompt is None or completion is None or requests is None:
        return None
    return TrialUsage(
        prompt_tokens=prompt, completion_tokens=completion, cost_usd=None, requests=requests
    )


def seal_artifacts(exchange: PierExchange, artifacts: Mapping[str, bytes]) -> dict[str, bytes]:
    """Return a manifest for the exact evidence captured before teardown.

    The candidate cannot supply or overwrite this binding document. Unknown
    diagnostic files remain retained but are not represented as success kinds.
    """
    if MANIFEST_PATH in artifacts:
        raise ArtifactCollectionRejected(
            "tampering",
            "candidate attempted to supply the artifact manifest",
            artifacts=dict(artifacts),
            rejected_path=MANIFEST_PATH,
        )
    if not artifacts.keys() >= REQUIRED_PATHS:
        raise ValueError("successful trial lacks required evidence")
    retained: dict[str, bytes] = {}
    total = 0
    for path in sorted(artifacts):
        data = artifacts[path]
        if len(data) > MAX_ARTIFACT_BYTES:
            raise ArtifactCollectionRejected(
                "oversized_artifact",
                f"artifact exceeds the byte limit: {path}",
                artifacts=retained,
                rejected_path=path,
            )
        if total + len(data) > MAX_AGGREGATE_ARTIFACT_BYTES:
            raise ArtifactCollectionRejected(
                "aggregate_artifact_limit",
                "artifacts exceed the aggregate byte limit",
                artifacts=retained,
                rejected_path=path,
            )
        retained[path] = data
        total += len(data)
    entries: list[ArtifactEntry] = []
    for path in sorted(KINDS):
        candidate_data = artifacts.get(path)
        if candidate_data is None:
            continue
        try:
            decoded = candidate_data.decode("utf-8")
        except UnicodeDecodeError:
            decoded = None
        if KINDS[path] in {"raw_trajectory", "result", "configuration"}:
            if decoded is None:
                raise ArtifactCollectionRejected(
                    "binary_payload",
                    f"structured artifact is not UTF-8: {path}",
                    artifacts=retained,
                    rejected_path=path,
                )
            try:
                json.loads(decoded)
            except ValueError as error:
                raise ArtifactCollectionRejected(
                    "tampering",
                    f"structured artifact is not JSON: {path}",
                    artifacts=retained,
                    rejected_path=path,
                ) from error
        entries.append(
            ArtifactEntry(
                path=path,
                kind=KINDS[path],
                size_bytes=len(candidate_data),
                checksum=digest_bytes(candidate_data),
                utf8=decoded is not None,
            )
        )
    manifest = ArtifactManifest(
        exchange=exchange,
        entries=tuple(entries),
        aggregate_bytes=sum(entry.size_bytes for entry in entries),
    )
    return {**artifacts, MANIFEST_PATH: canonical_json(manifest.model_dump(mode="json"))}
