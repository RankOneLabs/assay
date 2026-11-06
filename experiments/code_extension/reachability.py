"""Read the reachability split from a plan's retained evaluator output."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Literal

from assay.models import ExecutionOutcome, RunManifest
from assay.store import ObjectStore
from code_extension.config import RunConfiguration
from code_extension.diagnose import _FAIL
from code_extension.ledger import _evaluation_detail, _Output, _stop, _verdict
from code_extension.metrics import artifact_bytes
from code_extension.run import _plan_dir
from code_extension.status import ROUTE_PROBE, _manifest

type FeatureFailure = Literal["reachability", "omitted_stage", "semantic", "unattributed"]

_PASSED_REACHABILITY = re.compile(r"^\(pass\) reachability: ", re.MULTILINE)


def feature_failure(output: str, *, group_failed: bool) -> FeatureFailure | None:
    """Reachability wins, because an unreachable stage fails semantics too.

    A group can fail with no title at all when a test module throws on load, and
    that still needs review, so the group status decides there and not the output.
    """
    failed = _FAIL.findall(output)
    if any(title.startswith("reachability: ") for title in failed):
        return "reachability"
    if any(title.startswith("semantics: ") for title in failed) and _PASSED_REACHABILITY.search(
        output
    ):
        return "semantic"
    return "unattributed" if failed or group_failed else None


def _spelling(text: str) -> str:
    return text.replace("_", "").replace("-", "").lower()


def adds_stage_code(patch: str, stage: str) -> bool:
    """Whether the patch adds a line naming the stage outside the test tree.

    Any spelling counts, because a compiler written but never registered says
    `statusReportStageTypeCompiler` and only the registration says `status_report`.
    """
    name = _spelling(stage)
    path = ""
    for line in patch.splitlines():
        if line.startswith("+++ "):
            path = line.removeprefix("+++ ").removeprefix("b/")
        elif line.startswith("+") and name in _spelling(line) and not path.startswith("tests/"):
            return True
    return False


def stage_type(cell: str) -> str:
    """`oakridge-dbos-stage-status-report:plugin:w0` names the type `status_report`."""
    return cell.split(":")[0].removeprefix("oakridge-dbos-stage-").replace("-", "_")


def claimed_cells(records: list[dict[str, Any]]) -> list[str]:
    """Only a claim is a dispatch: a halted manifest also holds refused cells."""
    return [
        r["coordinate"] for r in records
        if r["event"] == "attempt_started" and r["coordinate"] != ROUTE_PROBE
    ]


def settled_cells(records: list[dict[str, Any]]) -> set[str]:
    """A manifest speaks only for claims made before it was written."""
    written = max(
        (index for index, r in enumerate(records) if r["event"] == "run_manifest"),
        default=0,
    )
    return set(claimed_cells(records[:written]))


def request_counts(records: list[dict[str, Any]]) -> Counter[str]:
    """A request refused by the attempt budget was reserved but never sent."""
    unsent = {
        r["attempt_id"] for r in records
        if r["event"] == "finished" and r.get("status") == "not_sent"
    }
    return Counter(
        r["coordinate"] for r in records
        if r["event"] == "reserved" and r["attempt_id"] not in unsent
    )


def _settled_row(
    cell: str, reference: str, store: ObjectStore, manifest: RunManifest,
) -> dict[str, Any]:
    outcome = ExecutionOutcome.model_validate_json(store.read_bytes(reference))
    stop = _stop(outcome, store)
    verdict = _verdict(cell, manifest, store)
    detail, _ = _evaluation_detail(cell, manifest, store)
    failure: FeatureFailure | None = None
    if detail is not None:
        record = json.loads(store.read_bytes(detail.evaluator_record_ref))
        group = record["groups"]["new_behavior"]
        failure = feature_failure(
            f"{group['stdout']}\n{group['stderr']}",
            group_failed=detail.groups["new_behavior"].status == "failed",
        )
    if failure == "reachability" and outcome.output_ref is not None:
        output = _Output.model_validate_json(store.read_bytes(outcome.output_ref))
        patch = artifact_bytes(store, output.patch_ref).decode("utf-8")
        if not adds_stage_code(patch, stage_type(cell)):
            failure = "omitted_stage"
    return {
        "stop": getattr(stop, "cause", stop.kind),
        "verdict": verdict.value if verdict else None,
        "feature_failure": failure,
    }


def plan_rows(store_path: Path, plan_digest: str) -> list[dict[str, Any]]:
    """One row per dispatched attempt; a claim with no retained outcome is unsettled."""
    store = ObjectStore(store_path)
    directory = _plan_dir(store, plan_digest)
    config = RunConfiguration.load(directory / "config.json")
    journal = (directory / "attempts.jsonl").read_text(encoding="utf-8").splitlines()
    records = [json.loads(line) for line in journal]
    found = _manifest(store, config, records)
    settled = settled_cells(records)
    requests = request_counts(records)
    rows = []
    for cell in claimed_cells(records):
        row: dict[str, Any] = {"stop": "unsettled", "verdict": None, "feature_failure": None}
        if found is not None and cell in settled and cell in found[1].execution_records:
            row = _settled_row(cell, found[1].execution_records[cell], store, found[1])
        rows.append({"cell": cell, "requests": requests[cell], **row})
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
