"""The handoff may name migration inputs, never the hidden answer."""

from __future__ import annotations

import json
import re
from dataclasses import asdict

from assay.code_intel.leak_scan import scan_text
from verification_pilot.arms import arm
from verification_pilot.fixture import load_fixture
from verification_pilot.ground_truth import build_specimens
from verification_pilot.migrations import MIGRATIONS
from verification_pilot.render import render_prefix
from verification_pilot.self_trust import leaks
from verification_pilot.session import contributor_blocks, rotated_blocks

ARM_IDS = ("native-template", "quoted-template", "smithers-local", "openrouter")


def test_no_hidden_identity_or_answer_in_any_rendered_block() -> None:
    _, truth = build_specimens(load_fixture())
    hidden_kinds = {record.kind for record in (*truth.remnants, *truth.decoys)}
    answer_records = [json.dumps(asdict(record), sort_keys=True) for record in truth.remnants]
    for migration in MIGRATIONS:
        blocks = contributor_blocks(migration)
        for rotation in range(3):
            ordered = rotated_blocks(blocks, rotation)
            for placement in ("native-template", "quoted-template"):
                for route in ("smithers-local", "openrouter"):
                    rendered = json.dumps(render_prefix(ordered, arm(placement, route)))
                    for forbidden in (*ARM_IDS, *hidden_kinds, *answer_records):
                        assert forbidden not in rendered
                    assert "ground_truth" not in rendered
                    assert "remnant" not in rendered.lower()


def test_reusable_scan_matches_existing_archive_rows() -> None:
    archive = next(iter(sorted(leaks.RUNS.glob("*/index.json"))))
    run = archive.parent
    index = json.loads(archive.read_text(encoding="utf-8"))
    expected = []
    actual = []
    patterns = [re.compile(term, re.I) for term in leaks.TERMS]
    patterns.extend(re.compile(re.escape(path)) for path in sorted(leaks.hidden_paths()))
    for cell_id, entry in sorted(index.items()):
        trajectory = json.loads((run / "traces" / entry["trajectory"]).read_text(
            encoding="utf-8"))
        for position, message in enumerate(trajectory["messages"]):
            if message["role"] == "assistant":
                continue
            content = message.get("content") or ""
            if not isinstance(content, str):
                content = json.dumps(content)
            for pattern in patterns:
                for match in pattern.finditer(content):
                    expected.append((run.name, cell_id, position, message["role"],
                                     pattern.pattern,
                                     content[max(0, match.start() - 80):match.end() + 80]
                                     .replace("\n", " ")))
            for hit in scan_text(content, leaks.TERMS, leaks.hidden_paths(),
                                 source=message["role"]):
                actual.append((run.name, cell_id, position, message["role"],
                               hit.term, hit.context))
    assert actual == expected
    assert len(leaks.TERMS) == 16
    assert leaks.RAW.parts[-2:] == ("raw", "self_trust")
