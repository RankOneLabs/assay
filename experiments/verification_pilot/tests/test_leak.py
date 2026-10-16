"""The handoff may name migration inputs, never the hidden answer."""

from __future__ import annotations

import json
from dataclasses import asdict

from verification_pilot.arms import arm
from verification_pilot.fixture import load_fixture
from verification_pilot.ground_truth import build_specimens
from verification_pilot.migrations import MIGRATIONS
from verification_pilot.render import render_prefix
from verification_pilot.session import contributor_blocks, rotated_blocks
from verification_pilot.settings import PILOT_SUBJECT_IDS


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
                    for forbidden in (*PILOT_SUBJECT_IDS, *hidden_kinds, *answer_records):
                        assert forbidden not in rendered
                    assert "ground_truth" not in rendered
                    assert "remnant" not in rendered.lower()
