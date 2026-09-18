"""Canonical content identities shared by the bridge's trial drivers."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping


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


__all__ = ["canonical_json", "digest_bytes", "package_digest"]
