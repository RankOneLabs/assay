"""Read the reachability split from a plan's retained evaluator output."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any, Literal

from assay.models import ExecutionOutcome
from assay.store import ObjectStore
from code_extension.config import RunConfiguration
from code_extension.diagnose import _FAIL
from code_extension.ledger import _evaluation_detail, _stop, _verdict
from code_extension.run import _plan_dir
from code_extension.status import _manifest

type FeatureFailure = Literal["reachability", "semantic", "unattributed"]


def feature_failure(output: str) -> FeatureFailure | None:
    """Reachability wins over semantics, because an unreachable stage fails both."""
    failed = _FAIL.findall(output)
    if any(title.startswith("reachability: ") for title in failed):
        return "reachability"
    if any(title.startswith("semantics: ") for title in failed):
        return "semantic"
    return "unattributed" if failed else None


def plan_rows(store_path: Path, plan_digest: str) -> list[dict[str, Any]]:
    """One row per dispatched attempt; ungraded attempts keep a null feature failure."""
    store = ObjectStore(store_path)
    directory = _plan_dir(store, plan_digest)
    config = RunConfiguration.load(directory / "config.json")
    journal = (directory / "attempts.jsonl").read_text(encoding="utf-8").splitlines()
    records = [json.loads(line) for line in journal]
    requests = Counter(r["coordinate"] for r in records if r["event"] == "reserved")
    found = _manifest(store, config, records)
    if found is None:
        raise ValueError(f"no run manifest for {plan_digest}")
    _, manifest = found
    rows = []
    for cell, reference in manifest.execution_records.items():
        outcome = ExecutionOutcome.model_validate_json(store.read_bytes(reference))
        stop = _stop(outcome, store)
        verdict = _verdict(cell, manifest, store)
        detail, _ = _evaluation_detail(cell, manifest, store)
        failure = None
        if detail is not None:
            record = json.loads(store.read_bytes(detail.evaluator_record_ref))
            group = record["groups"]["new_behavior"]
            failure = feature_failure(f"{group['stdout']}\n{group['stderr']}")
        rows.append({
            "cell": cell,
            "stop": getattr(stop, "cause", stop.kind),
            "requests": requests[cell],
            "verdict": verdict.value if verdict else None,
            "feature_failure": failure,
        })
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(prog="code_extension.reachability")
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--plan", required=True)
    args = parser.parse_args()
    for row in plan_rows(args.store, args.plan):
        print(json.dumps(row, sort_keys=True))


if __name__ == "__main__":
    main()
