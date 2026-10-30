"""Literal ce-v1 pins against the actual bridge and renderer."""

from code_extension.bridge import EXTENSION_TOOLS
from code_extension.protocol import (
    ORDERED_TOOL_SCHEMAS_SHA256,
    PROTOCOL_ID,
    PROTOCOL_VERSION,
    RENDERED_TASK_SHA256,
    SUBMISSION_SCHEMA_SHA256,
    SYSTEM_PROMPT_SHA256,
    submission_schema,
    surface_digests,
)


def test_ce_v1_rendering_pins() -> None:
    assert (PROTOCOL_ID, PROTOCOL_VERSION) == ("ce-v1", "1.0.0")
    assert [tool["function"]["name"] for tool in EXTENSION_TOOLS] == [
        "read_file", "write_file", "replace_in_file", "run_command", "submit_output",
    ]
    assert set(submission_schema()["properties"]) == {
        "summary", "self_assessed_verdict", "checks_performed", "remaining_work",
    }
    assert submission_schema()["properties"]["self_assessed_verdict"]["enum"] == [
        "complete", "incomplete", "unsure", None,
    ]
    assert surface_digests() == {
        "system_prompt": SYSTEM_PROMPT_SHA256,
        "rendered_task": RENDERED_TASK_SHA256,
        "ordered_tool_schemas": ORDERED_TOOL_SCHEMAS_SHA256,
        "submission_schema": SUBMISSION_SCHEMA_SHA256,
    }
