from __future__ import annotations

import ast
import hashlib
from pathlib import Path

import yaml

from workflow_edit.settings import PROVISIONAL_SOURCE, Part1AgentSettings


def test_part1_settings_match_bridge_configuration() -> None:
    root = Path(__file__).resolve().parents[3]
    configuration = yaml.safe_load(
        (root / "integrations/pier/config/workflow_edit.yaml").read_text()
    )
    assert configuration == Part1AgentSettings().model_dump()
    assert all(
        PROVISIONAL_SOURCE in (Part1AgentSettings.model_fields[name].description or "")
        for name in (
            "max_tool_schema_bytes",
            "max_tool_output_bytes",
            "max_conversation_bytes",
            "max_request_bytes",
            "max_response_bytes",
            "max_output_tokens",
        )
    )


def test_pilot_settings_field_definition_bytes_are_unchanged() -> None:
    root = Path(__file__).resolve().parents[3]
    source = (root / "src/assay/adapters/consistency.py").read_text()
    node = next(
        item
        for item in ast.parse(source).body
        if isinstance(item, ast.ClassDef) and item.name == "PilotSettings"
    )
    exact_bytes = "".join(
        source.splitlines(keepends=True)[node.lineno - 1 : node.end_lineno]
    ).encode()
    assert hashlib.sha256(exact_bytes).hexdigest() == (
        "bc839b5718b1dccb5a7ad70cffe90adcaab6ee73a7eeeb66a2be0d1e6d8827b4"
    )
