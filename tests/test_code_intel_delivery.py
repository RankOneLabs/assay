"""The index mount is an explicit operator decision."""

import json
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from assay.code_intel.delivery import CodeIntelDeliveryConfig
from assay.code_intel.models import QueryResult
from assay.code_intel.query_script import QUERY_SCRIPT


def _configuration() -> dict[str, object]:
    return {
        "mode": {"kind": "symbols"},
        "delivery": {"kind": "tool"},
        "repository_revision": "sha256:" + "1" * 64,
        "max_context_tokens": 512,
        "query_limit": 20,
        "provider_options": {},
        "index_mount": "/codeintel-index",
        "index_agent_readable": True,
    }


@pytest.mark.parametrize("mount", [None, "codeintel-index", "/workspace/index"])
def test_index_mount_must_be_explicit_absolute_and_outside_workspace(
    mount: str | None,
) -> None:
    values = _configuration()
    if mount is None:
        del values["index_mount"]
    else:
        values["index_mount"] = mount
    with pytest.raises(ValidationError, match="index_mount"):
        CodeIntelDeliveryConfig.model_validate(values)


def test_index_readability_is_explicit() -> None:
    values = _configuration()
    del values["index_agent_readable"]
    with pytest.raises(ValidationError, match="index_agent_readable"):
        CodeIntelDeliveryConfig.model_validate(values)
    assert CodeIntelDeliveryConfig.model_validate(_configuration()).index_mount == (
        "/codeintel-index"
    )


def test_tool_delivery_requires_readable_index() -> None:
    values = _configuration()
    values["index_agent_readable"] = False
    with pytest.raises(ValidationError, match="agent-readable"):
        CodeIntelDeliveryConfig.model_validate(values)


def test_query_script_returns_bounded_symbol_context(tmp_path: Path) -> None:
    manifest = {
        "repo_revision": "sha256:" + "1" * 64,
        "items": [{
            "repo_revision": "sha256:" + "1" * 64,
            "symbol": "createThing", "file_path": "src/thing.ts", "start_line": 3,
            "end_line": 3, "content": "export function createThing() {}",
            "retrieval_method": "typescript_symbol_definition", "rank": 0,
            "content_hash": "sha256:" + "2" * 64, "approximate_tokens": 9,
            "raw_source_ref": "src/thing.ts:3:3",
        }],
        "references": [{"name": "createThing", "file_path": "src/use.ts",
                        "line": 7, "column": 5}],
    }
    (tmp_path / "index.json").write_text(json.dumps(manifest), encoding="utf-8")
    queried = subprocess.run(
        ["python", "-c", QUERY_SCRIPT, str(tmp_path / "index.json"), "symbol", "createThing",
         "512"], capture_output=True, text=True, check=True,
    )
    result = QueryResult.model_validate(json.loads(queried.stdout))
    assert result.items[0].file_path == "src/thing.ts"
    references = subprocess.run(
        ["python", "-c", QUERY_SCRIPT, str(tmp_path / "index.json"), "references",
         "createThing", "512"], capture_output=True, text=True, check=True,
    )
    related = QueryResult.model_validate(json.loads(references.stdout))
    assert related.items[0].file_path == "src/use.ts"
