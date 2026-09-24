"""Tests for the multi-arm relevance grid: catalogue parity, rendering, scoring."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typesafe_relevance.catalogue import load_catalogue
from typesafe_relevance.mappings import decide_argmax
from typesafe_relevance.render import (
    RenderError,
    answer_schema,
    normalize_answers,
    render_prompt,
)
from typesafe_relevance.run_arms import build_arms, load_prior_cells, score_arm


@pytest.fixture
def v1(relevance_catalogues: Path) -> Path:
    return relevance_catalogues / "agent-ops-relevance.v1.yaml"


@pytest.fixture
def v2(relevance_catalogues: Path) -> Path:
    return relevance_catalogues / "agent-ops-relevance.v2.yaml"


@pytest.fixture
def v1_questions(v1: Path) -> dict:
    return load_catalogue(v1).questions


@pytest.fixture
def v2_questions(v2: Path) -> dict:
    return load_catalogue(v2).questions


def test_v2_keeps_v1_question_ids_in_order(v1_questions: dict, v2_questions: dict) -> None:
    assert list(v2_questions) == list(v1_questions)


def test_v2_keeps_v1_answer_types(v1_questions: dict, v2_questions: dict) -> None:
    assert [q["type"] for q in v2_questions.values()] == [
        q["type"] for q in v1_questions.values()
    ]


def test_v2_keeps_v1_answer_domains(v1_questions: dict, v2_questions: dict) -> None:
    def domain(question: dict) -> object:
        if question["type"] == "score":
            return len(question["criteria"])
        return sorted(question["criteria"])

    assert {key: domain(q) for key, q in v2_questions.items()} == {
        key: domain(q) for key, q in v1_questions.items()
    }


def test_v2_has_a_different_version_than_v1(v1: Path, v2: Path) -> None:
    assert load_catalogue(v2).version != load_catalogue(v1).version


def test_v2_gives_every_criterion_examples(v2_questions: dict) -> None:
    missing = [
        f"{question_id}.{name}"
        for question_id, question in v2_questions.items()
        if question["type"] != "score"
        for name, item in question["criteria"].items()
        if not item.get("examples")
    ]
    assert missing == []


def test_rendered_prompt_names_every_question(v2_questions: dict) -> None:
    prompt = render_prompt(v2_questions)
    assert all(question_id in prompt for question_id in v2_questions)


def test_rendered_prompt_carries_criteria_examples(v2_questions: dict) -> None:
    prompt = render_prompt(v2_questions)
    assert "always add retries" in prompt


def test_answer_schema_mirrors_each_answer_domain(v2_questions: dict) -> None:
    schema = answer_schema(v2_questions)
    assert schema["properties"]["operational_claim"] == {"type": "number"}
    assert sorted(schema["properties"]["exclusion"]["properties"]) == sorted(
        v2_questions["exclusion"]["criteria"]
    )
    assert sorted(schema["properties"]["band"]["properties"]) == ["0", "1", "2", "3"]


def test_answer_schema_is_strict(v2_questions: dict) -> None:
    schema = answer_schema(v2_questions)
    assert schema["additionalProperties"] is False


def _full_reply(questions: dict) -> dict:
    reply: dict[str, object] = {}
    for question_id, question in questions.items():
        if question["type"] == "noul":
            reply[question_id] = 0.5
        elif question["type"] == "choice":
            names = list(question["criteria"])
            reply[question_id] = {name: 1.0 / len(names) for name in names}
        else:
            reply[question_id] = {str(i): 0.25 for i in range(len(question["criteria"]))}
    return reply


def test_normalize_produces_jev_shaped_noul(v2_questions: dict) -> None:
    answers = normalize_answers(_full_reply(v2_questions), v2_questions)
    assert answers["operational_claim"] == {"type": "noul", "noul": 0.5}


def test_normalize_renormalizes_choice_probabilities(v2_questions: dict) -> None:
    reply = _full_reply(v2_questions)
    reply["exclusion"] = {"non_english": 2.0, "coding_assistant": 0.0, "hardware": 0.0,
                          "funding_or_market": 0.0, "event_promo": 0.0, "hype": 0.0, "none": 2.0}
    answers = normalize_answers(reply, v2_questions)
    assert answers["exclusion"]["probabilities"]["none"] == pytest.approx(0.5)


def test_normalize_derives_score_as_weighted_position(v2_questions: dict) -> None:
    reply = _full_reply(v2_questions)
    reply["band"] = {"0": 0.0, "1": 0.0, "2": 0.0, "3": 1.0}
    answers = normalize_answers(reply, v2_questions)
    assert answers["band"]["score"] == pytest.approx(3.0)


def test_normalize_rejects_a_missing_question(v2_questions: dict) -> None:
    reply = _full_reply(v2_questions)
    del reply["band"]
    with pytest.raises(RenderError, match="missing question: band"):
        normalize_answers(reply, v2_questions)


def test_normalize_rejects_all_zero_probabilities(v2_questions: dict) -> None:
    reply = _full_reply(v2_questions)
    reply["band"] = {"0": 0.0, "1": 0.0, "2": 0.0, "3": 0.0}
    with pytest.raises(RenderError, match="sum to zero"):
        normalize_answers(reply, v2_questions)


def test_normalized_answers_drive_the_existing_decision_mapping(v2_questions: dict) -> None:
    reply = _full_reply(v2_questions)
    reply["band"] = {"0": 0.0, "1": 0.0, "2": 0.0, "3": 1.0}
    reply["exclusion"] = {name: (1.0 if name == "none" else 0.0)
                          for name in v2_questions["exclusion"]["criteria"]}
    decision = decide_argmax(normalize_answers(reply, v2_questions))
    assert decision["eligible"] is True


def test_build_arms_rejects_an_unknown_arm() -> None:
    with pytest.raises(ValueError, match="unknown arms"):
        build_arms(["jev:v3"])


def test_jev_v1_arm_never_dispatches() -> None:
    assert build_arms(["jev:v1"])[0].backend is None


def test_score_arm_reports_accuracy_precision_and_recall() -> None:
    scored = score_arm([True, True, False], [True, False, False], [True, True, True])
    assert scored["accuracy"] == pytest.approx(2 / 3)
    assert scored["precision"] == pytest.approx(0.5)
    assert scored["recall"] == pytest.approx(1.0)


def test_prior_cells_index_the_primary_report_shape(tmp_path: Path) -> None:
    path = tmp_path / "prior.json"
    path.write_text(
        json.dumps(
            {"cases": [{"evaluation_id": 7, "repeats": [{"repeat_index": 1, "answers": {}}]}]}
        ),
        encoding="utf-8",
    )
    assert "jev:v1:7:1" in load_prior_cells([path])


def test_prior_cells_index_the_multi_arm_shape(tmp_path: Path) -> None:
    path = tmp_path / "prior.json"
    path.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "evaluation_id": 7,
                        "arms": {"gemini:v2": {"repeats": [{"repeat_index": 2, "answers": {}}]}},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    assert "gemini:v2:7:2" in load_prior_cells([path])


def _arms_document() -> dict:
    def case(evaluation_id: int, label: bool, production: bool, band: str, decision: bool) -> dict:
        answers = {
            "band": {"type": "score", "probabilities": {k: (1.0 if k == band else 0.0)
                                                        for k in ("0", "1", "2", "3")}},
            "operational_claim": {"type": "noul", "noul": 0.9 if label else 0.1},
            "exclusion": {"type": "choice", "probabilities": {"none": 0.8, "hype": 0.2}},
        }
        return {
            "evaluation_id": evaluation_id,
            "human_label": label,
            "production_decision": production,
            "production_score": 0.5,
            "arms": {
                "arm:a": {
                    "decision": decision,
                    "complete": True,
                    "repeats": [
                        {"repeat_index": i, "model": "m", "request_id": "r", "usage": {},
                         "latency_ms": 1, "answers": answers, "decision": {"eligible": decision}}
                        for i in (1, 2, 3)
                    ],
                }
            },
        }

    return {
        "format": "assay.relevance-arms/v1",
        "arms": {"arm:a": {"catalogue": "v2", "catalogue_version": "x", "reused": False}},
        "catalogues": {"v2": {"version": "x", "file_sha256": "y"}},
        "repeat_count": 3,
        "reference": "frozen",
        "failures": [],
        "metrics": {"production": {"accuracy": 0.5, "precision": 0.5, "recall": 1.0}},
        "cases": [case(1, True, True, "3", True), case(2, False, True, "2", False)],
    }


def test_arm_predictions_returns_none_when_an_arm_is_incomplete() -> None:
    from typesafe_relevance.report_arms import arm_predictions

    document = _arms_document()
    document["cases"][0]["arms"]["arm:a"]["complete"] = False
    assert arm_predictions(document, "arm:a") is None


def test_band_distribution_splits_by_human_label() -> None:
    from typesafe_relevance.report_arms import band_distribution

    counts = band_distribution(_arms_document(), "arm:a")
    assert counts == {"positive": {"substantive": 1}, "negative": {"pointer": 1}}


def test_question_discrimination_ranks_by_absolute_gap() -> None:
    from typesafe_relevance.report_arms import question_discrimination

    rows = question_discrimination(_arms_document(), "arm:a")
    assert rows[0][0] == "operational_claim"


def test_public_export_drops_no_answer_data_but_carries_no_state() -> None:
    from typesafe_relevance.report_arms import public_export

    exported = public_export(_arms_document())
    case = exported["cases"][0]
    assert "band" in case["arms"]["arm:a"]["repeats"][0]["answers"]
    assert "state" not in case and "text" not in case
