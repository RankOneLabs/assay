"""Run the relevance catalogue across backends and catalogue versions.

This answers two questions the primary report could not, because it had a single
arm and therefore no control:

1. Is the 62% primary result Jev, or is it the questions?  ``jev:v1`` against
   ``gemini:v1`` holds the questions fixed and swaps the answering model — and
   Gemini 2.5 Flash is production's own model, so the comparison with the frozen
   production decision is same-model, different-schema.
2. Do better-written criteria help?  ``*:v1`` against ``*:v2`` holds the model
   fixed and swaps only the criteria text. v2 has identical question ids, types
   and answer domains, so nothing but wording differs.

``jev:v1`` is not re-run: the 237 stored answers from the primary run are reused,
so that arm costs nothing and stays byte-identical to the published report.

Every cell is resumable. A completed cell is keyed by arm, evaluation and repeat
and is never re-paid for. ``--max-calls`` is a hard ceiling checked before each
request; ``--dry-run`` reports the plan and spends nothing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from typesafe_relevance.backends import (
    Backend,
    BackendError,
    OpenRouterBackend,
    TypesafeBackend,
)
from typesafe_relevance.catalogue import Catalogue, load_catalogue
from typesafe_relevance.mappings import DECIDE_REGISTRY
from typesafe_relevance.state import build_state

PROJECTS: dict[str, dict[str, str]] = {
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

REPEATS = 3


@dataclass(frozen=True, slots=True)
class Arm:
    """One (backend, catalogue) cell of the grid."""

    arm_id: str
    catalogue_key: str
    backend: Backend | None
    """None means the arm is reused from a prior run and never dispatches."""


def build_arms(selected: Sequence[str]) -> list[Arm]:
    available = {
        "jev:v1": Arm("jev:v1", "v1", None),
        "jev:v2": Arm("jev:v2", "v2", TypesafeBackend(arm="jev:v2")),
        "gemini:v1": Arm(
            "gemini:v1", "v1", OpenRouterBackend(arm="gemini:v1", model="google/gemini-2.5-flash")
        ),
        "gemini:v2": Arm(
            "gemini:v2", "v2", OpenRouterBackend(arm="gemini:v2", model="google/gemini-2.5-flash")
        ),
        "haiku:v2": Arm(
            "haiku:v2", "v2", OpenRouterBackend(arm="haiku:v2", model="anthropic/claude-haiku-4.5")
        ),
    }
    unknown = [name for name in selected if name not in available]
    if unknown:
        raise ValueError(f"unknown arms: {unknown}; known: {sorted(available)}")
    return [available[name] for name in selected]


def read_population(agent_ops: Path, agent_evals: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path, project_key in ((agent_ops, "agent-ops"), (agent_evals, "agent-evals")):
        for line in path.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            record["_project_key"] = project_key
            records.append(record)
    records.sort(key=lambda record: int(record["evaluation_id"]))
    if len(records) != 79 or len({record["evaluation_id"] for record in records}) != 79:
        raise ValueError("population must contain 79 distinct evaluations")
    return records


def load_prior_cells(paths: Sequence[Path]) -> dict[str, dict[str, Any]]:
    """Index every completed cell from prior outputs, keyed arm:evaluation:repeat."""
    cells: dict[str, dict[str, Any]] = {}
    for path in paths:
        if not path.exists():
            continue
        document = json.loads(path.read_text(encoding="utf-8"))
        for case in document.get("cases", []):
            evaluation_id = case["evaluation_id"]
            # The primary report's shape: one implicit jev:v1 arm.
            for repeat in case.get("repeats", []):
                cells[f"jev:v1:{evaluation_id}:{repeat['repeat_index']}"] = repeat
            for arm_id, arm_case in (case.get("arms") or {}).items():
                for repeat in arm_case.get("repeats", []):
                    cells[f"{arm_id}:{evaluation_id}:{repeat['repeat_index']}"] = repeat
    return cells


def _precision(predictions: Sequence[bool], labels: Sequence[bool]) -> float:
    positive = sum(predictions)
    if positive == 0:
        return 0.0
    return sum(p and y for p, y in zip(predictions, labels, strict=True)) / positive


def _recall(predictions: Sequence[bool], labels: Sequence[bool]) -> float:
    actual = sum(labels)
    if actual == 0:
        return 0.0
    return sum(p and y for p, y in zip(predictions, labels, strict=True)) / actual


def _mcnemar_exact(
    reference: Sequence[bool], candidate: Sequence[bool], labels: Sequence[bool]
) -> dict[str, Any]:
    ref_only = sum(r == y and c != y for r, c, y in zip(reference, candidate, labels, strict=True))
    cand_only = sum(r != y and c == y for r, c, y in zip(reference, candidate, labels, strict=True))
    discordant = ref_only + cand_only
    tail = min(ref_only, cand_only)
    p_value = (
        1.0
        if discordant == 0
        else min(
            1.0,
            2.0 * sum(math.comb(discordant, k) for k in range(tail + 1)) / (2**discordant),
        )
    )
    return {
        "reference_only_correct": ref_only,
        "candidate_only_correct": cand_only,
        "p_value": p_value,
    }


def score_arm(
    predictions: Sequence[bool], labels: Sequence[bool], production: Sequence[bool]
) -> dict[str, Any]:
    accuracy = sum(p == y for p, y in zip(predictions, labels, strict=True)) / len(labels)
    return {
        "accuracy": accuracy,
        "precision": _precision(predictions, labels),
        "recall": _recall(predictions, labels),
        "mcnemar_vs_production": _mcnemar_exact(production, predictions, labels),
    }


@dataclass(slots=True)
class Budget:
    """Hard ceiling on dispatched calls, checked before every request."""

    limit: int
    spent: int = 0

    def take(self) -> None:
        if self.spent >= self.limit:
            raise RuntimeError(f"call budget of {self.limit} exhausted; stopping before dispatch")
        self.spent += 1


def run(args: argparse.Namespace) -> None:
    catalogues: dict[str, Catalogue] = {
        "v1": load_catalogue(args.catalogue_v1),
        "v2": load_catalogue(args.catalogue_v2),
    }
    arms = build_arms(args.arms)
    records = read_population(args.agent_ops, args.agent_evals)
    if args.limit_cases is not None:
        records = records[: args.limit_cases]
        print(f"SMOKE: restricted to the first {len(records)} evaluations; not a scoreable run")
    prior = load_prior_cells([args.output, *args.reuse])

    pending = [
        (arm, record, repeat)
        for arm in arms
        for record in records
        for repeat in range(1, REPEATS + 1)
        if f"{arm.arm_id}:{record['evaluation_id']}:{repeat}" not in prior
    ]
    missing_reuse = [
        f"{arm.arm_id}:{record['evaluation_id']}:{repeat}"
        for arm, record, repeat in pending
        if arm.backend is None
    ]
    if missing_reuse:
        raise ValueError(
            f"{len(missing_reuse)} reuse-only cells are absent from prior outputs; "
            f"first: {missing_reuse[0]}"
        )

    print(f"arms: {', '.join(arm.arm_id for arm in arms)}")
    print(f"cells total: {len(arms) * len(records) * REPEATS}")
    print(f"cells already complete: {len(arms) * len(records) * REPEATS - len(pending)}")
    print(f"cells to dispatch: {len(pending)}  (budget {args.max_calls})")
    for key, catalogue in catalogues.items():
        print(f"catalogue {key}: version {catalogue.version}")
    dispatching = {arm.arm_id for arm, _, _ in pending}
    for arm in arms:
        if arm.backend is not None and arm.arm_id in dispatching:
            arm.backend.check_ready()
    print(f"preflight ok for: {', '.join(sorted(dispatching)) or 'nothing to dispatch'}")
    if args.dry_run:
        print("dry run: nothing dispatched")
        return
    if len(pending) > args.max_calls:
        raise RuntimeError(
            f"{len(pending)} cells exceed the --max-calls ceiling of {args.max_calls}"
        )

    budget = Budget(limit=args.max_calls)
    results: dict[str, dict[str, Any]] = dict(prior)
    failures: list[dict[str, Any]] = []
    output_path: Path = args.output

    for index, (arm, record, repeat) in enumerate(pending, start=1):
        evaluation_id = int(record["evaluation_id"])
        catalogue = catalogues[arm.catalogue_key]
        state = build_state(record, PROJECTS[record["_project_key"]])
        assert arm.backend is not None  # reuse-only arms were rejected above
        budget.take()
        try:
            answer = arm.backend(state, catalogue.questions, evaluation_id)
        except BackendError as error:
            failures.append(
                {"arm": arm.arm_id, "evaluation_id": evaluation_id, "repeat": repeat,
                 "detail": error.detail}
            )
            print(f"  [{index}/{len(pending)}] FAIL {arm.arm_id} {evaluation_id}: {error.detail}")
            continue
        results[f"{arm.arm_id}:{evaluation_id}:{repeat}"] = {
            "repeat_index": repeat,
            "request_id": answer.request_id,
            "model": answer.model,
            "latency_ms": answer.latency_ms,
            "usage": answer.usage,
            "answers": answer.answers,
            "decision": DECIDE_REGISTRY[catalogue.decide](answer.answers),
        }
        if index % 10 == 0 or index == len(pending):
            print(f"  [{index}/{len(pending)}] {arm.arm_id} evaluation {evaluation_id}")
            _write(output_path, catalogues, arms, records, results, failures, partial=True)
        time.sleep(args.delay)

    _write(output_path, catalogues, arms, records, results, failures, partial=False)
    print(f"dispatched {budget.spent} calls, {len(failures)} failures")
    print(f"wrote {output_path}")


def _write(
    path: Path,
    catalogues: Mapping[str, Catalogue],
    arms: Sequence[Arm],
    records: Sequence[Mapping[str, Any]],
    results: Mapping[str, dict[str, Any]],
    failures: Sequence[Mapping[str, Any]],
    *,
    partial: bool,
) -> None:
    cases: list[dict[str, Any]] = []
    for record in records:
        evaluation_id = int(record["evaluation_id"])
        arm_cases: dict[str, Any] = {}
        for arm in arms:
            repeats = [
                results[key]
                for repeat in range(1, REPEATS + 1)
                if (key := f"{arm.arm_id}:{evaluation_id}:{repeat}") in results
            ]
            if not repeats:
                continue
            votes = [bool(repeat["decision"]["eligible"]) for repeat in repeats]
            arm_cases[arm.arm_id] = {
                "repeats": repeats,
                "decision": sum(votes) * 2 >= len(votes) + 1,
                "complete": len(repeats) == REPEATS,
            }
        cases.append(
            {
                "evaluation_id": evaluation_id,
                "human_label": record["human_label"],
                "production_score": record["production_score"],
                "production_decision": record["production_decision"],
                "arms": arm_cases,
            }
        )

    labels = [bool(case["human_label"]) for case in cases]
    production = [bool(case["production_decision"]) for case in cases]
    metrics: dict[str, Any] = {
        "production": {
            "accuracy": sum(p == y for p, y in zip(production, labels, strict=True)) / len(labels),
            "precision": _precision(production, labels),
            "recall": _recall(production, labels),
        }
    }
    for arm in arms:
        complete = [case for case in cases if case["arms"].get(arm.arm_id, {}).get("complete")]
        if len(complete) != len(cases):
            metrics[arm.arm_id] = {"incomplete_cases": len(cases) - len(complete)}
            continue
        predictions = [bool(case["arms"][arm.arm_id]["decision"]) for case in complete]
        metrics[arm.arm_id] = score_arm(predictions, labels, production)

    document = {
        "format": "assay.relevance-arms/v1",
        "partial": partial,
        "repeat_count": REPEATS,
        "reference": "recorded production decision from the frozen evaluation",
        "arms": {
            arm.arm_id: {
                "catalogue": arm.catalogue_key,
                "catalogue_version": catalogues[arm.catalogue_key].version,
                "reused": arm.backend is None,
            }
            for arm in arms
        },
        "catalogues": {
            key: {
                "version": catalogue.version,
                "file_sha256": hashlib.sha256(catalogue.path.read_bytes()).hexdigest(),
            }
            for key, catalogue in catalogues.items()
        },
        "metrics": metrics,
        "failures": list(failures),
        "cases": cases,
    }
    path.write_text(json.dumps(document, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalogue-v1", type=Path, required=True)
    parser.add_argument("--catalogue-v2", type=Path, required=True)
    parser.add_argument("--agent-ops", type=Path, required=True)
    parser.add_argument("--agent-evals", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--reuse", type=Path, nargs="*", default=[],
        help="prior output files whose completed cells are reused instead of re-paid",
    )
    parser.add_argument("--arms", nargs="+", required=True)
    parser.add_argument("--max-calls", type=int, required=True)
    parser.add_argument(
        "--limit-cases", type=int, default=None,
        help="smoke only: restrict to the first N evaluations; output is not scoreable",
    )
    parser.add_argument("--delay", type=float, default=0.2)
    parser.add_argument("--dry-run", action="store_true")
    run(parser.parse_args())


if __name__ == "__main__":
    main()
