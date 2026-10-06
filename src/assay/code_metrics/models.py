"""Public metric names and snapshot types."""
from __future__ import annotations

from collections.abc import Mapping
from typing import NamedTuple

DELTAS = (
    "radon.sloc",
    "radon.lloc",
    "radon.cc",
    "radon.halstead_volume",
    "radon.mi",
    "complexipy.cognitive",
    "grimp.imports",
    "ruff.violations",
    "ruff.magic_values",
    "mypy.errors",
    "jscpd.clones",
    "jscpd.duplicated_lines",
)
NEW_CODE = ("new_lines", "new_duplicated_lines", "new_max_nesting_depth")
METRICS = DELTAS + NEW_CODE

Snapshot = Mapping[str, str]


class _Config(NamedTuple):
    clone_min_lines: int
    clone_min_tokens: int
    ruff_ignore: tuple[str, ...]


