"""Retained production sandbox attempts cover the declared tool surface."""

from __future__ import annotations

import json

from code_extension.bridge import EXTENSION_TOOLS
from code_extension.fixture import PILOT

GATES = PILOT.parent / "dispatch-handler" / "qualification" / "gates"


def test_access_attempts_cover_every_tool_and_forbidden_class() -> None:
    evidence = json.loads((GATES / "access-probe.json").read_bytes())
    declared = {tool["function"]["name"] for tool in EXTENSION_TOOLS}
    assert set(evidence["tools_exercised"]) == declared
    assert evidence["submitted"] and evidence["candidate_unchanged"]
    attempts = evidence["attempts"]
    assert len(attempts) == 17
    targets = "\n".join(item["target"] for item in attempts)
    for marker in (
        "tests/hidden/",
        "patches/reference.patch",
        "patches/missing-registration.patch",
        "patches/missing-validation.patch",
        "/cache/operator/",
        "/home/steve/",
        "ln -s",
    ):
        assert marker in targets
    for index, attempt in enumerate(attempts):
        expected = "exit=0\nREFUSED" if 8 <= index <= 13 else (
            "exit=0" if index in {14, 16} else "error:"
        )
        assert attempt["response"].startswith(expected)


def test_scripted_worker_and_leak_scan_records() -> None:
    scripted = json.loads((GATES / "scripted-submission.json").read_bytes())
    assert scripted["tool_path"] == ["write_file", "submit_output"]
    assert scripted["reference_tree_matches"]
    assert scripted["independent_evaluator_verdict"] == "correct"
    assert set(scripted["groups"].values()) == {"passed"}
    scan = json.loads((GATES / "leak-scan.json").read_bytes())
    assert scan["hits"] == [] and scan["sources_scanned"] >= 64
