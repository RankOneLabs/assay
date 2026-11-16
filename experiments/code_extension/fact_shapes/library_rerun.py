"""Pure qualification rule over reachability.plan_rows output."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from code_extension.reachability import AttemptOutcome


class RerunRow(BaseModel):
    """Read only the fields relevant to the rule from a reachability row."""

    model_config = ConfigDict(extra="ignore", frozen=True)
    outcome: AttemptOutcome
    request_timeout: bool = False


@dataclass(frozen=True)
class RerunVerdict:
    status: Literal["passed", "failed", "incomplete"]
    limit_stop_count: int
    settled_count: int


def verdict(rows: Iterable[RerunRow | Mapping[str, Any]]) -> RerunVerdict:
    """Fail on the second limit stop; pass only after all eleven attempts settle."""
    attempts = tuple(row if isinstance(row, RerunRow) else RerunRow.model_validate(row)
                     for row in rows)
    if len(attempts) > 11:
        raise ValueError("library rerun has exactly eleven attempts")
    settled = tuple(row for row in attempts if row.outcome != "unsettled")
    limits = sum(row.outcome in {"limit_stop", "timeout"} or row.request_timeout
                 for row in settled)
    status: Literal["passed", "failed", "incomplete"] = (
        "failed" if limits >= 2 else "passed" if len(settled) == 11 else "incomplete"
    )
    return RerunVerdict(status, limits, len(settled))
