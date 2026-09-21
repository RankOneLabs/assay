"""Render the multi-arm relevance grid as a results table and a public export.

Two contrasts carry the report:

- **model swap** — arms sharing a catalogue, answered by different models. If they
  land together, the catalogue is the limit; if they separate, the model is.
- **wording swap** — arms sharing a model, answered over v1 and v2 criteria. This
  is the only difference between those catalogues, so any gap is wording.

The public export carries evaluation ids, labels, decisions and per-question
answer values but no post state or text, matching what the primary report
published.
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

BAND_NAMES = {0: "out_of_scope", 1: "building", 2: "pointer", 3: "substantive"}


def _answer_value(answer: Mapping[str, Any]) -> float | None:
    """Scalar view of one answer: noul value, or 1 - P(none) for a choice with none."""
    kind = answer.get("type")
    if kind == "noul":
        return float(answer["noul"])
    if kind == "choice" and "none" in answer.get("probabilities", {}):
        return 1.0 - float(answer["probabilities"]["none"])
    return None


def arm_ids(document: Mapping[str, Any]) -> list[str]:
    return list(document.get("arms", {}))


def arm_predictions(document: Mapping[str, Any], arm_id: str) -> list[bool] | None:
    predictions: list[bool] = []
    for case in document["cases"]:
        arm_case = case.get("arms", {}).get(arm_id)
        if not arm_case or not arm_case.get("complete"):
            return None
        predictions.append(bool(arm_case["decision"]))
    return predictions


def paired_disagreement(left: Sequence[bool], right: Sequence[bool]) -> int:
    return sum(a != b for a, b in zip(left, right, strict=True))


def question_discrimination(
    document: Mapping[str, Any], arm_id: str
) -> list[tuple[str, float, float, float]]:
    """Mean answer value on positive versus negative human labels, per question."""
    per_question: dict[str, tuple[list[float], list[float]]] = {}
    for case in document["cases"]:
        arm_case = case.get("arms", {}).get(arm_id)
        if not arm_case or not arm_case.get("complete"):
            continue
        label = bool(case["human_label"])
        for question_id in arm_case["repeats"][0]["answers"]:
            values = [
                value
                for repeat in arm_case["repeats"]
                if (value := _answer_value(repeat["answers"][question_id])) is not None
            ]
            if len(values) != len(arm_case["repeats"]):
                continue
            positives, negatives = per_question.setdefault(question_id, ([], []))
            (positives if label else negatives).append(statistics.mean(values))
    rows = [
        (question_id, statistics.mean(positives), statistics.mean(negatives),
         statistics.mean(positives) - statistics.mean(negatives))
        for question_id, (positives, negatives) in per_question.items()
        if positives and negatives
    ]
    return sorted(rows, key=lambda row: -abs(row[3]))


def band_distribution(document: Mapping[str, Any], arm_id: str) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {"positive": {}, "negative": {}}
    for case in document["cases"]:
        arm_case = case.get("arms", {}).get(arm_id)
        if not arm_case or not arm_case.get("complete"):
            continue
        bucket = "positive" if case["human_label"] else "negative"
        tops = []
        for repeat in arm_case["repeats"]:
            probabilities = repeat["answers"]["band"]["probabilities"]
            tops.append(int(max(probabilities, key=lambda key: probabilities[key])))
        majority = max(set(tops), key=tops.count)
        name = BAND_NAMES[majority]
        counts[bucket][name] = counts[bucket].get(name, 0) + 1
    return counts


def render(document: Mapping[str, Any]) -> str:
    metrics = document["metrics"]
    lines = [
        "| Arm | Accuracy | Precision | Recall | McNemar p vs production |",
        "|---|---:|---:|---:|---:|",
    ]
    production = metrics["production"]
    lines.append(
        f"| production (frozen) | {production['accuracy']:.1%} | "
        f"{production['precision']:.1%} | {production['recall']:.1%} | — |"
    )
    for arm_id in arm_ids(document):
        scored = metrics.get(arm_id, {})
        if "accuracy" not in scored:
            lines.append(f"| {arm_id} | incomplete | | | |")
            continue
        lines.append(
            f"| {arm_id} | {scored['accuracy']:.1%} | {scored['precision']:.1%} | "
            f"{scored['recall']:.1%} | {scored['mcnemar_vs_production']['p_value']:.4f} |"
        )
    return "\n".join(lines)


def public_export(document: Mapping[str, Any]) -> dict[str, Any]:
    """Text-free projection safe for assay's public evidence directory."""
    return {
        "format": "assay.relevance-arms-public/v1",
        "arms": document["arms"],
        "catalogues": document["catalogues"],
        "repeat_count": document["repeat_count"],
        "reference": document["reference"],
        "metrics": document["metrics"],
        "failures": document["failures"],
        "cases": [
            {
                "evaluation_id": case["evaluation_id"],
                "human_label": case["human_label"],
                "production_decision": case["production_decision"],
                "production_score": case["production_score"],
                "arms": {
                    arm_id: {
                        "decision": arm_case["decision"],
                        "complete": arm_case["complete"],
                        "repeats": [
                            {
                                "repeat_index": repeat["repeat_index"],
                                "model": repeat["model"],
                                "request_id": repeat["request_id"],
                                "usage": repeat["usage"],
                                "latency_ms": repeat["latency_ms"],
                                "answers": repeat["answers"],
                                "decision": repeat["decision"],
                            }
                            for repeat in arm_case["repeats"]
                        ],
                    }
                    for arm_id, arm_case in case.get("arms", {}).items()
                },
            }
            for case in document["cases"]
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--public-export", type=Path, default=None)
    args = parser.parse_args()
    document = json.loads(args.run.read_text(encoding="utf-8"))

    print(render(document))
    print()
    for arm_id in arm_ids(document):
        predictions = arm_predictions(document, arm_id)
        if predictions is None:
            continue
        counts = band_distribution(document, arm_id)
        print(f"{arm_id} band argmax — positives {counts['positive']}")
        print(f"{' ' * len(arm_id)}              negatives {counts['negative']}")
    print()
    ids = [a for a in arm_ids(document) if arm_predictions(document, a) is not None]
    for index, left in enumerate(ids):
        for right in ids[index + 1 :]:
            disagreement = paired_disagreement(
                arm_predictions(document, left) or [], arm_predictions(document, right) or []
            )
            print(f"{left} vs {right}: disagree on {disagreement} cases")

    if args.public_export is not None:
        args.public_export.write_text(
            json.dumps(public_export(document), sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
        print(f"\nwrote {args.public_export}")


if __name__ == "__main__":
    main()
