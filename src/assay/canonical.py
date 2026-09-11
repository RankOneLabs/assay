"""The single canonical JSON and hashing implementation used by Assay."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any


class CanonicalizationError(ValueError):
    """A value cannot be represented by Assay's canonical JSON profile."""


def _validate(value: Any, path: str = "$") -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CanonicalizationError(f"non-finite number at {path}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate(item, f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise CanonicalizationError(f"non-string object key at {path}")
            _validate(item, f"{path}.{key}")
        return
    raise CanonicalizationError(f"unsupported {type(value).__name__} at {path}")


def canonical_json(value: Any) -> bytes:
    """Encode JSON deterministically, preserving Unicode and array order."""
    _validate(value)
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def digest_bytes(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"
