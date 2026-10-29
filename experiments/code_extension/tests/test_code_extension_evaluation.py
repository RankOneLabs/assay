"""Cell evaluation uses the coordinate, realization and worker evidence independently."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import pytest
from code_extension.dispatch import cell_idempotency_key
from code_extension.evaluation import CellEvaluator, evaluate_scenario_candidate
from code_extension.study import load_pilot_study_fixture
from workflow_edit.bridge import turn_idempotency_key

from assay.canonical import canonical_json
from assay.investigations.workflow_correctness import (
    GroupResult,
    WorkflowCorrectnessResult,
    WorkflowRunnerSettings,
    WorkflowTestGroup,
    workflow_tree_digest,
)
from assay.models import CellCoordinate, EvaluationCoordinate
from assay.pier_protocol import CandidateSubmission
from assay.store import ObjectStore


class RecordingRunner:
    def __init__(self, image: str) -> None:
        self.settings = WorkflowRunnerSettings(image=image, toolchain="bun")
        self.calls: list[dict[str, Any]] = []

    def configuration(self) -> dict[str, str]:
        return {"image": self.settings.image}

    async def run(self, **kwargs: Any) -> WorkflowCorrectnessResult:
        self.calls.append(kwargs)
        return WorkflowCorrectnessResult(
            "incorrect",
            tuple(
                GroupResult(
                    group.name, "failed" if group.name == "visible_regression" else "passed"
                )
                for group in kwargs["groups"]
            ),
            "group_failure",
        )


def _envelope(store: ObjectStore, path: str, content: bytes) -> str:
    return str(store.publish_json({
        "schema_version": "assay-pier-raw-artifact/0.1.0",
        "path": path,
        "byte_length": len(content),
        "content_base64": base64.b64encode(content).decode("ascii"),
    }))


@pytest.mark.asyncio
async def test_worker_baseline_mismatch_is_named_unavailable(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path / "store")
    fixture = load_pilot_study_fixture(store)
    scenario = fixture.scenarios[0]
    manifest = fixture.manifest
    baseline = scenario.realizations["baseline"]
    runner = RecordingRunner(manifest.observed_runtime_image_digest)
    coordinate = CellCoordinate(
        subject_id=scenario.subject_id, arm_id="baseline", worker_repeat=0,
        realization_ref=str(store.publish_json({"repository": baseline})),
    )
    output = {
        "cell_id": coordinate.id,
        "patch_ref": _envelope(store, "candidate.patch", b""),
        "tree_digest_ref": _envelope(
            store, "tree_digest", workflow_tree_digest(baseline).encode("ascii")
        ),
        "result_ref": _envelope(store, "result.json", canonical_json({
            "baseline_tree_digest": "sha256:" + "f" * 64,
        })),
    }
    evaluator = CellEvaluator(store, manifest, runner)  # type: ignore[arg-type]
    result = await evaluator.evaluate(
        input_value={"repository": baseline}, output=output,
        coordinate=EvaluationCoordinate(cell_id=coordinate.id, evaluator_id="correctness",
                                        evaluator_repeat=0),
    )
    assert result.verdict == "unavailable"
    record = evaluator.records[coordinate.id]
    assert record["cause"] == "baseline_digest_mismatch"
    assert all(
        group["cause"] == "baseline_digest_mismatch"
        for group in record["groups"].values()  # type: ignore[union-attr]
    )
    assert runner.calls == []


@pytest.mark.asyncio
async def test_candidate_visible_test_edit_and_addition_use_frozen_group(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path / "store")
    fixture = load_pilot_study_fixture(store)
    scenario = fixture.scenarios[0]
    manifest = fixture.manifest
    baseline = scenario.realizations["baseline"]
    visible_ref = manifest.scenarios[0].visible_tests[0].digest
    frozen = WorkflowTestGroup.model_validate_json(store.read_bytes(visible_ref))
    path = sorted(frozen.files)[0]
    patch = (
        f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n"
        "@@ -1 +1 @@\n-// original\n+// weakened\n"
        "diff --git a/tests/visible/added.test.ts b/tests/visible/added.test.ts\n"
        "new file mode 100644\n--- /dev/null\n+++ b/tests/visible/added.test.ts\n"
        "@@ -0,0 +1 @@\n+// added\n"
    )
    runner = RecordingRunner(manifest.observed_runtime_image_digest)
    result = await evaluate_scenario_candidate(
        store=store, manifest=manifest, subject_id=scenario.subject_id, arm_id="baseline",
        baseline=baseline,
        submission=CandidateSubmission(
            patch_ref=str(store.publish_bytes(patch.encode())),
            tree_digest="sha256:" + "d" * 64,
            baseline_tree_digest=workflow_tree_digest(baseline),
        ),
        runner=runner,  # type: ignore[arg-type]
    )
    assert result.verdict == "incorrect"
    assert len(runner.calls) == 1
    received = runner.calls[0]
    assert received["patch"] == patch
    assert received["baseline"] == baseline
    groups = received["groups"]
    assert groups[0].restores and groups[0].files == frozen.files
    assert "tests/visible/added.test.ts" not in groups[0].files
    assert [group.name for group in groups] == [
        "visible_regression", "hidden_regression", "new_behavior"
    ]


def test_dispatch_key_reuses_a_job_per_run_cell_and_turn(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path / "store")
    fixture = load_pilot_study_fixture(store)
    coordinate = CellCoordinate(
        subject_id=fixture.scenarios[0].subject_id, arm_id="baseline", worker_repeat=0,
        realization_ref="sha256:" + "a" * 64,
    )
    next_repeat = coordinate.model_copy(update={"worker_repeat": 1})
    key = cell_idempotency_key("run-one", coordinate)
    assert key == cell_idempotency_key("run-one", coordinate)
    assert turn_idempotency_key(key, 1) == turn_idempotency_key(
        cell_idempotency_key("run-one", coordinate), 1
    )
    assert key != cell_idempotency_key("run-two", coordinate)
    assert key != cell_idempotency_key("run-one", next_repeat)
    assert turn_idempotency_key(key, 1) != turn_idempotency_key(key, 2)
