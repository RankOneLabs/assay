"""Operator configuration for delivering one code-intelligence index to a cell."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any

from pydantic import Field, field_validator

from assay.code_intel.models import CodeIntelDelivery, CodeIntelMode
from assay.models import Sha256Ref, WireModel


class CodeIntelDeliveryConfig(WireModel):
    """A fully specified provider arm; the index mount has no implicit location."""

    mode: CodeIntelMode
    delivery: CodeIntelDelivery
    repository_revision: Sha256Ref
    max_context_tokens: int = Field(gt=0)
    query_limit: int = Field(gt=0)
    provider_options: dict[str, Any] = Field(default_factory=dict)
    index_mount: str
    index_agent_readable: bool

    @field_validator("index_mount")
    @classmethod
    def validate_index_mount(cls, value: str) -> str:
        path = PurePosixPath(value)
        if not path.is_absolute():
            raise ValueError("index_mount must be an absolute path")
        if value != str(path) or ".." in path.parts:
            raise ValueError("index_mount must be a canonical absolute path")
        if path == PurePosixPath("/workspace") or PurePosixPath("/workspace") in path.parents:
            raise ValueError("index_mount must be outside /workspace")
        if path == PurePosixPath("/"):
            raise ValueError("index_mount must name a directory")
        return value
