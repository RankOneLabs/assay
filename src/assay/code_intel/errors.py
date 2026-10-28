"""Code-intelligence failures are returned as local Result values."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class CodeIntelError:
    operation: str
    entity_id: str
    detail: str
    cause: Literal[
        "codeintel_stale_index", "codeintel_omission_uncovered", "codeintel_unsupported_query"
    ]

    def __str__(self) -> str:
        return f"{self.operation} {self.entity_id}: {self.detail}"


@dataclass(frozen=True)
class Ok[T]:
    value: T


@dataclass(frozen=True)
class Err:
    error: CodeIntelError


type Result[T] = Ok[T] | Err
