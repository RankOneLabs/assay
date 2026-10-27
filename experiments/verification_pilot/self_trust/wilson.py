"""95% Wilson score interval used in the independent audit recount."""

from __future__ import annotations

import math


def wilson(k: int, n: int) -> str:
    """Return the two-decimal interval, or an empty string for no trials."""
    if n == 0:
        return ""
    z, p = 1.959964, k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return f"{max(0.0, centre - half):.2f}-{min(1.0, centre + half):.2f}"
