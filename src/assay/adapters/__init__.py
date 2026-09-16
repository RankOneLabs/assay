"""Lazily loaded adapters; the pinned Jig/OpenRouter stack is optional.

``JigWorker`` (and, transitively, the OpenRouter and consistency adapters it
pulls in) require the ``assay[legacy]`` extra. A clean core install can still
import this package; the Jig import only happens -- and fails actionably --
when a caller actually asks for ``JigWorker``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from assay.adapters.jig import JigWorker as JigWorker

__all__ = ["JigWorker", "missing_legacy_extra"]


def missing_legacy_extra(name: str, error: ModuleNotFoundError) -> ModuleNotFoundError:
    """Convert a raw missing-dependency error into an actionable one."""
    return ModuleNotFoundError(
        f"{name} requires the pinned Jig/OpenRouter stack; install the "
        "'legacy' extra (e.g. `pip install assay[legacy]`) to use it"
    )


def __getattr__(name: str) -> Any:
    if name == "JigWorker":
        try:
            from assay.adapters.jig import JigWorker
        except ModuleNotFoundError as error:
            raise missing_legacy_extra("assay.adapters.JigWorker", error) from error
        return JigWorker
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
