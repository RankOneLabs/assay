"""Pure decision mappings used by the Typesafe relevance experiment."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

SUBSTANCE = ("operational_claim", "reasoned_practice", "operational_question")


def _probabilities(answer: Mapping[str, Any], name: str) -> Mapping[Any, float]:
    value = answer.get(name)
    if not isinstance(value, Mapping) or not isinstance(value.get("probabilities"), Mapping):
        raise ValueError(f"missing probabilities for {name}")
    return cast(Mapping[Any, float], value["probabilities"])


def _noul(answer: Mapping[str, Any], name: str) -> float:
    value = answer.get(name)
    if not isinstance(value, Mapping) or not isinstance(value.get("noul"), (int, float)):
        raise ValueError(f"missing noul for {name}")
    return float(value["noul"])


def derive_band(answers: Mapping[str, Any], threshold: float = 0.5) -> str:
    exclusion = _probabilities(answers, "exclusion")
    if 1.0 - float(exclusion.get("none", 0.0)) >= threshold:
        return "out_of_scope"
    if max(_noul(answers, name) for name in SUBSTANCE) >= threshold and _noul(
        answers, "point_in_own_text"
    ) >= threshold:
        return "substantive"
    if _noul(answers, "on_topic_pointer") >= threshold:
        return "pointer"
    if _noul(answers, "general_building") >= threshold:
        return "building"
    return "out_of_scope"


def decide_argmax(answers: Mapping[str, Any]) -> dict[str, Any]:
    band = _probabilities(answers, "band")
    exclusion = _probabilities(answers, "exclusion")
    p_substantive = float(band.get(3, band.get("3", band.get("substantive", 0.0))))
    p_exclusion = 1.0 - float(exclusion.get("none", 0.0))
    eligible = p_substantive >= 0.5 and p_exclusion < 0.5
    exclusion_label = max(exclusion, key=exclusion.__getitem__)
    return {
        "eligible": eligible,
        "p_eligible": p_substantive,
        "uncertain": False,
        "reason": (
            f"hard exclusion: {exclusion_label} ({p_exclusion:.3f})"
            if p_exclusion >= 0.5
            else f"band substantive probability {p_substantive:.3f}"
        ),
        "account_label": answers.get("account_type", {}).get("choice"),
        "account_confidence": answers.get("account_type", {}).get("confidence"),
        "details": {
            "band_probabilities": dict(band),
            "exclusion": exclusion_label,
            "exclusion_probability": p_exclusion,
            "derived_band": derive_band(answers),
        },
    }


DECIDE_REGISTRY = {"agent_ops_relevance/v1": decide_argmax}
