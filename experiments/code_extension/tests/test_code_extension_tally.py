"""The library study's tally applies the plan's decision table, first matching row first."""

from __future__ import annotations

from collections import Counter

import pytest
from code_extension.classification import (
    CandidateStopped,
    EvaluatorVerdict,
    GroupVerdict,
    Submitted,
)
from code_extension.library import SUBJECTS
from code_extension.reachability import attempt_outcome
from code_extension.tally import CONTROLS, GROUPS, NON_LOCAL, Counts, app, decide, group_table

MODELS = ("ministral", "sol")
# Non-local tasks by app: dbos 2, observation 3, kbbl 4.
DBOS = SUBJECTS["worker-silence-bound"]
DBOS_2 = SUBJECTS["operations-route"]
OBSERVATION = SUBJECTS["addressing-runner"]
KBBL = SUBJECTS["context-usage-inbox"]
KBBL_2 = SUBJECTS["agent-default-model"]
KBBL_3 = SUBJECTS["gated-review-shortcuts"]
CONTROL = SUBJECTS["worker-start-budget"]


def full(outcome: str = "semantic") -> Counts:
    """Every pairing complete, with one pass so the cohort is not at floor or ceiling."""
    return {(model, subject): Counter({outcome: 4, "passed": 1})
            for model in MODELS for subject in SUBJECTS.values()}


def with_reachability(counts: Counts, model: str, *subjects: str, failures: int = 2) -> Counts:
    for subject in subjects:
        counts[(model, subject)] = Counter({"reachability": failures, "passed": 5 - failures})
    return counts


def test_groups_cover_every_task_once_and_controls_stay_out_of_non_local() -> None:
    grouped = [subject for subjects in GROUPS.values() for subject in subjects]
    assert sorted(grouped) == sorted(SUBJECTS.values())
    assert len(NON_LOCAL) == 9 and len(CONTROLS) == 2 and not NON_LOCAL & CONTROLS
    by_app = Counter(app(subject) for subject in NON_LOCAL)
    assert by_app == {"dbos": 2, "observation": 3, "kbbl": 4}


def test_a_missing_or_unsettled_attempt_is_incomplete() -> None:
    missing = full()
    del missing[("sol", CONTROL)]
    assert decide(missing, MODELS).result == "Incomplete"
    unsettled = full()
    unsettled[("sol", CONTROL)] = Counter({"semantic": 4, "unsettled": 1})
    assert decide(unsettled, MODELS).result == "Incomplete"


def test_floor_or_ceiling_wins_even_when_the_rule_is_met() -> None:
    counts = {key: Counter({"passed": 5}) for key in full()}
    assert decide(counts, MODELS).result == "Floor or ceiling"


def test_no_model_is_readable_when_too_few_attempts_ran_their_feature_tests() -> None:
    assert decide(full("limit_stop"), MODELS).result == "No model is readable"


def test_recurs_needs_three_tasks_across_two_apps_and_a_clean_control() -> None:
    counts = with_reachability(full(), "sol", DBOS, OBSERVATION, KBBL)
    assert decide(counts, MODELS).result == "Recurs with a clean control: sol"


def test_three_tasks_in_one_app_do_not_recur() -> None:
    counts = with_reachability(full(), "sol", KBBL, KBBL_2, KBBL_3)
    assert decide(counts, MODELS).result == "Some non-local tasks show missed integration"


def test_two_tasks_do_not_recur() -> None:
    counts = with_reachability(full(), "sol", DBOS, OBSERVATION)
    assert decide(counts, MODELS).result == "Some non-local tasks show missed integration"


def test_one_failure_on_a_task_does_not_show_missed_integration() -> None:
    counts = with_reachability(full(), "sol", DBOS, OBSERVATION, KBBL, failures=1)
    assert decide(counts, MODELS).result == "No non-local task shows missed integration"


def test_a_control_failure_blocks_the_clean_result() -> None:
    counts = with_reachability(full(), "sol", DBOS, OBSERVATION, KBBL, CONTROL)
    assert decide(counts, MODELS).result == "Recurs without a clean control: sol"


def test_the_clean_control_must_belong_to_the_model_that_recurs() -> None:
    counts = with_reachability(full(), "sol", DBOS, OBSERVATION, KBBL, CONTROL)
    with_reachability(counts, "ministral", CONTROL)
    assert decide(counts, MODELS).result == "Recurs without a clean control: sol"


def test_tasks_shown_by_different_models_do_not_add_up() -> None:
    counts = with_reachability(full(), "sol", DBOS, OBSERVATION)
    with_reachability(counts, "ministral", KBBL, DBOS_2)
    assert decide(counts, MODELS).result == "Some non-local tasks show missed integration"


def test_only_a_control_failure_is_not_a_non_local_finding() -> None:
    counts = with_reachability(full(), "sol", CONTROL)
    assert decide(counts, MODELS).result == "No non-local task shows missed integration"


def test_an_omitted_feature_never_counts() -> None:
    counts = full()
    for subject in (DBOS, OBSERVATION, KBBL):
        counts[("sol", subject)] = Counter({"omitted_stage": 5})
    assert decide(counts, MODELS).result == "No non-local task shows missed integration"


def test_the_group_table_counts_reachability_failures_only() -> None:
    table = group_table({"sol": [
        {"cell": f"{DBOS}:baseline:w0", "outcome": "reachability"},
        {"cell": f"{DBOS}:baseline:w1", "outcome": "semantic"},
    ]})
    assert "| Carried through layers | 1 |" in table
    assert "| Control | 0 |" in table


GROUP_RAN = EvaluatorVerdict("incorrect", (GroupVerdict("failed", name="new_behavior"),))
NOTHING_RAN = EvaluatorVerdict("incorrect", (GroupVerdict("unavailable", name="new_behavior"),))
PASSED = EvaluatorVerdict("correct", (GroupVerdict("passed", name="new_behavior"),))


@pytest.mark.parametrize(
    ("stop", "verdict", "terminal", "failure", "expected"),
    [
        (CandidateStopped("agent_deadline"), None, "wall_limit", None, "timeout"),
        (CandidateStopped("no_submission"), None, "turn_limit", None, "limit_stop"),
        (CandidateStopped("no_submission"), None, "output_token_limit", None, "limit_stop"),
        (CandidateStopped("no_submission"), None, "no_tool_call", None, "no_submission"),
        (CandidateStopped("tampering"), None, "tampering", None, "scope_or_integrity"),
        (Submitted(), None, "normal_submission", None, "harness_failure"),
        (Submitted(), NOTHING_RAN, "normal_submission", None, "unusable_patch"),
        (Submitted(), GROUP_RAN, "normal_submission", "reachability", "reachability"),
        (Submitted(), GROUP_RAN, "normal_submission", "omitted_stage", "omitted_stage"),
        (Submitted(), GROUP_RAN, "normal_submission", None, "regression_only"),
        (Submitted(), PASSED, "normal_submission", None, "passed"),
    ],
)
def test_each_attempt_gets_one_outcome_in_table_order(
    stop: object,
    verdict: EvaluatorVerdict | None,
    terminal: str,
    failure: str | None,
    expected: str,
) -> None:
    assert attempt_outcome(stop, verdict, terminal, failure) == expected  # type: ignore[arg-type]
