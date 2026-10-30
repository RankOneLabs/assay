"""Cell evaluation uses the coordinate, realization and worker evidence independently."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import pytest
from code_extension import bridge
from code_extension.classification import (
    EvaluatorVerdict,
    GroupVerdict,
    NeedsOperatorJudgment,
    Submitted,
    classify,
)
from code_extension.dispatch import cell_idempotency_key
from code_extension.evaluation import (
    CellEvaluator,
    evaluate_scenario_candidate,
    grader_cache_key,
)
from code_extension.study import load_pilot_study_fixture
from workflow_edit.bridge import turn_idempotency_key

from assay.canonical import canonical_json
from assay.investigations.workflow_correctness import (
    GroupResult,
    PreflightResult,
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
    assert bridge.cell_idempotency_key is cell_idempotency_key
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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("case", "verdict", "preflight_status", "cause", "attribution", "statuses"),
    [
        ("correct", "correct", "passed", None, None, ("passed",) * 3),
        ("wrong", "incorrect", "passed", "group_failure", "candidate_failure",
         ("failed", "passed", "passed")),
        ("compile", "incorrect", "failed", "typecheck_nonzero_exit", "candidate_failure",
         ("unavailable",) * 3),
        ("scope", "correct", "passed", None, None, ("passed",) * 3),
        ("timeout", "incorrect", "passed", "candidate_timeout", "candidate_failure",
         ("failed", "passed", "passed")),
        ("infrastructure", "unavailable", "unavailable", "SandboxImageUnavailable",
         "evaluator_infrastructure", ("unavailable",) * 3),
        ("unknown", "unavailable", "unavailable", "mystery",
         "unresolved", ("unavailable",) * 3),
    ],
)
async def test_scripted_evaluator_outcomes(
    tmp_path: Path, case: str, verdict: str, preflight_status: str, cause: str | None,
    attribution: str | None, statuses: tuple[str, ...],
) -> None:
    store = ObjectStore(tmp_path / "store")
    fixture = load_pilot_study_fixture(store)
    scenario = fixture.scenarios[0]
    baseline = scenario.realizations["baseline"]
    digest = workflow_tree_digest(baseline)
    coordinate = CellCoordinate(
        subject_id=scenario.subject_id, arm_id="baseline", worker_repeat=0,
        realization_ref=str(store.publish_json({"repository": baseline})),
    )
    output = {
        "cell_id": coordinate.id,
        "patch_ref": _envelope(store, "candidate.patch", b""),
        "tree_digest_ref": _envelope(store, "tree_digest", digest.encode()),
        "result_ref": _envelope(store, "result.json", canonical_json({
            "baseline_tree_digest": digest,
        })),
    }
    rejected = ({
        "path": "tsconfig.json", "disposition": "restored",
        "baseline_digest": "sha256:" + "a" * 64,
        "candidate_digest": "sha256:" + "b" * 64,
    },) if case == "scope" else ()
    scripted = WorkflowCorrectnessResult(
        verdict,  # type: ignore[arg-type]
        tuple(GroupResult(
            name, status, cause if status != "passed" else None,  # type: ignore[arg-type]
            "stdout", "stderr", 1 if status == "failed" else 0,
            10.0 if case == "timeout" and status == "failed" else None,
        ) for name, status in zip(
            ("visible_regression", "hidden_regression", "new_behavior"), statuses,
            strict=True,
        )),
        cause,
        PreflightResult(preflight_status, cause if preflight_status != "passed" else None),
        attribution,  # type: ignore[arg-type]
        rejected,
    )

    class ScriptedRunner(RecordingRunner):
        async def run(self, **kwargs: Any) -> WorkflowCorrectnessResult:
            self.calls.append(kwargs)
            return scripted

    runner = ScriptedRunner(fixture.manifest.observed_runtime_image_digest)
    evaluator = CellEvaluator(store, fixture.manifest, runner)  # type: ignore[arg-type]
    result = await evaluator.evaluate(
        input_value={"repository": baseline}, output=output,
        coordinate=EvaluationCoordinate(
            cell_id=coordinate.id, evaluator_id="correctness", evaluator_repeat=0,
        ),
    )
    assert result.verdict == verdict
    record = evaluator.records[coordinate.id]
    assert record["cause"] == cause
    assert record["preflight"] == {
        "status": preflight_status,
        "cause": cause if preflight_status != "passed" else None,
    }
    assert record["attribution"] == attribution
    assert [group["status"] for group in record["groups"].values()] == list(statuses)  # type: ignore[union-attr]
    assert record["rejected_changes"] == list(rejected)
    assert all(group["stdout"] == "stdout" and group["stderr"] == "stderr"
               for group in record["groups"].values())  # type: ignore[union-attr]
    assert ("correctness_category" in record) is (case != "unknown")


def test_classification_uses_named_preflight() -> None:
    classified = classify(Submitted(), EvaluatorVerdict(
        "incorrect", (GroupVerdict("unavailable", "typecheck_nonzero_exit"),),
        "typecheck_nonzero_exit", PreflightResult("failed", "typecheck_nonzero_exit"),
        "candidate_failure",
    ))
    assert classified == NeedsOperatorJudgment("invalid_or_incomplete")
    legacy = classify(Submitted(), EvaluatorVerdict(
        "incorrect", (GroupVerdict("unavailable", "typecheck_nonzero_exit"),),
        "typecheck_nonzero_exit",
    ))
    assert legacy == classified


def test_grader_cache_key_changes_with_every_identity_input() -> None:
    args: dict[str, Any] = {
        "candidate_tree_digest": "candidate",
        "baseline_tree_digest": "baseline",
        "image_digest": "image",
        "dependency_lock_digests": {"package-lock.json": "lock"},
        "test_group_digests": {
            "visible_regression": "visible", "hidden_regression": "hidden",
            "new_behavior": "new",
        },
        "evaluator_configuration": {"deadline_s": 10},
        "grader_revision": "2",
    }
    unchanged = grader_cache_key(**args)
    assert grader_cache_key(**args) == unchanged
    for field_name in ("candidate_tree_digest", "baseline_tree_digest", "image_digest",
                       "grader_revision"):
        changed = {**args, field_name: "changed"}
        assert grader_cache_key(**changed) != unchanged
    for field_name, key in (
        ("dependency_lock_digests", "package-lock.json"),
        ("test_group_digests", "visible_regression"),
        ("test_group_digests", "hidden_regression"),
        ("test_group_digests", "new_behavior"),
        ("evaluator_configuration", "deadline_s"),
    ):
        changed = {**args, field_name: {**args[field_name], key: "changed"}}
        assert grader_cache_key(**changed) != unchanged
