"""ce-v1 model-visible protocol identity and literal surface pins."""

from __future__ import annotations

from typing import Any, cast

from assay.canonical import canonical_json, digest_bytes
from code_extension.bridge import (  # type: ignore[attr-defined]
    EXTENSION_SYSTEM_PROMPT,
    EXTENSION_TOOLS,
)
from code_extension.prompts import render_initial_task

PROTOCOL_ID = "ce-v1"
PROTOCOL_VERSION = "1.0.0"

# Fixed rendering witness. Each trial also records the digest of its own rendered
# instruction.md, since feature requests and scopes vary by scenario.
PINNED_TASK = render_initial_task(
    feature_request="Implement the declared feature.",
    workspace_and_test_instructions="Work in /workspace and run the visible tests.",
    writable_scope=("src/", "tests/visible/"),
    budget="900 seconds; at most 60 model requests.",
)

SYSTEM_PROMPT_SHA256 = "sha256:d6f2f100a9a362ddae1d201fd96de86b24ad47b7449ff863d42c64ed71607cfb"
RENDERED_TASK_SHA256 = "sha256:7dabab300210e9e4c6bff5b979b79d77e77b1d17c95140291dfbfc91fd0073b3"
ORDERED_TOOL_SCHEMAS_SHA256 = (
    "sha256:698286ad88a625d2ebdccb8c5f1fffc7d7831692f09eac7b146123fd2f8c8c9c"
)
SUBMISSION_SCHEMA_SHA256 = "sha256:a73898a4628eecc8e286951d54545dcacabc8d58c1f50f3ab80e281e7cafdd51"


def submission_schema() -> dict[str, Any]:
    """Read the actual extension submit_output parameters, without copying them."""
    return cast(dict[str, Any], EXTENSION_TOOLS[-1]["function"]["parameters"])


def surface_digests() -> dict[str, str]:
    return {
        "system_prompt": digest_bytes(EXTENSION_SYSTEM_PROMPT.encode("utf-8")),
        "rendered_task": digest_bytes(PINNED_TASK.encode("utf-8")),
        "ordered_tool_schemas": digest_bytes(canonical_json(EXTENSION_TOOLS)),
        "submission_schema": digest_bytes(canonical_json(submission_schema())),
    }
