"""Retained production sandbox attempts cover the declared tool surface."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from code_extension.bridge import EXTENSION_SYSTEM_PROMPT, EXTENSION_TOOLS
from code_extension.fixture import PILOT
from code_extension.fixtures import load_scenario
from code_extension.probe import _scripted_client

from assay.canonical import digest_bytes
from assay.fixture_manifest import FixtureManifestV3

GATES = PILOT.parent / "dispatch-handler" / "qualification" / "gates"


def test_live_bridge_resolves_sidecar_scope_and_production_prompt_bounds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "code_extension.bridge.observed_image_digest", lambda _image: "sha256:" + "a" * 64
    )
    fixture = load_scenario("dispatch-handler")
    manifest = FixtureManifestV3.model_validate_json(
        (GATES.parent / "manifest.json").read_bytes()
    )
    bridge = _scripted_client(fixture, manifest, "image", tmp_path, [])
    configuration = bridge.configuration()
    assert configuration["writable_prefixes"] == ["src/domain/"]
    assert "tests/visible/" not in configuration["writable_prefixes"]
    assert configuration["system_prompt_sha256"] == digest_bytes(
        EXTENSION_SYSTEM_PROMPT.encode()
    )
    assert configuration["bounds"]["max_turns"] == bridge._bounds().max_turns


def test_access_attempts_cover_every_tool_and_forbidden_class() -> None:
    evidence = json.loads((GATES / "access-probe.json").read_bytes())
    declared = {tool["function"]["name"] for tool in EXTENSION_TOOLS}
    assert set(evidence["tools_exercised"]) == declared
    assert evidence["submitted"] and evidence["candidate_unchanged"]
    assert evidence["writable_prefixes"] == ["src/domain/"]
    assert evidence["system_prompt_sha256"] == digest_bytes(
        EXTENSION_SYSTEM_PROMPT.encode()
    )
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
    assert scripted["writable_prefixes"] == ["src/domain/"]
    assert set(scripted["groups"].values()) == {"passed"}
    scan = json.loads((GATES / "leak-scan.json").read_bytes())
    assert scan["hits"] == [] and scan["sources_scanned"] >= 64
