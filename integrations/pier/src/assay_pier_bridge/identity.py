"""Canonical content identities shared by the bridge's trial drivers."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from collections.abc import Mapping

from assay_pier_bridge.protocol import BridgeIdentity

_IMAGE_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")


class ImageInspectionError(ValueError):
    """The built image's digest could not be observed through Docker."""


class ImageDigestMismatchError(ValueError):
    """A manifest declares a digest other than the built image's digest."""


def observed_image_digest(image_ref: str) -> str:
    """Read the built image ID, not a digest supplied by a manifest or caller."""
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", "--format", "{{.Id}}", image_ref],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ImageInspectionError(f"cannot inspect bridge image {image_ref!r}") from exc
    digest = result.stdout.strip()
    if result.returncode != 0 or _IMAGE_DIGEST.fullmatch(digest) is None:
        raise ImageInspectionError(
            f"cannot read a sha256 image digest for {image_ref!r}: {result.stderr.strip()}"
        )
    return digest


def bind_bridge_identity(manifest: Mapping[str, object], image_ref: str) -> BridgeIdentity:
    """Bind a fixture identity to the observed image and reject stale declarations."""
    observed = observed_image_digest(image_ref)
    declared = manifest.get("bridge_image_digest")
    if declared is not None and declared != observed:
        raise ImageDigestMismatchError(
            f"bridge_image_digest {declared!r} differs from inspected image digest {observed!r}"
        )
    return BridgeIdentity.model_validate({**manifest, "bridge_image_digest": observed})


def digest_bytes(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def canonical_json(value: object) -> bytes:
    """Mirror ``assay.canonical.canonical_json`` without importing Assay."""
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def package_digest(package: Mapping[str, str]) -> str:
    """Return the canonical identity of a sealed package mapping."""
    entries = [
        [path, digest_bytes(content.encode("utf-8"))] for path, content in sorted(package.items())
    ]
    return digest_bytes(canonical_json(entries))


__all__ = [
    "ImageDigestMismatchError",
    "ImageInspectionError",
    "bind_bridge_identity",
    "canonical_json",
    "digest_bytes",
    "observed_image_digest",
    "package_digest",
]
