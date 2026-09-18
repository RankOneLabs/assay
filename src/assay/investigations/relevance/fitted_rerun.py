"""Leakage-safe fitted replay over the retained Typesafe answer vectors."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

import sklearn
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold

FEATURE_EXTRACTOR = "scout-pr40/extract_features"
FITTER = "scout-pr40/l2-logistic-liblinear"


def extract_features(answers: Mapping[str, Any]) -> dict[str, float]:
    """Apply the feature projection merged in Scout PR #40 to Assay wire answers."""
    features: dict[str, float] = {}
    for question_id, value in answers.items():
        answer = cast(Mapping[str, Any], value)
        answer_type = answer.get("type")
        if answer_type == "noul":
            features[question_id] = float(answer["noul"])
        elif answer_type == "score":
            probabilities = cast(Mapping[str, float], answer["probabilities"])
            for level, probability in probabilities.items():
                features[f"{question_id}/{level}"] = float(probability)
        elif answer_type == "choice":
            probabilities = cast(Mapping[str, float], answer["probabilities"])
            none_keys = [key for key in probabilities if key.casefold() == "none"]
            if none_keys:
                features[question_id] = 1.0 - float(probabilities[none_keys[0]])
    return features


def _metrics(predictions: Sequence[bool], labels: Sequence[bool]) -> dict[str, Any]:
    tp = sum(prediction and label for prediction, label in zip(predictions, labels, strict=True))
    tn = sum(
        not prediction and not label
        for prediction, label in zip(predictions, labels, strict=True)
    )
    fp = sum(
        prediction and not label
        for prediction, label in zip(predictions, labels, strict=True)
    )
    fn = sum(
        not prediction and label
        for prediction, label in zip(predictions, labels, strict=True)
    )
    return {
        "accuracy": (tp + tn) / len(labels),
        "precision": tp / (tp + fp) if tp + fp else 0.0,
        "recall": tp / (tp + fn) if tp + fn else 0.0,
        "confusion": {"tp": tp, "tn": tn, "fp": fp, "fn": fn},
    }


def _mcnemar_exact(
    reference: Sequence[bool], candidate: Sequence[bool], labels: Sequence[bool]
) -> dict[str, Any]:
    reference_only = sum(
        ref == label and cand != label
        for ref, cand, label in zip(reference, candidate, labels, strict=True)
    )
    candidate_only = sum(
        ref != label and cand == label
        for ref, cand, label in zip(reference, candidate, labels, strict=True)
    )
    discordant = reference_only + candidate_only
    tail = min(reference_only, candidate_only)
    p_value = (
        1.0
        if discordant == 0
        else min(
            1.0,
            2.0
            * sum(math.comb(discordant, k) for k in range(tail + 1))
            / (2**discordant),
        )
    )
    return {
        "reference_only_correct": reference_only,
        "candidate_only_correct": candidate_only,
        "p_value": p_value,
    }


def build_fitted_report(source: Mapping[str, Any]) -> dict[str, Any]:
    """Produce grouped five-fold out-of-fold decisions without tuning on test folds."""
    cases = sorted(
        cast(list[dict[str, Any]], source["cases"]),
        key=lambda case: case["evaluation_id"],
    )
    labels = [bool(case["human_label"]) for case in cases]
    feature_keys = sorted(
        {
            key
            for case in cases
            for repeat in case["repeats"]
            for key in extract_features(repeat["answers"])
        }
    )
    splitter = StratifiedKFold(n_splits=5, shuffle=True, random_state=0)
    results: dict[int, dict[str, Any]] = {}
    for fold, (train_indexes, test_indexes) in enumerate(splitter.split(cases, labels)):
        matrix: list[list[float]] = []
        training_labels: list[int] = []
        for index in train_indexes:
            for repeat in cases[index]["repeats"]:
                features = extract_features(repeat["answers"])
                matrix.append([features.get(key, 0.0) for key in feature_keys])
                training_labels.append(int(labels[index]))
        classifier = LogisticRegression(
            l1_ratio=0.0,
            solver="liblinear",
            C=1.0,
            max_iter=1000,
            random_state=0,
        )
        classifier.fit(matrix, training_labels)
        for index in test_indexes:
            probabilities: list[float] = []
            for repeat in cases[index]["repeats"]:
                features = extract_features(repeat["answers"])
                row = [features.get(key, 0.0) for key in feature_keys]
                probabilities.append(float(classifier.predict_proba([row])[0, 1]))
            decisions = [probability >= 0.5 for probability in probabilities]
            results[index] = {
                "evaluation_id": cases[index]["evaluation_id"],
                "fold": fold,
                "human_label": labels[index],
                "production_decision": bool(cases[index]["production_decision"]),
                "repeat_probabilities": probabilities,
                "repeat_decisions": decisions,
                "fitted_decision": sum(decisions) >= 2,
            }
    ordered = [results[index] for index in range(len(cases))]
    production = [bool(case["production_decision"]) for case in cases]
    argmax = [bool(case["typesafe_decision"]) for case in cases]
    fitted = [bool(case["fitted_decision"]) for case in ordered]
    production_metrics = _metrics(production, labels)
    fitted_metrics = _metrics(fitted, labels)
    return {
        "format": "assay.typesafe-relevance-fitted-rerun/v1",
        "status": "exploratory_retrospective",
        "adoption_gate": False,
        "source_format": source["format"],
        "catalogue_version": source["catalogue_version"],
        "source_case_count": len(cases),
        "source_repeat_count": sum(len(case["repeats"]) for case in cases),
        "protocol": {
            "feature_extractor": FEATURE_EXTRACTOR,
            "fitter": FITTER,
            "sklearn_version": sklearn.__version__,
            "folds": 5,
            "fold_split": "StratifiedKFold(shuffle=True, random_state=0)",
            "grouping": "all three repeats for an evaluation stay in the same fold",
            "repeat_aggregation": "majority vote at probability >= 0.5",
            "threshold": 0.5,
            "threshold_tuned": False,
        },
        "feature_keys": feature_keys,
        "metrics": {
            "production": production_metrics,
            "typesafe_argmax": _metrics(argmax, labels),
            "typesafe_fitted_oof": fitted_metrics,
            "mcnemar_production_vs_fitted": _mcnemar_exact(production, fitted, labels),
        },
        "selection_rule": {
            "requires_accuracy_at_least_production": True,
            "requires_precision_at_least_production": True,
            "typesafe_won": (
                fitted_metrics["accuracy"] >= production_metrics["accuracy"]
                and fitted_metrics["precision"] >= production_metrics["precision"]
            ),
        },
        "cases": ordered,
    }


def canonical_bytes(document: Mapping[str, Any]) -> bytes:
    return (json.dumps(document, indent=2, sort_keys=True) + "\n").encode()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source_bytes = args.source.read_bytes()
    report = build_fitted_report(json.loads(source_bytes))
    report["source_sha256"] = hashlib.sha256(source_bytes).hexdigest()
    args.output.write_bytes(canonical_bytes(report))


if __name__ == "__main__":
    main()
