"""Baseline is an identity transform over the authorized study surface."""

from assay.canonical import canonical_json, digest_bytes
from assay.code_intel.baseline import select_code_intel
from assay.code_intel.contract import (
    CodeIntelSettings,
    append_code_intel_tools,
    render_code_intel_prompt,
)
from assay.code_intel.errors import Ok
from assay.code_intel.models import BaselineMode


def test_baseline_has_no_prompt_tool_or_query_surface() -> None:
    selected = select_code_intel(CodeIntelSettings(mode=BaselineMode()))
    assert isinstance(selected, Ok)
    code_intel = selected.value
    assert code_intel.capabilities().query_kinds == ()
    assert code_intel.capabilities().supports_summary is False
    assert code_intel.tools() == ()
    assert code_intel.prompt_block() is None
    prompt = "pinned system prompt\n"
    tools = [{"type": "function", "name": "read_file"}]
    assert render_code_intel_prompt(prompt, code_intel.prompt_block()) == prompt
    assert digest_bytes(canonical_json(append_code_intel_tools(tools, code_intel.tools()))) == (
        digest_bytes(canonical_json(tools))
    )
    assert append_code_intel_tools(tools, code_intel.tools())[0] is tools[0]
    prepared = code_intel.prepare(
        {"src/main.ts": "ok", "tests/hidden/omissions.test.ts": "secret"},
        image_digest="sha256:" + "1" * 64,
        excluded_paths=frozenset({"tests/hidden/omissions.test.ts"}),
    )
    assert isinstance(prepared, Ok)
    summary = code_intel.summarize(prepared.value)
    assert isinstance(summary, Ok)
    assert summary.value.text == ""
    assert "omissions.test.ts" not in prepared.value.model_dump_json()
    assert "omissions.test.ts" not in summary.value.model_dump_json()
    assert not isinstance(code_intel.query(prepared.value, "symbol", "x"), Ok)
    code_intel.close()
