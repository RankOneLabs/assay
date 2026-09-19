"""Tests for the blind relevance label packet: gate equivalence, blinding, scoring."""

from __future__ import annotations

import html
import json
import os
from pathlib import Path

import pytest

from assay.investigations.relevance.catalogue import load_catalogue
from assay.investigations.relevance.mappings import decide_argmax
from assay.investigations.relevance.packet import (
    BAND_NAMES,
    DISPOSITIONS,
    PacketError,
    blind_case,
    eligibility_gate,
    human_answers,
    human_decision,
    plan_digest,
    rubric_card,
    select_census,
    select_packet,
    stratify,
)
from assay.investigations.relevance.packet_html import render_packet_html
from assay.investigations.relevance.run_packet import (
    CENSUS_READING,
    PLAN,
    READING,
    packet_digest,
    score,
)

CATALOGUE = Path("src/assay/investigations/relevance/catalogues/agent-ops-relevance.v2.yaml")

#: The arms run carries post text, so it lives in the private receipts repo and is
#: absent in CI. Override with ``ASSAY_ARMS_RUN`` when it sits elsewhere.
ARMS_RUN = Path(
    os.environ.get(
        "ASSAY_ARMS_RUN",
        str(Path.home() / "codes/rol/run-receipts/typesafe-relevance-2026-09/arms-run.json"),
    )
)


@pytest.fixture
def questions() -> dict:
    return load_catalogue(CATALOGUE).questions


def _document() -> dict:
    """A small arms document with one case in each shape the stratifier names."""

    def case(evaluation_id: int, label: bool, decisions: dict[str, bool]) -> dict:
        return {
            "evaluation_id": evaluation_id,
            "human_label": label,
            "production_decision": True,
            "arms": {
                arm: {"decision": value, "complete": True, "repeats": []}
                for arm, value in decisions.items()
            },
        }

    return {
        "arms": {"a": {}, "b": {}},
        "cases": [
            case(1, True, {"a": False, "b": False}),  # crux
            case(2, False, {"a": True, "b": True}),  # mirror
            case(3, True, {"a": True, "b": True}),  # unanimous_yes_positive
            case(4, False, {"a": False, "b": False}),  # unanimous_no_negative
            case(5, True, {"a": True, "b": False}),  # split_positive
            case(6, False, {"a": True, "b": False}),  # split_negative
        ],
    }


def test_stratify_names_every_shape() -> None:
    assert set(stratify(_document())) == {
        "crux",
        "mirror",
        "unanimous_yes_positive",
        "unanimous_no_negative",
        "split_positive",
        "split_negative",
    }


def test_crux_is_stored_positive_that_every_arm_rejected() -> None:
    assert stratify(_document())["crux"] == [1]


def test_select_packet_is_deterministic_under_a_seed() -> None:
    plan = [("crux", 1), ("mirror", 1)]
    first = select_packet(_document(), "p", "seed-a", plan)
    second = select_packet(_document(), "p", "seed-a", plan)
    assert [c.evaluation_id for c in first.cases] == [c.evaluation_id for c in second.cases]


def test_select_packet_reorders_under_a_different_seed() -> None:
    plan = [("crux", 1), ("mirror", 1), ("split_positive", 1), ("split_negative", 1)]
    a = [c.evaluation_id for c in select_packet(_document(), "p", "seed-a", plan).cases]
    b = [c.evaluation_id for c in select_packet(_document(), "p", "seed-z", plan).cases]
    assert sorted(a) == sorted(b)


def test_select_packet_rejects_a_stratum_that_is_too_small() -> None:
    with pytest.raises(PacketError, match="need 9"):
        select_packet(_document(), "p", "s", [("crux", 9)])


def test_case_ids_are_assigned_after_the_display_shuffle() -> None:
    plan = [("crux", 1), ("mirror", 1), ("split_positive", 1)]
    packet = select_packet(_document(), "p", "seed-a", plan)
    assert [c.case_id for c in packet.cases] == [1, 2, 3]


# --- blinding ---------------------------------------------------------------


def test_blind_case_carries_only_text_and_parent() -> None:
    record = {
        "text": "a post",
        "parent_text": "a parent",
        "human_label": True,
        "author_name": "Grafana",
        "url": "https://example.test",
        "production_score": 0.85,
    }
    assert blind_case(4, record) == {"case_id": 4, "text": "a post", "parent_text": "a parent"}


def test_blind_case_tolerates_a_post_with_no_parent() -> None:
    assert blind_case(1, {"text": "x"})["parent_text"] is None


def test_rendered_page_contains_no_author_or_label(questions: dict) -> None:
    cases = [{"case_id": 1, "text": "a post by Grafana", "parent_text": None}]
    page = render_packet_html("p", "d", "pd", cases, rubric_card(questions))
    for leaked in ("human_label", "production_decision", "author_name", "stratum", "evaluation_id"):
        assert leaked not in page


def test_rendered_page_uses_the_catalogue_wording_verbatim(questions: dict) -> None:
    page = render_packet_html("p", "d", "pd", [{"case_id": 1, "text": "x"}], rubric_card(questions))
    assert html.escape(questions["band"]["instructions"]["note"]) in page
    for level in questions["band"]["criteria"]:
        assert html.escape(level["summary"]) in page


# --- the gate ---------------------------------------------------------------


def test_gate_matches_decide_argmax_on_every_stored_answer_vector() -> None:
    """The mirrored gate must agree with the frozen mapping on real data.

    `mappings.py` is digest-pinned by published evidence and cannot be
    refactored to share the gate, so equivalence is asserted rather than
    structurally guaranteed.
    """
    if not ARMS_RUN.exists():
        pytest.skip("private arms run is not present")
    document = json.loads(ARMS_RUN.read_text(encoding="utf-8"))
    compared = 0
    for case in document["cases"]:
        for arm_case in case.get("arms", {}).values():
            for repeat in arm_case["repeats"]:
                answers = repeat["answers"]
                assert eligibility_gate(answers) == decide_argmax(answers)["eligible"]
                compared += 1
    assert compared > 1000


def test_gate_rejects_a_substantive_post_under_a_hard_exclusion(questions: dict) -> None:
    assert human_decision(3, "hype", questions) is False


def test_gate_accepts_a_substantive_post_with_no_exclusion(questions: dict) -> None:
    assert human_decision(3, "none", questions) is True


def test_gate_rejects_every_band_below_substantive(questions: dict) -> None:
    assert [human_decision(index, "none", questions) for index in range(4)] == [
        False,
        False,
        False,
        True,
    ]


def test_human_answers_are_one_hot_over_the_catalogue_domain(questions: dict) -> None:
    answers = human_answers(2, "none", questions)
    assert answers["band"]["probabilities"] == {"0": 0.0, "1": 0.0, "2": 1.0, "3": 0.0}
    assert sorted(answers["exclusion"]["probabilities"]) == sorted(
        questions["exclusion"]["criteria"]
    )


def test_human_answers_rejects_an_unknown_exclusion(questions: dict) -> None:
    with pytest.raises(PacketError, match="unknown exclusion"):
        human_answers(0, "not_a_category", questions)


def test_human_answers_rejects_a_band_out_of_range(questions: dict) -> None:
    with pytest.raises(PacketError, match="band index out of range"):
        human_answers(9, "none", questions)


# --- rubric -----------------------------------------------------------------


def test_rubric_lists_the_four_bands_in_catalogue_order(questions: dict) -> None:
    assert [level["name"] for level in rubric_card(questions)["band"]["levels"]] == list(BAND_NAMES)


def test_rubric_carries_every_exclusion_option(questions: dict) -> None:
    names = [option["name"] for option in rubric_card(questions)["exclusion"]["options"]]
    assert names == list(questions["exclusion"]["criteria"])


# --- scoring ----------------------------------------------------------------


def _key() -> dict:
    return {
        "format": "assay.label-packet-key/v1",
        "name": "p",
        "digest": "d",
        "plan_digest": plan_digest(READING),
        "cases": [
            {
                "case_id": index + 1,
                "evaluation_id": 100 + index,
                "stratum": "crux",
                "stored_label": True,
                "production_decision": True,
                "arms": {"a": False, "b": False},
            }
            for index in range(3)
        ],
    }


def _labels(bands: list[int]) -> dict:
    return {
        "plan_digest": plan_digest(READING),
        "reviewer": "test",
        "saved_at": "2026-09-18T00:00:00Z",
        "cases": [
            {"case_id": index + 1, "band": band, "exclusion": "none"}
            for index, band in enumerate(bands)
        ],
    }


def test_score_counts_crux_cases_where_the_reviewer_sides_with_the_arms(questions: dict) -> None:
    report = score(_labels([2, 2, 3]), _key(), questions)
    assert report["primary"]["reviewer_sides_with_arms"] == 2


def test_score_refuses_labels_collected_under_a_different_plan(questions: dict) -> None:
    labels = _labels([2, 2, 2])
    labels["plan_digest"] = "stale"
    with pytest.raises(PacketError, match="plan digest"):
        score(labels, _key(), questions)


def test_score_refuses_a_label_for_an_unknown_case(questions: dict) -> None:
    labels = _labels([2, 2, 2])
    labels["cases"][0]["case_id"] = 99
    with pytest.raises(PacketError, match="unknown case"):
        score(labels, _key(), questions)


def test_score_reports_disagreement_with_the_stored_label(questions: dict) -> None:
    report = score(_labels([2, 2, 3]), _key(), questions)
    assert [row["agrees_with_stored"] for row in report["cases"]] == [False, False, True]


def test_plan_digest_changes_when_the_reading_changes() -> None:
    altered = {**READING, "otherwise": "different"}
    assert plan_digest(altered) != plan_digest(READING)


def test_declared_plan_draws_thirty_cases() -> None:
    assert sum(take for _, take in PLAN) == 30


# --- census -----------------------------------------------------------------


def test_census_covers_every_case_exactly_once() -> None:
    packet = select_census(_document(), "c", "seed-a")
    ids = [case.evaluation_id for case in packet.cases]
    assert sorted(ids) == [1, 2, 3, 4, 5, 6]


def test_census_keeps_the_stratum_tag_for_reporting() -> None:
    packet = select_census(_document(), "c", "seed-a")
    by_id = {case.evaluation_id: case.stratum for case in packet.cases}
    assert by_id[1] == "crux"


def test_census_display_order_is_not_evaluation_order() -> None:
    packet = select_census(_document(), "c", "seed-a")
    assert [case.evaluation_id for case in packet.cases] != [1, 2, 3, 4, 5, 6]


def test_census_reading_digest_differs_from_the_sampled_reading() -> None:
    assert plan_digest(CENSUS_READING) != plan_digest(READING)


def test_disposition_offers_exactly_three_outcomes() -> None:
    assert [name for name, _ in DISPOSITIONS] == ["respond", "review", "drop"]


# --- packet identity --------------------------------------------------------


def _blind() -> list[dict]:
    return [{"case_id": 1, "text": "a"}, {"case_id": 2, "text": "b"}]


def test_a_second_sitting_over_the_same_cases_is_a_different_packet(questions: dict) -> None:
    """The load-bearing one.

    The browser keys its saved draft on this digest. If a repeat reading of the
    same cases hashed the same, the previous sitting's answers would hydrate into
    the form and the retest would report perfect agreement having measured nothing.
    """
    rubric = rubric_card(questions)
    assert packet_digest(_blind(), rubric, "one") != packet_digest(_blind(), rubric, "two")


def test_changing_the_questions_is_a_different_packet(questions: dict) -> None:
    """Answers to one question set must not be restored into another."""
    altered = {**questions, "band": {**questions["band"], "criteria": []}}
    assert packet_digest(_blind(), rubric_card(questions), "one") != packet_digest(
        _blind(), rubric_card(altered), "one"
    )


def test_rebuilding_the_same_sitting_is_the_same_packet(questions: dict) -> None:
    """A draft in progress must survive a rebuild of the packet it belongs to."""
    rubric = rubric_card(questions)
    assert packet_digest(_blind(), rubric, "one") == packet_digest(_blind(), rubric, "one")


def test_rubric_card_carries_the_disposition_question(questions: dict) -> None:
    options = rubric_card(questions)["disposition"]["options"]
    assert [option["name"] for option in options] == ["respond", "review", "drop"]


def test_rendered_page_asks_the_disposition_question(questions: dict) -> None:
    page = render_packet_html("p", "d", "pd", [{"case_id": 1, "text": "x"}], rubric_card(questions))
    assert 'name="disposition:1"' in page
    assert page.count('type="radio"') == 4 + 7 + 3


def test_score_reports_the_disposition_distribution(questions: dict) -> None:
    labels = _labels([3, 2, 0])
    for entry, disposition in zip(labels["cases"], ["respond", "review", "drop"], strict=True):
        entry["disposition"] = disposition
    report = score(labels, _key(), questions)
    assert report["disposition_distribution"] == {"respond": 1, "review": 1, "drop": 1}


def test_score_cross_tabs_band_against_disposition(questions: dict) -> None:
    labels = _labels([2, 2, 3])
    for entry, disposition in zip(labels["cases"], ["review", "drop", "respond"], strict=True):
        entry["disposition"] = disposition
    report = score(labels, _key(), questions)
    assert report["band_by_disposition"]["pointer"] == {"respond": 0, "review": 1, "drop": 1}
