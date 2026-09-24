"""Tests for round 4's ``route()`` and the feature catalogues it reads."""

from __future__ import annotations

from pathlib import Path

import pytest
from typesafe_relevance.catalogue import load_catalogue
from typesafe_relevance.render import answer_schema
from typesafe_relevance.route import EXCLUSION_PREFIX, ROUTED, route


def _answers(**values: float) -> dict:
    base = {"excl_hype": 0.0, "excl_hardware": 0.0} | dict.fromkeys(ROUTED, 0.0)
    return {name: {"type": "noul", "noul": p} for name, p in (base | values).items()}


def test_exclusion_drops_first() -> None:
    decision = route(_answers(excl_hype=0.9, answerable_from_post=0.9, about_agent_work=0.9))
    assert (decision["action"], decision["exclusion"]) == ("drop", "hype")


def test_any_excl_answer_is_an_exclusion() -> None:
    decision = route(_answers(excl_benchmark=0.9, answerable_from_post=0.9, about_agent_work=0.9))
    assert (decision["action"], decision["exclusion"]) == ("drop", "benchmark")


def test_needs_thread_reviews_before_respond() -> None:
    decision = route(_answers(needs_thread=0.9, answerable_from_post=0.9, about_agent_work=0.9))
    assert (decision["action"], decision["line"]) == ("review", "needs_thread")


def test_respond_needs_both_answerable_and_about() -> None:
    assert route(_answers(answerable_from_post=0.9, about_agent_work=0.9))["action"] == "respond"
    assert route(_answers(answerable_from_post=0.9, about_agent_work=0.1))["action"] == "drop"


def test_pointer_reviews_and_nothing_drops() -> None:
    assert route(_answers(points_somewhere=0.9))["line"] == "points_somewhere"
    assert route(_answers())["action"] == "drop"


def test_margin_overrides_the_path() -> None:
    decision = route(_answers(answerable_from_post=0.9, about_agent_work=0.55))
    assert (decision["path_action"], decision["action"]) == ("respond", "review")
    assert decision["margin"] == ["about_agent_work"]


def test_margin_only_counts_consulted_features() -> None:
    decision = route(_answers(excl_hardware=0.9, points_somewhere=0.5))
    assert decision["action"] == "drop"


@pytest.mark.parametrize("version", ["v4", "v5", "v6"])
def test_feature_catalogue_has_exactly_the_routed_features(
    relevance_catalogues: Path, version: str
) -> None:
    path = relevance_catalogues / f"agent-ops-relevance-features.{version}.yaml"
    questions = load_catalogue(path).questions
    exclusions = {q for q in questions if q.startswith(EXCLUSION_PREFIX)}
    assert exclusions
    assert set(questions) - exclusions == set(ROUTED)
    assert all(q["type"] == "noul" for q in questions.values())
    answer_schema(questions)
