"""Run and render the pre-registered Typesafe primary relevance comparison."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

import msgspec
from typesafe_sdk import JSONContent, Question, RetryPolicy, TypeSafeClient

from assay.investigations.relevance.catalogue import load_catalogue
from assay.investigations.relevance.mappings import DECIDE_REGISTRY
from assay.investigations.relevance.state import build_state

PROJECTS = {
    "agent-ops": {
        "key": "agent-ops",
        "name": "AgentOperations",
        "description": "all thigns agent operations",
    },
    "agent-evals": {
        "key": "agent-evals",
        "name": "AgentEvals",
        "description": "all things agent evals",
    },
}


def _read_jsonl(path: Path, project_key: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        record["_project_key"] = project_key
        records.append(record)
    return records


def _answer_payload(response: Any) -> dict[str, Any]:
    payload = msgspec.to_builtins(response)
    answers = payload["answers"]
    if not isinstance(answers, dict):
        raise ValueError("Typesafe response answers are not an object")
    return answers


def _precision(predictions: list[bool], labels: list[bool]) -> float:
    predicted_positive = sum(predictions)
    if predicted_positive == 0:
        return 0.0
    return (
        sum(p and y for p, y in zip(predictions, labels, strict=True)) / predicted_positive
    )


def _mcnemar_exact(
    reference: list[bool], candidate: list[bool], labels: list[bool]
) -> dict[str, Any]:
    ref_only = sum(r == y and c != y for r, c, y in zip(reference, candidate, labels, strict=True))
    cand_only = sum(r != y and c == y for r, c, y in zip(reference, candidate, labels, strict=True))
    discordant = ref_only + cand_only
    tail = min(ref_only, cand_only)
    p = (
        1.0
        if discordant == 0
        else min(
            1.0,
            2.0
            * sum(math.comb(discordant, k) for k in range(tail + 1))
            / (2**discordant),
        )
    )
    return {"reference_only_correct": ref_only, "candidate_only_correct": cand_only, "p_value": p}


def run(args: argparse.Namespace) -> None:
    catalogue = load_catalogue(args.catalogue)
    decide = DECIDE_REGISTRY[catalogue.decide]
    records = _read_jsonl(args.agent_ops, "agent-ops") + _read_jsonl(
        args.agent_evals, "agent-evals"
    )
    records.sort(key=lambda record: int(record["evaluation_id"]))
    if len(records) != 79 or len({record["evaluation_id"] for record in records}) != 79:
        raise ValueError("primary population must contain 79 distinct evaluations")

    output_path: Path = args.output
    existing: dict[str, Any] = {}
    if output_path.exists():
        prior = json.loads(output_path.read_text(encoding="utf-8"))
        existing = {
            f"{case['evaluation_id']}:{repeat['repeat_index']}": repeat
            for case in prior.get("cases", [])
            for repeat in case.get("repeats", [])
        }

    case_results: list[dict[str, Any]] = []
    retry = RetryPolicy(max_retries=0)
    with TypeSafeClient(
        api_key=os.environ["TYPESAFE_API_KEY"],
        model="jev-latest",
        retry=retry,
        timeout=60.0,
    ) as client:
        for record in records:
            repeats: list[dict[str, Any]] = []
            for repeat_index in range(1, 4):
                key = f"{record['evaluation_id']}:{repeat_index}"
                if key in existing:
                    repeats.append(existing[key])
                    continue
                started = time.monotonic()
                response = client.system_one(
                    state=cast(
                        JSONContent,
                        build_state(record, PROJECTS[record["_project_key"]]),
                    ),
                    questions=cast(Mapping[str, Question], catalogue.questions),
                )
                answers = _answer_payload(response)
                decision = decide(answers)
                repeats.append(
                    {
                        "repeat_index": repeat_index,
                        "request_id": response.request_id,
                        "model": response.model,
                        "latency_ms": round((time.monotonic() - started) * 1000),
                        "usage": msgspec.to_builtins(response.usage),
                        "answers": answers,
                        "decision": decision,
                    }
                )
                partial_cases = case_results + [
                    {
                        "evaluation_id": record["evaluation_id"],
                        "human_label": record["human_label"],
                        "production_score": record["production_score"],
                        "production_decision": record["production_decision"],
                        "repeats": repeats,
                    }
                ]
                output_path.write_text(
                    json.dumps({"cases": partial_cases}, sort_keys=True, indent=2) + "\n",
                    encoding="utf-8",
                )
            votes = [bool(repeat["decision"]["eligible"]) for repeat in repeats]
            case_results.append(
                {
                    "evaluation_id": record["evaluation_id"],
                    "human_label": record["human_label"],
                    "production_score": record["production_score"],
                    "production_decision": record["production_decision"],
                    "typesafe_decision": sum(votes) >= 2,
                    "repeats": repeats,
                }
            )
            output_path.write_text(
                json.dumps({"cases": case_results}, sort_keys=True, indent=2) + "\n",
                encoding="utf-8",
            )

    labels = [bool(case["human_label"]) for case in case_results]
    production = [bool(case["production_decision"]) for case in case_results]
    typesafe = [bool(case["typesafe_decision"]) for case in case_results]
    production_accuracy = sum(a == b for a, b in zip(production, labels, strict=True)) / len(labels)
    typesafe_accuracy = sum(a == b for a, b in zip(typesafe, labels, strict=True)) / len(labels)
    production_precision = _precision(production, labels)
    typesafe_precision = _precision(typesafe, labels)
    won = typesafe_accuracy >= production_accuracy and typesafe_precision >= production_precision
    document = {
        "format": "assay.typesafe-relevance-primary/v1",
        "catalogue_version": catalogue.version,
        "catalogue_sha256": hashlib.sha256(Path(args.catalogue).read_bytes()).hexdigest(),
        "population_sha256": hashlib.sha256(Path(args.population).read_bytes()).hexdigest(),
        "model": "jev-latest",
        "sdk_version": "0.6.0",
        "repeat_count": 3,
        "reference": "recorded production decision from the frozen evaluation",
        "protocol_deviation": (
            "The production reference was not rerun; its frozen recorded decision is used "
            "for all three paired candidate repeats."
        ),
        "metrics": {
            "production": {"accuracy": production_accuracy, "precision": production_precision},
            "typesafe": {"accuracy": typesafe_accuracy, "precision": typesafe_precision},
            "mcnemar": _mcnemar_exact(production, typesafe, labels),
        },
        "typesafe_won": won,
        "cases": case_results,
    }
    output_path.write_text(json.dumps(document, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalogue", type=Path, required=True)
    parser.add_argument("--agent-ops", type=Path, required=True)
    parser.add_argument("--agent-evals", type=Path, required=True)
    parser.add_argument("--population", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args())


if __name__ == "__main__":
    main()
