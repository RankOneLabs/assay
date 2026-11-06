"""The November cohorts prepare offline to the sizes the study plan states."""

from __future__ import annotations

from pathlib import Path

import pytest
from code_extension.config import RunConfiguration
from code_extension.launch import prepare_cohort

STUDY = Path(__file__).parents[1] / "studies" / "matched-tasks-2026-11"
MINISTRAL = ("mistralai/ministral-14b-2512", "mistral/zdr")
QWEN = ("qwen/qwen3.8-27b", "deepinfra/bf16")
SOL = ("openai/gpt-6.1-sol", "azure/us")


@pytest.fixture(autouse=True)
def pinned_image(monkeypatch: pytest.MonkeyPatch) -> None:
    """Preparing checks the local Docker image, which CI does not provision."""
    image = RunConfiguration.load(STUDY / "study-qwen.json").image_digest
    monkeypatch.setattr("code_extension.bridge.observed_image_digest", lambda _: image)


@pytest.mark.parametrize(
    ("name", "plans", "combined_cap"),
    [
        ("calibration", [(8, MINISTRAL), (8, QWEN)], "4.00"),
        ("study", [(40, MINISTRAL), (40, QWEN)], "16.00"),
        (
            "study-with-control",
            [(40, MINISTRAL), (20, MINISTRAL), (40, QWEN), (20, QWEN)],
            "24.00",
        ),
        ("third-model", [(60, SOL)], "15.00"),
        ("study-with-sol", [(40, MINISTRAL), (40, QWEN), (60, SOL)], "31.00"),
    ],
)
def test_cohort_prepares_its_stated_grid_without_a_credential(
    name: str, plans: list[tuple[int, tuple[str, str]]], combined_cap: str,
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    summary = prepare_cohort(STUDY / f"{name}.json", tmp_path / "store")
    observed = [
        (plan["attempts"], (plan["model"]["model"], plan["model"]["provider"]))
        for plan in summary["plans"]
    ]
    assert observed == plans
    assert summary["caps"]["combined_usd"] == combined_cap
    assert not any(plan["unresolved_blockers"] for plan in summary["plans"])


def test_calibration_attempts_cannot_land_in_a_study_plan(tmp_path: Path) -> None:
    store = tmp_path / "store"
    calibration = prepare_cohort(STUDY / "calibration.json", store)
    study = prepare_cohort(STUDY / "study.json", store)
    assert not {plan["digest"] for plan in calibration["plans"]} & {
        plan["digest"] for plan in study["plans"]
    }


@pytest.mark.parametrize("name", ["study-with-control", "study-with-sol"])
def test_a_wider_cohort_reuses_the_study_plans(name: str, tmp_path: Path) -> None:
    store = tmp_path / "store"
    study = prepare_cohort(STUDY / "study.json", store)
    combined = prepare_cohort(STUDY / f"{name}.json", store)
    assert {plan["digest"] for plan in study["plans"]} < {
        plan["digest"] for plan in combined["plans"]
    }
