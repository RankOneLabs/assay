"""Typed lifecycle and surface rules for code intelligence."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol

from pydantic import Field

from assay.code_intel.errors import Result
from assay.code_intel.models import (
    BaselineMode,
    CapabilityManifest,
    CodeIntelDelivery,
    CodeIntelMode,
    IndexManifest,
    PreloadedSummary,
    QueryResult,
    ToolDelivery,
)
from assay.models import WireModel

type ToolDefinition = dict[str, object]


class CodeIntelSettings(WireModel):
    mode: CodeIntelMode = Field(default_factory=BaselineMode)
    delivery: CodeIntelDelivery = Field(default_factory=ToolDelivery)


class CodeIntelContract(Protocol):
    def prepare(
        self, snapshot_mapping: Mapping[str, str], *, image_digest: str,
        excluded_paths: frozenset[str],
    ) -> Result[IndexManifest]: ...

    def capabilities(self) -> CapabilityManifest: ...

    def query(self, manifest: IndexManifest, query_kind: str, text: str) -> Result[QueryResult]: ...

    def summarize(self, manifest: IndexManifest) -> Result[PreloadedSummary]: ...

    def tools(self) -> tuple[ToolDefinition, ...]: ...

    def prompt_block(self) -> str | None: ...

    def prefix_block(self) -> tuple[dict[str, object], ...]: ...

    def close(self) -> None: ...


def append_code_intel_tools(
    baseline_tools: Sequence[ToolDefinition], extra_tools: Sequence[ToolDefinition],
) -> list[ToolDefinition]:
    """Keep baseline definitions and order byte-for-byte; append only."""
    return [*baseline_tools, *extra_tools]


def render_code_intel_prompt(system_prompt: str, block: str | None) -> str:
    return system_prompt if block is None else system_prompt + block


def append_code_intel_prefix(
    message_prefix: Sequence[dict[str, object]], block: Sequence[dict[str, object]],
) -> list[dict[str, object]]:
    return [*message_prefix, *block]
