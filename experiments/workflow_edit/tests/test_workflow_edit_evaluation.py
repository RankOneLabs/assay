from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from assay.canonical import canonical_json
from assay.fixture_manifest import FixtureManifest
from assay.investigations.workflow_correctness import (
    WorkflowCorrectnessResult,
    WorkflowRunnerSettings,
    WorkflowTestGroup,
    workflow_tree_digest,
)
from assay.pier_protocol import CandidateSubmission
from assay.store import ObjectStore
from workflow_edit.evaluation import evaluate_candidate


class RecordingStore(ObjectStore):
    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.reads: list[str] = []

    def read_bytes(self, ref: Any) -> bytes:
        self.reads.append(str(ref))
        return super().read_bytes(ref)


class RecordingRunner:
    def __init__(self, image: str) -> None:
        self.settings = WorkflowRunnerSettings(image=image)
        self.received: dict[str, Any] = {}

    async def run(self, **kwargs: Any) -> WorkflowCorrectnessResult:
        self.received = kwargs
        return WorkflowCorrectnessResult("correct", ())


@pytest.mark.asyncio
async def test_evaluation_never_reads_reference_patch(tmp_path: Path) -> None:
    store = RecordingStore(tmp_path)
    baseline = {"src.ts": "export const value = 0;\n"}
    baseline_digest = workflow_tree_digest(baseline)
    image = "sha256:" + "a" * 64
    patch_ref = str(store.publish_bytes(b"candidate patch"))
    hidden = []
    for name in ("hidden_regression", "new_behavior"):
        group = WorkflowTestGroup(
            name=name, files={f"tests/{name}.js": "// test"}, command=("node", "--test")
        )
        hidden.append(str(store.publish_bytes(canonical_json(group.model_dump(mode="json")))))
    reference_ref = str(store.publish_bytes(b"operator-only reference"))
    fixture = FixtureManifest.model_construct(
        per_arm_tree_digests={"mess-00": baseline_digest},
        observed_runtime_image_digest=image,
        hidden_tests=tuple(hidden),
        reference_patch=reference_ref,
    )
    runner = RecordingRunner(image)
    result = await evaluate_candidate(
        store=store,
        fixture=fixture,
        arm_id="mess-00",
        baseline=baseline,
        submission=CandidateSubmission(
            patch_ref=patch_ref,
            tree_digest="sha256:" + "b" * 64,
            baseline_tree_digest=baseline_digest,
        ),
        visible_regression=WorkflowTestGroup(
            name="visible_regression",
            files={"tests/visible.js": "// test"},
            command=("node", "--test"),
        ),
        hidden_regression_ref=hidden[0],
        new_behavior_ref=hidden[1],
        runner=runner,  # type: ignore[arg-type]
    )
    assert result.verdict == "correct"
    assert store.reads == [hidden[0], hidden[1], patch_ref]
    assert reference_ref not in store.reads
    assert runner.received["baseline_tree_digest"] == baseline_digest
    assert runner.received["expected_tree_digest"] == "sha256:" + "b" * 64
    assert [group.name for group in runner.received["groups"]] == [
        "visible_regression",
        "hidden_regression",
        "new_behavior",
    ]
