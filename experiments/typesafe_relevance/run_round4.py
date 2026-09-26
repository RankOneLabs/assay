"""Run ``jev:v4`` and ``llm:v4`` on the round 4 packet's posts, then ``route()``.

Both arms answer the one feature catalogue, and ``route()`` makes both decisions,
so the arms differ only in the answering model. ``llm:v4`` is production's
relevance model as deployed (``RELEVANCE_MODEL=openrouter/google/gemini-2.5-flash``
on willie, 2026-09-23).

Cells are keyed by arm and evaluation id and written after every call, so a rerun
resumes and never pays twice for a completed cell. ``--dry-run`` spends nothing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
from typing import Any

from typesafe_relevance.backends import (
    Backend,
    BackendError,
    OpenRouterBackend,
    TypesafeBackend,
)
from typesafe_relevance.catalogue import Catalogue, check_dispatchable, load_catalogue
from typesafe_relevance.route import route
from typesafe_relevance.run_arms import PROJECTS
from typesafe_relevance.state import build_state

LLM_MODEL = "google/gemini-2.5-flash"

#: The ``v5`` arms are the same backends answering the v5 catalogue; the arm name
#: records which catalogue a cell came from, one catalogue per output file.
ARMS: dict[str, Backend] = {
    "jev:v4": TypesafeBackend(arm="jev:v4"),
    "llm:v4": OpenRouterBackend(arm="llm:v4", model=LLM_MODEL),
    "jev:v5": TypesafeBackend(arm="jev:v5"),
    "llm:v5": OpenRouterBackend(arm="llm:v5", model=LLM_MODEL),
}


def read_cases(key_path: Path, populations: dict[str, Path]) -> list[dict[str, Any]]:
    """The packet's posts, from its private key and the exports it was built from."""
    key = json.loads(key_path.read_text(encoding="utf-8"))
    records: dict[int, dict[str, Any]] = {}
    for path in populations.values():
        for line in path.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            records[int(record["evaluation_id"])] = record
    return [
        {**records[int(case["evaluation_id"])], "_project_key": case["project_key"]}
        for case in key["cases"]
    ]


def _write(
    path: Path, catalogue: Catalogue, cells: dict[str, dict[str, Any]], failures: list[Any]
) -> None:
    document = {
        "format": "assay.relevance-round4-arms/v1",
        "catalogue": {
            "id": catalogue.id,
            "version": catalogue.version,
            "file_sha256": hashlib.sha256(catalogue.path.read_bytes()).hexdigest(),
        },
        "arms": {
            arm: {"model": "jev-latest" if arm.startswith("jev") else LLM_MODEL}
            for arm in sorted({cell["arm"] for cell in cells.values()})
        },
        "cells": cells,
        "failures": failures,
    }
    path.write_text(json.dumps(document, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> None:
    catalogue = load_catalogue(args.catalogue)
    cases = read_cases(
        args.key, {"agent-ops": args.agent_ops, "agent-evals": args.agent_evals}
    )
    output: Path = args.output
    cells: dict[str, dict[str, Any]] = {}
    if output.exists():
        prior = json.loads(output.read_text(encoding="utf-8"))
        if prior["catalogue"]["version"] != catalogue.version:
            raise SystemExit(
                f"{output} was run with catalogue version {prior['catalogue']['version']}, "
                f"not {catalogue.version}; write to a new output"
            )
        cells = prior["cells"]
    pending = [
        (arm, record)
        for arm in args.arms
        for record in cases
        if f"{arm}:{record['evaluation_id']}" not in cells
    ]
    if pending:
        check_dispatchable(catalogue.questions)
    print(f"catalogue {catalogue.id} version {catalogue.version}")
    print(f"cases {len(cases)}, arms {', '.join(args.arms)}, to dispatch {len(pending)}")
    for arm in {arm for arm, _ in pending}:
        ARMS[arm].check_ready()
    if args.dry_run:
        print("dry run: nothing dispatched")
        return

    failures: list[dict[str, Any]] = []
    for index, (arm, record) in enumerate(pending, start=1):
        evaluation_id = int(record["evaluation_id"])
        state = build_state(record, PROJECTS[record["_project_key"]])
        try:
            answer = ARMS[arm](state, catalogue.questions, evaluation_id)
            decision = route(answer.answers)
        except (BackendError, ValueError) as error:
            failures.append({"arm": arm, "evaluation_id": evaluation_id, "detail": str(error)})
            print(f"  [{index}/{len(pending)}] FAIL {arm} {evaluation_id}: {error}")
            continue
        cells[f"{arm}:{evaluation_id}"] = {
            "arm": arm,
            "evaluation_id": evaluation_id,
            "request_id": answer.request_id,
            "model": answer.model,
            "latency_ms": answer.latency_ms,
            "usage": answer.usage,
            "answers": answer.answers,
            "route": decision,
        }
        _write(output, catalogue, cells, failures)
        if index % 10 == 0 or index == len(pending):
            print(f"  [{index}/{len(pending)}] {arm} {evaluation_id}")
        time.sleep(args.delay)
    _write(output, catalogue, cells, failures)
    print(f"{len(pending) - len(failures)} cells written, {len(failures)} failures -> {output}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalogue", type=Path, required=True)
    parser.add_argument(
        "--key", type=Path, required=True, help="the packet's answer-key-private.json"
    )
    parser.add_argument("--agent-ops", type=Path, required=True)
    parser.add_argument("--agent-evals", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--arms", nargs="+", choices=sorted(ARMS), default=sorted(ARMS))
    parser.add_argument("--delay", type=float, default=0.2)
    parser.add_argument("--dry-run", action="store_true")
    run(parser.parse_args())


if __name__ == "__main__":
    main()
