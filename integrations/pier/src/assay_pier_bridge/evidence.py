"""Read worker-attested usage from bridge result evidence."""

from __future__ import annotations

import json

from assay_pier_bridge.protocol import TrialUsage


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
    requests = _nonnegative_int(usage.get("requests"))
    if prompt is None or completion is None or requests is None:
        return None
    return TrialUsage(
        prompt_tokens=prompt, completion_tokens=completion, cost_usd=None, requests=requests
    )
