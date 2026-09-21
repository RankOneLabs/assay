from __future__ import annotations

import json
from pathlib import Path

import pytest

from assay.investigations.relevance.catalogue import load_catalogue
from assay.investigations.relevance.mappings import DECIDE_REGISTRY, derive_band
from assay.investigations.relevance.state import build_state

ROOT = Path(__file__).parents[1]
CATALOGUE = ROOT / "src/assay/investigations/relevance/catalogues/agent-ops-relevance.v1.yaml"


@pytest.fixture(autouse=True)
def _require_run_receipts(run_receipts_checkout: Path) -> None:
    pass


@pytest.fixture
def answers_path(run_receipts_checkout: Path) -> Path:
    return run_receipts_checkout / "typesafe-relevance-primary-2026-09/exported-answers.json"


def test_catalogue_version_matches_primary_report(answers_path: Path) -> None:
    catalogue = load_catalogue(CATALOGUE)
    report = json.loads(answers_path.read_text(encoding="utf-8"))
    assert catalogue.version == report["catalogue_version"]
    assert len(catalogue.questions) == 17


def test_exported_answers_reproduce_every_recorded_decision(answers_path: Path) -> None:
    catalogue = load_catalogue(CATALOGUE)
    decide = DECIDE_REGISTRY[catalogue.decide]
    report = json.loads(answers_path.read_text(encoding="utf-8"))
    assert len(report["cases"]) == 79
    assert sum(len(case["repeats"]) for case in report["cases"]) == 237
    for case in report["cases"]:
        votes = []
        for repeat in case["repeats"]:
            reproduced = decide(repeat["answers"])
            assert reproduced == repeat["decision"]
            votes.append(reproduced["eligible"])
        assert (sum(votes) >= 2) == case["typesafe_decision"]


def test_reference_state_builder_projects_only_declared_fields() -> None:
    state = build_state(
        {
            "platform": "bluesky",
            "channel": "bluesky",
            "url": "https://example.test/post",
            "text": "A concrete agent incident.",
            "parent_author_name": None,
            "parent_text": None,
            "author_name": "Ada",
            "author_handle": "ada.test",
            "ignored": "must not leak",
        },
        {"key": "agent-ops", "name": "AgentOperations", "description": "ops"},
    )
    assert state == {
        "post": {
            "platform": "bluesky",
            "channel": "bluesky",
            "url": "https://example.test/post",
            "text": "A concrete agent incident.",
        },
        "parent_context_only": None,
        "author": {"name": "Ada", "handle": "ada.test"},
        "project": {"key": "agent-ops", "name": "AgentOperations", "description": "ops"},
    }


def test_precedence_mapping_hard_exclusion_wins() -> None:
    answers = {
        "exclusion": {"probabilities": {"none": 0.1, "hype": 0.9}},
        "operational_claim": {"noul": 0.99},
        "reasoned_practice": {"noul": 0.1},
        "operational_question": {"noul": 0.1},
        "point_in_own_text": {"noul": 0.99},
        "on_topic_pointer": {"noul": 0.1},
        "general_building": {"noul": 0.1},
    }
    assert derive_band(answers) == "out_of_scope"
