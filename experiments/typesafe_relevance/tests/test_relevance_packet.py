"""Tests for the blind relevance label packet: gate equivalence, blinding, scoring."""

from __future__ import annotations

import hashlib
import html
import json
import subprocess
from pathlib import Path

import pytest
from typesafe_relevance.catalogue import load_catalogue
from typesafe_relevance.mappings import decide_argmax
from typesafe_relevance.packet import (
    BAND_NAMES,
    DISPOSITIONS,
    PacketError,
    as_questions,
    blind_case,
    eligibility_gate,
    human_answers,
    human_decision,
    is_asked,
    plan_digest,
    route,
    rubric_card,
    select_census,
    select_packet,
    stratify,
    substance_rubric_card,
    surfaced,
)
from typesafe_relevance.packet_html import FORMATS_V2, render_packet_html
from typesafe_relevance.run_packet import (
    CENSUS_READING,
    PLAN,
    READING,
    packet_digest,
    score,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def questions() -> dict:
    return load_catalogue(FIXTURES / "band-form.yaml").questions


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
    page = render_packet_html("p", "d", "pd", cases, as_questions(rubric_card(questions)))
    for leaked in ("human_label", "production_decision", "author_name", "stratum", "evaluation_id"):
        assert leaked not in page


def test_rendered_page_uses_the_catalogue_wording_verbatim(questions: dict) -> None:
    page = render_packet_html(
        "p", "d", "pd", [{"case_id": 1, "text": "x"}], as_questions(rubric_card(questions))
    )
    assert html.escape(questions["band"]["instructions"]["note"]) in page
    for level in questions["band"]["criteria"]:
        assert html.escape(level["summary"]) in page


# --- the gate ---------------------------------------------------------------


def test_gate_matches_decide_argmax_on_every_stored_answer_vector(
    run_receipts_checkout: Path,
) -> None:
    """The mirrored gate must agree with the frozen mapping on real data.

    `mappings.py` is digest-pinned by published evidence and cannot be
    refactored to share the gate, so equivalence is asserted rather than
    structurally guaranteed.
    """
    arms_run = run_receipts_checkout / "typesafe-relevance-arms-2026-09/exported-answers.json"
    document = json.loads(arms_run.read_text(encoding="utf-8"))
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
    page = render_packet_html(
        "p", "d", "pd", [{"case_id": 1, "text": "x"}], as_questions(rubric_card(questions))
    )
    assert 'name="disposition:1"' in page
    assert page.count('type="radio"') == 4 + len(questions["exclusion"]["criteria"]) + 3


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


# --- published evidence integrity ---


@pytest.fixture
def census_evidence(run_receipts_checkout: Path) -> Path:
    return run_receipts_checkout / "typesafe-relevance-census-2026-09"


def _manifest(census_evidence: Path) -> dict:
    return json.loads((census_evidence / "checksums.json").read_text(encoding="utf-8"))


def test_census_evidence_files_match_the_working_tree(census_evidence: Path) -> None:
    """The labels behind every published number, pinned for good.

    These must validate at any commit. If this fails, a figure in RESULTS.md no
    longer has the data under it that produced it.
    """
    for name, digest in sorted(_manifest(census_evidence)["evidence_files"].items()):
        evidence_path = Path(name)
        assert not evidence_path.is_absolute() and ".." not in evidence_path.parts, name
        blob = (census_evidence / evidence_path).read_bytes()
        assert hashlib.sha256(blob).hexdigest() == digest, name


@pytest.mark.parametrize("name", ["../outside.json", "/outside.json"])
def test_census_evidence_files_stay_within_the_receipt(tmp_path: Path, name: str) -> None:
    manifest = {"evidence_files": {name: hashlib.sha256(b"").hexdigest()}}
    (tmp_path / "checksums.json").write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(AssertionError, match=name):
        test_census_evidence_files_match_the_working_tree(tmp_path)


def test_census_source_pins_are_checked_against_their_commit_not_head(
    census_evidence: Path,
) -> None:
    """Provenance, not a freeze.

    Unlike the arms run, the labelling instrument is still being developed, so
    these digests are expected to stop matching the working tree. They record what
    produced the labels, which means they are checked against the commit they name.
    The first version of this manifest pinned them against HEAD, which would have
    broken the moment the next sitting's code landed.
    """
    manifest = _manifest(census_evidence)
    commit = manifest["source_commit"]
    for name, digest in sorted(manifest["source_files_at_commit"].items()):
        found = subprocess.run(
            ["git", "show", f"{commit}:{name}"],
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            check=False,
        )
        if found.returncode != 0:
            pytest.skip(f"commit {commit} is not in this clone")
        assert hashlib.sha256(found.stdout).hexdigest() == digest, name


def test_census_manifest_does_not_pin_source_files_as_evidence(census_evidence: Path) -> None:
    """The bug this file is guarding against, stated directly."""
    assert not [
        name for name in _manifest(census_evidence)["evidence_files"] if name.startswith("src/")
    ]


# --- the substance rule ---

@pytest.fixture
def v3_questions() -> dict:
    questions = load_catalogue(FIXTURES / "label-form.yaml").questions
    return {key: q for key, q in questions.items() if key != "needs_thread"}


def _substance_labels(rows: list[tuple[str, str | None]]) -> dict:
    return {
        "format": "assay.label-packet-labels/v2",
        "plan_digest": plan_digest(READING),
        "reviewer": "test",
        "saved_at": "2026-09-19T00:00:00Z",
        "cases": [
            {"case_id": index + 1, "exclusion": exclusion, "substance": substance}
            for index, (exclusion, substance) in enumerate(rows)
        ],
    }


def test_the_rule_routes_each_substance_answer_to_its_outcome() -> None:
    """The whole rule. If this passes there is no other branch to test."""
    assert route("none", "in_post") == "respond"
    assert route("none", "pointer") == "review"
    assert route("none", "none") == "drop"
    assert route("hype", None) == "drop"


def test_an_exclusion_ends_the_case_without_a_substance_answer() -> None:
    """The chain, which is the whole reason the two questions are not a flat form.

    An excluded post is one decision. A substance answer arriving beside an
    exclusion means the page failed to prune, and that must fail loudly rather
    than quietly land a contradiction in the labels of record.
    """
    assert route("non_english", None) == "drop"
    with pytest.raises(PacketError, match="substance answered on excluded post"):
        route("hype", "in_post")


def test_the_rule_rejects_an_answer_it_does_not_recognise() -> None:
    """A typo must fail loudly rather than silently dropping a post."""
    with pytest.raises(PacketError, match="unknown substance"):
        route("none", "in-post")
    with pytest.raises(PacketError, match="unknown exclusion"):
        route("nonw", "in_post")
    with pytest.raises(PacketError, match="unknown substance"):
        route("none", None)


def test_both_non_drop_routes_surface_because_scout_has_no_review_state() -> None:
    """`review` is the outcome being studied; `surfaced` is what scout can do.

    Kept apart so that adding a review status later changes one function.
    """
    assert surfaced("none", "in_post")
    assert surfaced("none", "pointer")
    assert not surfaced("none", "none")
    assert not surfaced("hype", None)


def test_sitting_two_asks_two_questions_and_not_the_band(v3_questions: dict) -> None:
    card = substance_rubric_card(v3_questions)
    assert [question["key"] for question in card] == ["exclusion", "substance"]


def test_substance_is_only_asked_of_a_post_that_cleared_the_exclusions(
    v3_questions: dict,
) -> None:
    """The condition lives in the packet, so page and server cannot drift apart."""
    card = substance_rubric_card(v3_questions)
    exclusion, substance = card
    assert exclusion["asked_when"] is None
    assert substance["asked_when"] == {"question": "exclusion", "equals": "none"}
    assert is_asked(substance, {"exclusion": "none"})
    assert not is_asked(substance, {"exclusion": "hype"})
    assert not is_asked(substance, {})


def test_the_substance_options_are_offered_in_the_order_their_tests_apply(
    v3_questions: dict,
) -> None:
    """`in_post` before `pointer` is the tie-break a link post turns on.

    A post that states a claim and links to the writeup is `in_post`; only a post
    you cannot answer without opening the link is `pointer`. Order is how the
    page communicates that, so it is pinned.
    """
    card = substance_rubric_card(v3_questions)
    substance = next(q for q in card if q["key"] == "substance")
    assert [option["value"] for option in substance["options"]] == [
        "in_post",
        "pointer",
        "none",
    ]


def test_the_substance_page_asks_substance_and_never_band(v3_questions: dict) -> None:
    page = render_packet_html(
        "p", "d", "pd", [{"case_id": 1, "text": "x"}], substance_rubric_card(v3_questions)
    )
    assert 'name="substance:1"' in page
    assert 'name="band:1"' not in page
    assert 'name="scope:1"' not in page


def test_a_conditional_question_renders_hidden_so_it_is_not_answered_first(
    v3_questions: dict,
) -> None:
    """Rendered but hidden, so the page stays static HTML with no templating."""
    page = render_packet_html(
        "p", "d", "pd", [{"case_id": 1, "text": "x"}], substance_rubric_card(v3_questions)
    )
    assert 'id="q-substance-1" class="disp hidden"' in page
    assert 'id="q-exclusion-1"' in page


def test_the_substance_page_stamps_the_v2_label_format(v3_questions: dict) -> None:
    """A reader must be able to tell which questions a label file answers."""
    page = render_packet_html(
        "p",
        "d",
        "pd",
        [{"case_id": 1, "text": "x"}],
        substance_rubric_card(v3_questions),
        formats=FORMATS_V2,
    )
    assert '"labels_format": "assay.label-packet-labels/v2"' in page


def test_scoring_dispatches_on_the_label_format(questions: dict) -> None:
    """v2 labels must not be scored through the band gate, which would KeyError."""
    labels = _substance_labels([("none", "in_post")] * 3)
    report = score(labels, _key(), questions)
    assert report["format"] == "assay.label-packet-report/v2"


def test_the_band_path_still_scores_v1_labels(questions: dict) -> None:
    """The census must stay reproducible after its question is retired."""
    labels = _labels([3, 2, 0])
    for entry, disposition in zip(labels["cases"], ["respond", "review", "drop"], strict=True):
        entry["disposition"] = disposition
    assert score(labels, _key(), questions)["format"] == "assay.label-packet-report/v1"


def test_the_surfaced_rate_counts_only_posts_the_rule_admits(questions: dict) -> None:
    labels = _substance_labels([("none", "in_post"), ("none", "none"), ("hype", None)])
    report = score(labels, _key(), questions)
    assert report["surfaced"] == {"surfaced": 1, "n": 3, "rate": 0.3333}


def test_the_route_distribution_separates_respond_from_review(questions: dict) -> None:
    """The split scout cannot act on yet is still the thing being measured."""
    labels = _substance_labels([("none", "in_post"), ("none", "pointer"), ("hype", None)])
    report = score(labels, _key(), questions)
    assert report["route_distribution"] == {"respond": 1, "review": 1, "drop": 1}


def test_posts_an_exclusion_ended_are_counted_rather_than_dropped(questions: dict) -> None:
    """The substance counts and the exclusion counts must reconcile to n."""
    labels = _substance_labels([("none", "in_post"), ("hype", None), ("non_english", None)])
    report = score(labels, _key(), questions)
    assert report["substance_distribution"]["null"] == 2
    assert sum(report["substance_distribution"].values()) == 3


def test_the_census_crosswalk_scores_only_the_bands_that_map(questions: dict) -> None:
    """`building` absorbed both kinds under apply_in_order, so it cannot be scored.

    Leaving it out of the primary and still tabulating it is what keeps the
    excluded cases visible rather than silently missing.
    """
    labels = _substance_labels([("none", "in_post"), ("none", "none"), ("none", "pointer")])
    census = {
        "cases": [
            {"evaluation_id": 100, "band": "substantive"},
            {"evaluation_id": 101, "band": "building"},
            {"evaluation_id": 102, "band": "pointer"},
        ]
    }
    report = score(labels, _key(), questions, census=census)
    walk = report["census_crosswalk"]
    assert walk == {
        "n": 2,
        "agree": 2,
        "rate": 1.0,
        "matched_cases": 3,
        "by_band": walk["by_band"],
    }
    assert walk["by_band"]["building"]["none"] == 1
