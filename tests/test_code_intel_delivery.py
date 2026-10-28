"""The index mount is an explicit operator decision."""

import pytest
from pydantic import ValidationError

from assay.code_intel.delivery import CodeIntelDeliveryConfig


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
