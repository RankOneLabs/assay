"""Render one configured code-intelligence delivery for a self-trust cell."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from assay.code_intel.contract import CodeIntelSettings
from assay.code_intel.delivery import CodeIntelDeliveryConfig
from assay.code_intel.errors import Err, Ok
from assay.code_intel.models import BaselineMode, PreloadedDelivery, SymbolsMode
from assay.code_intel.snapshot import repo_revision
from assay.code_intel.symbols import SymbolsCodeIntel
from verification_pilot.self_trust.ladder import RUNGS
from verification_pilot.self_trust.study import SelfTrustSubject


@dataclass(frozen=True)
class PreparedDelivery:
    block: str | None = None
    tool: dict[str, Any] | None = None
    index_files: dict[str, bytes] | None = None


def prepare_delivery(
    subject: SelfTrustSubject, config: CodeIntelDeliveryConfig | None,
    *, image_digest: str, index_root: Path,
) -> PreparedDelivery:
    if config is None or isinstance(config.mode, BaselineMode):
        return PreparedDelivery()
    if repo_revision(subject.repository) != config.repository_revision:
        raise ValueError("codeintel_stale_index")
    root = Path(str(config.provider_options.get("index_root", index_root)))
    provider = SymbolsCodeIntel(
        CodeIntelSettings(mode=SymbolsMode(), delivery=config.delivery), index_root=root,
    )
    excluded = (frozenset({RUNGS[subject.fixture].hidden_test})
                if subject.fixture in RUNGS else frozenset())
    prepared = provider.prepare(subject.repository, image_digest=image_digest,
                                excluded_paths=excluded)
    if isinstance(prepared, Err):
        raise ValueError(f"{prepared.error.cause}: {prepared.error.detail}")
    manifest = prepared.value
    files = {"index.json": manifest.model_dump_json().encode("utf-8")}
    if isinstance(config.delivery, PreloadedDelivery):
        summarized = provider.summarize(manifest, token_budget=config.max_context_tokens)
        if (isinstance(summarized, Err) or not isinstance(summarized, Ok)
                or summarized.value is None):
            raise ValueError("codeintel_index_failure")
        if config.mode.kind == "relationships":
            text = "\n".join(
                f"{reference.file_path}:{reference.line} {reference.name}"
                for reference in sorted(manifest.references, key=lambda item: (
                    item.file_path, item.line, item.column, item.name))
            )
        else:
            text = summarized.value.text.rstrip("\n")
        block = f"Code intelligence for {manifest.repo_revision}:\n{text}"
        block = block.encode("utf-8")[:config.max_context_tokens * 4].decode(
            "utf-8", "ignore").rstrip("\n")
        return PreparedDelivery(block=block, index_files=files)
    kind = "references" if config.mode.kind == "relationships" else "symbol"
    tool = {
        "type": "function",
        "function": {
            "name": "codeintel_query",
            "description": "Query the mounted code-intelligence index for repository context.",
            "parameters": {
                "type": "object", "additionalProperties": False,
                "required": ["kind", "text"],
                "properties": {
                    "kind": {"type": "string", "enum": [kind]},
                    "text": {"type": "string"},
                },
            },
            "strict": True,
        },
    }
    return PreparedDelivery(tool=tool, index_files=files)
