"""Checked wire shapes for code-intelligence artifacts.

The source tree here is the fixture's ``Rung.start_tree`` or ``subject_tree``
mapping, not a Git checkout.  See self_trust/ladder.py:31-37.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

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


class CapabilityManifest(WireModel):
    """Declared mode, delivery, and query support of one code-intelligence implementation."""

    schema_version: Literal["assay-codeintel-capabilities/0.1.0"] = (
        "assay-codeintel-capabilities/0.1.0"
    )
    mode: CodeIntelMode
    delivery: CodeIntelDelivery
    query_kinds: tuple[str, ...]
    supports_summary: bool


class PreloadedSummary(WireModel):
    repo_revision: Sha256Ref
    text: str
    items: tuple[ContextItem, ...] = ()


class QueryResult(WireModel):
    query_kind: NonEmpty
    items: tuple[ContextItem, ...]

