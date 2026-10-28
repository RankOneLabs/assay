"""Checked wire shapes for code-intelligence artifacts.

The source tree here is the fixture's ``Rung.start_tree`` or ``subject_tree``
mapping, not a Git checkout.  See self_trust/ladder.py:31-37.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from assay.code_metrics.models import (
    CycleReportV4,
    ModuleGraphV2,
    PropagationReportV4,
)
from assay.models import NonEmpty, Sha256Ref, WireModel


class BaselineMode(WireModel):
    kind: Literal["baseline"] = "baseline"


class SymbolsMode(WireModel):
    kind: Literal["symbols"] = "symbols"


class RelationshipsMode(WireModel):
    kind: Literal["relationships"] = "relationships"


CodeIntelMode = Annotated[
    BaselineMode | SymbolsMode | RelationshipsMode, Field(discriminator="kind")
]


class ToolDelivery(WireModel):
    kind: Literal["tool"] = "tool"


class PreloadedDelivery(WireModel):
    kind: Literal["preloaded"] = "preloaded"


CodeIntelDelivery = Annotated[ToolDelivery | PreloadedDelivery, Field(discriminator="kind")]


class ContextItem(WireModel):
    """Source provenance required to audit what a session could retrieve."""

    repo_revision: Sha256Ref
    file_path: NonEmpty
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)
    symbol: str | None = None
    retrieval_method: NonEmpty
    rank: int = Field(ge=0)
    content_hash: Sha256Ref
    approximate_tokens: int = Field(ge=0)
    raw_source_ref: NonEmpty
    content: str | None = None


class SymbolDefinition(WireModel):
    name: NonEmpty
    kind: NonEmpty
    file_path: NonEmpty
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    signature: str | None = None


class SymbolReference(WireModel):
    name: NonEmpty
    file_path: NonEmpty
    line: int = Field(ge=1)
    column: int = Field(ge=1)


class AstStructure(WireModel):
    kind: NonEmpty
    file_path: NonEmpty
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    parent_kind: str | None = None


class IndexManifest(WireModel):
    """One index for one subject tree, including its cache-key inputs.

    ``snapshot_digest`` hashes the ``dict[str, str]`` returned by
    ``Rung.subject_tree`` (ladder.py:32) with ``canonical_json`` and
    ``digest_bytes`` (assay/canonical.py:35-44). ``indexed_paths`` excludes
    ``Rung.hidden_test`` (ladder.py:36); coverage consumes
    ``Rung.omission_paths`` (ladder.py:34).
    """

    schema_version: Literal["assay-codeintel-index-manifest/0.1.0"] = (
        "assay-codeintel-index-manifest/0.1.0"
    )
    repo_revision: Sha256Ref
    snapshot_digest: Sha256Ref
    image_digest: Sha256Ref
    indexer_version: NonEmpty
    cache_key: Sha256Ref
    indexed_paths: tuple[str, ...]
    items: tuple[ContextItem, ...] = ()
    definitions: tuple[SymbolDefinition, ...] = ()
    references: tuple[SymbolReference, ...] = ()
    structures: tuple[AstStructure, ...] = ()
    tool_versions: dict[str, str] = Field(default_factory=dict)
    build_time_ms: float = Field(default=0, ge=0)


class CapabilityManifest(WireModel):
    """Declared mode, delivery, and query support of one code-intelligence implementation."""

    schema_version: Literal["assay-codeintel-capabilities/0.1.0"] = (
        "assay-codeintel-capabilities/0.1.0"
    )
    mode: CodeIntelMode
    delivery: CodeIntelDelivery
    query_kinds: tuple[str, ...]
    supports_summary: bool
    unresolvable_cases: tuple[str, ...] = ()
    graph_edge_caveat: str | None = None


class PreloadedSummary(WireModel):
    repo_revision: Sha256Ref
    text: str
    items: tuple[ContextItem, ...] = ()


class QueryResult(WireModel):
    query_kind: NonEmpty
    items: tuple[ContextItem, ...]
    latency_ms: float = Field(default=0, ge=0)
    supplied_tokens: int = Field(default=0, ge=0)
    snippets: tuple[str, ...] = ()


class ResolvedCall(WireModel):
    kind: Literal["resolved"] = "resolved"


class UnresolvedCall(WireModel):
    kind: Literal["unresolved"] = "unresolved"
    reason: Literal[
        "dynamic import()", "string-keyed dispatch", "any-typed value",
        "unknown target", "ambiguous target",
    ]


CallResolution = Annotated[ResolvedCall | UnresolvedCall, Field(discriminator="kind")]


class CallEdge(WireModel):
    caller: NonEmpty
    callee: NonEmpty
    file_path: NonEmpty
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    target_path: str | None = None
    resolution: CallResolution


class ImportEdgeItem(ContextItem):
    importer: NonEmpty
    imported: NonEmpty


class CallEdgeItem(ContextItem):
    caller: NonEmpty
    callee: NonEmpty
    target_path: str | None = None
    resolution: CallResolution


class AffectedModuleItem(ContextItem):
    module: NonEmpty
    changed_module: NonEmpty


class RelationshipQueryResult(QueryResult):
    items: tuple[ImportEdgeItem | CallEdgeItem | AffectedModuleItem, ...]


class RelationshipIndexManifest(IndexManifest):
    graph: ModuleGraphV2
    cycles: CycleReportV4
    propagation: PropagationReportV4
    call_edges: tuple[CallEdge, ...] = ()
