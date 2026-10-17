"""Offline multi-arm study wiring: plan, rotation, grid check and per-cell grading.

One synthetic subject with four tiny repository trees (N = 4 dose sites) runs a
4-repeat grid through ``execute_plan`` with a scripted worker and a recording
evaluator runner. No Docker, Smithers, or model is involved.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any, get_args

import pytest

from assay.canonical import canonical_json
from assay.execution import WorkerSuccess
from assay.fixture_manifest import (
    DOSE_ARMS,
    DOSED_ARMS,
    DoseArm,
    FixtureManifestV2,
    dose_count,
)
from assay.investigations.workflow_correctness import (
    GroupResult,
    WorkflowCorrectnessResult,
    WorkflowRunnerSettings,
    WorkflowTestGroup,
    workflow_tree_digest,
)
from assay.models import (
    CellCoordinate,
    EvaluationCoordinate,
    ExecutionCeiling,
    RuntimeProfile,
    parse_execution_plan,
)
from assay.store import ObjectStore
from workflow_edit.arms import ARM_IDS, MESS_00, MESS_HIGH, MESS_LOW, MESS_MID
from workflow_edit.evaluation import CellEvaluator
from workflow_edit.fixture import SMOKE_EDIT_SUBJECT_ID, load_fixture
from workflow_edit.qualify import (
    CorrectnessEvaluator,
    Prepared,
    WorkflowEditWorker,
    read_evidence,
    run,
)
from workflow_edit.qualify import fixture_manifest as smoke_manifest
from workflow_edit.study import (
    STUDY_SCHEDULE,
    StudyFixture,
    StudySubject,
    check_fixture,
    plan_study,
    regrade_wf13,
)

SUBJECT = "synthetic-pointer"


@pytest.mark.asyncio
async def test_regrade_uses_stored_patch_and_fixed_runner() -> None:
    smoke = read_evidence("smoke")
    cell_id = sorted(smoke["evaluations"])[0]
    smoke = {**smoke, "evaluations": {cell_id: smoke["evaluations"][cell_id]}}
    patch = smoke["cells"][cell_id]["patch"]

    class RegradeRunner:
        settings = WorkflowRunnerSettings(image=smoke["image"], toolchain="bun")

        def __init__(self) -> None:
            self.seen_patch: str | None = None

        def configuration(self) -> dict[str, str]:
            return {"harness_sha256": "sha256:" + "f" * 64}

        async def run(self, **kwargs: Any) -> WorkflowCorrectnessResult:
            self.seen_patch = kwargs["patch"]
            assert kwargs["baseline_tree_digest"] == workflow_tree_digest(kwargs["baseline"])
            return WorkflowCorrectnessResult(
                "correct", tuple(GroupResult(group.name, "passed") for group in kwargs["groups"])
            )

    runner = RegradeRunner()
    result = await regrade_wf13(smoke, runner)  # type: ignore[arg-type]
    assert runner.seen_patch == patch
    assert list(result["evaluations"]) == [cell_id]
    assert result["changed_grades"][cell_id]["after"]["verdict"] == "correct"
N = 4
REPEATS = 4
IMAGE = "sha256:" + "a" * 64
ROUTING = "sha256:" + "b" * 64
OWNER = "export function readOwner(value: string): string {\n  return value.trim();\n}\n"
VISIBLE = {"tests/visible/owner.test.ts": "import './../../src/owner';\n"}


def _caller(rank: int, *, inline: bool) -> str:
    if inline:
        body = "  return value.trim();\n"
        return f"export function caller{rank}(value: string): string {{\n{body}}}\n"
    return (
        "import { readOwner } from './owner';\n"
        f"export function caller{rank}(value: string): string {{\n"
        "  return readOwner(value);\n}\n"
    )


def _tree(arm: DoseArm) -> dict[str, str]:
    inline = dose_count(arm, N)
    return {
        "src/owner.ts": OWNER,
        **{f"src/caller_{rank}.ts": _caller(rank, inline=rank <= inline)
           for rank in range(1, N + 1)},
        **VISIBLE,
    }


def _digest_of(store: ObjectStore, value: Any) -> str:
    return str(store.publish_json(value))


def _manifest(store: ObjectStore, trees: dict[str, dict[str, str]]) -> FixtureManifestV2:
    groups = {
        "visible_regression": WorkflowTestGroup(
            name="visible_regression", files=VISIBLE, command=("bun", "test"), restores=True
        ),
        "hidden_regression": WorkflowTestGroup(
            name="hidden_regression", files={"tests/hidden/regression.test.ts": "// r"},
            command=("bun", "test"),
        ),
        "new_behavior": WorkflowTestGroup(
            name="new_behavior", files={"tests/hidden/new.test.ts": "// n"},
            command=("bun", "test"),
        ),
    }
    refs = {name: _digest_of(store, group.model_dump(mode="json"))
            for name, group in groups.items()}

    def evidence(label: str) -> dict[str, str]:
        outcome = "failed" if label == "feature" else "passed"
        return {"outcome": outcome,
                "evidence": _digest_of(store, {"record": label, "outcome": outcome})}

    return FixtureManifestV2.model_validate({
        "schema_version": "assay-fixture-manifest/0.2.0",
        "checkpoint_sha": "c" * 40,
        "included_paths": ["src/", "tests/visible/"],
        "excluded_paths": ["tests/hidden/"],
        "normalization_diff": "synthetic\n",
        "dependency_lock_digests": {},
        "observed_runtime_image_digest": IMAGE,
        "routing_config_digest": ROUTING,
        "tasks": [{
            "subject_id": SUBJECT,
            "task_prompt": "Make readOwner strict.",
            "normalization_patch": _digest_of(store, {"normalization": "none"}),
            "transformation_version": "synthetic-inline/1",
            "treatment_site_count": N,
            "treatment_sites": [
                {
                    "rank": rank,
                    "path": f"src/caller_{rank}.ts",
                    "symbol": f"caller{rank}",
                    "span": {"start_line": 2, "end_line": 4},
                    "arms": [arm for arm in DOSED_ARMS if rank <= dose_count(arm, N)],
                    "removed_imports": [{
                        "module": "./owner", "name": "readOwner",
                        "arms": [arm for arm in DOSED_ARMS if rank <= dose_count(arm, N)],
                    }],
                }
                for rank in range(1, N + 1)
            ],
            "arms": {
                arm: {
                    "tree_digest": workflow_tree_digest(trees[arm]),
                    "reference_patch": _digest_of(store, {"reference": arm}),
                    "negative_patches": [_digest_of(store, {"negative": arm})],
                    "qualification": {
                        "baseline_passes": evidence(f"{arm} baseline"),
                        "feature_fails": evidence("feature"),
                        "reference_passes": evidence(f"{arm} reference"),
                        "equivalence_passes": evidence(f"{arm} equivalence"),
                    },
                }
                for arm in DOSE_ARMS
            },
            "visible_tests": [{"name": "visible_regression", "digest": refs["visible_regression"]}],
            "hidden_tests": [
                {"name": "hidden_regression", "digest": refs["hidden_regression"]},
                {"name": "new_behavior", "digest": refs["new_behavior"]},
            ],
            "equivalence_suite": _digest_of(store, {"equivalence": "synthetic"}),
            "rubric": _digest_of(store, {"rubric": "synthetic"}),
        }],
    })


def _envelope(store: ObjectStore, path: str, data: bytes) -> str:
    return _digest_of(store, {
        "schema_version": "assay-pier-raw-artifact/0.1.0", "path": path,
        "byte_length": len(data), "content_base64": base64.b64encode(data).decode("ascii"),
    })


def _output(
    store: ObjectStore, cell_id: str, repository: dict[str, str], *, baseline_digest: str
) -> dict[str, Any]:
    """A settled cell's output with the evidence ``PierAdapter`` publishes."""
    patch = b"--- a/src/owner.ts\n+++ b/src/owner.ts\n"
    candidate = workflow_tree_digest({**repository, "src/owner.ts": OWNER + "// strict\n"})
    result = {"exit_status": "submitted", "baseline_tree_digest": baseline_digest,
              "tree_digest": candidate}
    return {
        "cell_id": cell_id,
        "patch_ref": _envelope(store, "candidate.patch", patch),
        "tree_digest_ref": _envelope(store, "tree_digest", candidate.encode("ascii")),
        "result_ref": _envelope(store, "result.json", canonical_json(result)),
        "raw_trajectory_ref": _envelope(store, "trajectory.json", b"{}"),
    }


class ScriptedAdapter:
    """Submits one patch per cell; reports a wrong baseline for the named cells."""

    def __init__(self, store: ObjectStore, wrong_baseline: frozenset[str] = frozenset()) -> None:
        self.store = store
        self.wrong_baseline = wrong_baseline
        self.dispatched: list[str] = []

    def configuration(self, arm_id: str) -> dict[str, Any]:
        return {"id": "scripted-repository-agent", "version": "1"}

    async def run_cell(self, *, input_value: Any, coordinate: CellCoordinate) -> WorkerSuccess:
        self.dispatched.append(coordinate.id)
        repository = input_value["repository"]
        baseline = workflow_tree_digest(repository)
        if coordinate.id in self.wrong_baseline:
            baseline = workflow_tree_digest(_tree("mess-00"))
        return WorkerSuccess(output=_output(
            self.store, coordinate.id, repository, baseline_digest=baseline
        ))


class ScriptedBridge:
    def configuration(self) -> dict[str, Any]:
        return {"bridge": "scripted"}


class RecordingRunner:
    def __init__(self, image: str = IMAGE) -> None:
        self.settings = WorkflowRunnerSettings(image=image)
        self.calls: list[dict[str, Any]] = []

    def configuration(self) -> dict[str, Any]:
        return {"runner": "recording", "image": self.settings.image}

    async def run(self, **kwargs: Any) -> WorkflowCorrectnessResult:
        assert workflow_tree_digest(kwargs["baseline"]) == kwargs["baseline_tree_digest"]
        self.calls.append(kwargs)
        return WorkflowCorrectnessResult(
            "correct", tuple(GroupResult(group.name, "passed") for group in kwargs["groups"])
        )


def _study(tmp_path: Path, *, subject_id: str = SUBJECT, **realization_changes: Any) -> tuple[
    ObjectStore, StudyFixture
]:
    store = ObjectStore(tmp_path / "store")
    trees: dict[str, dict[str, str]] = {arm: _tree(arm) for arm in DOSE_ARMS}
    manifest = _manifest(store, trees)
    if subject_id != SUBJECT:
        manifest = FixtureManifestV2.model_validate({
            **manifest.model_dump(mode="json"),
            "tasks": [{**manifest.tasks[0].model_dump(mode="json"), "subject_id": subject_id}],
        })
    trees.update(realization_changes)
    return store, StudyFixture(manifest, (StudySubject(subject_id, trees),))


def _plan(
    store: ObjectStore, fixture: StudyFixture, adapter: ScriptedAdapter, runner: RecordingRunner
) -> Prepared:
    worker = WorkflowEditWorker(adapter, ScriptedBridge(), store)  # type: ignore[arg-type]
    return plan_study(
        store,
        fixture,
        worker=worker,
        runner=runner,  # type: ignore[arg-type]
        runtime=RuntimeProfile(id="pier", version="scripted",
                               configuration_ref=_digest_of(store, {"runtime": "scripted"})),
        image=IMAGE,
        routing_digest=ROUTING,
        repeats=REPEATS,
        ceiling=ExecutionCeiling(max_cells=len(ARM_IDS) * REPEATS, max_wall_time_seconds=600,
                                 max_fleet_occupancy=1),
    )


def test_core_dose_arms_are_the_experiment_arms() -> None:
    assert ARM_IDS == DOSE_ARMS == get_args(DoseArm) == (MESS_00, MESS_LOW, MESS_MID, MESS_HIGH)


def test_plan_has_four_realizations_rotated_schedule_and_a_full_grid(tmp_path: Path) -> None:
    store, fixture = _study(tmp_path)
    prepared = _plan(store, fixture, ScriptedAdapter(store), RecordingRunner())
    plan = parse_execution_plan(json.loads(prepared.plan_bytes))
    assert prepared.authorization == str(store.publish_bytes(prepared.plan_bytes))
    assert all(arm.conditions == {"assay_execution_schedule": STUDY_SCHEDULE}
               for arm in prepared.snapshot.arms)

    realization = {item.arm_id: item.artifact_ref for item in prepared.snapshot.realizations}
    assert sorted(realization) == sorted(ARM_IDS) and len(set(realization.values())) == 4
    for arm_id, ref in realization.items():
        given = json.loads(store.read_bytes(ref))
        assert workflow_tree_digest(given["repository"]) == workflow_tree_digest(_tree(arm_id))
        assert given["task"] == fixture.manifest.tasks[0].task_prompt

    # subject-rotated-v1: base order is the arms sorted by id, and each
    # subject/repeat block starts one arm later than the one before.
    base = sorted(ARM_IDS)
    assert base == ["mess-00", "mess-high", "mess-low", "mess-mid"]
    expected = [
        (repeat, arm)
        for repeat in range(REPEATS)
        for arm in (*base[repeat % 4:], *base[:repeat % 4])
    ]
    assert [(cell.worker_repeat, cell.arm_id) for cell in plan.cells] == expected
    firsts = [plan.cells[block * 4].arm_id for block in range(REPEATS)]
    assert sorted(firsts) == base
    assert all(cell.realization_ref == realization[cell.arm_id] for cell in plan.cells)


def test_grid_validation_refuses_the_smoke_subject_before_authorization(tmp_path: Path) -> None:
    store, fixture = _study(tmp_path, subject_id=SMOKE_EDIT_SUBJECT_ID)
    with pytest.raises(ValueError, match="qualification smoke subject"):
        _plan(store, fixture, ScriptedAdapter(store), RecordingRunner())
    # The plan is published only after the grid check, so none exists to authorize.
    plan_marker = b'"schema_version":"assay-execution-plan/0.3.0"'
    assert not any(plan_marker in path.read_bytes() for path in store.objects.iterdir())


def test_fixture_trees_must_match_the_manifest(tmp_path: Path) -> None:
    _store, fixture = _study(tmp_path, **{MESS_MID: _tree(MESS_HIGH)})
    with pytest.raises(ValueError, match="mess-mid tree differs"):
        check_fixture(fixture, store=_store, image=IMAGE, routing_digest=ROUTING)
    _store, fixture = _study(tmp_path, **{MESS_LOW: {}})
    missing = StudyFixture(fixture.manifest, (StudySubject(
        SUBJECT, {arm: tree for arm, tree in fixture.subjects[0].realizations.items()
                  if arm != MESS_LOW}),))
    with pytest.raises(ValueError, match="one realization per arm"):
        check_fixture(missing, store=_store, image=IMAGE, routing_digest=ROUTING)


def test_fixture_must_be_qualified_and_bound_to_image_and_routing(tmp_path: Path) -> None:
    _store, fixture = _study(tmp_path)
    with pytest.raises(ValueError, match="another image"):
        check_fixture(fixture, store=_store, image="sha256:" + "d" * 64, routing_digest=ROUTING)
    with pytest.raises(ValueError, match="another routing"):
        check_fixture(fixture, store=_store, image=IMAGE, routing_digest=None)
    wire = fixture.manifest.model_dump(mode="json")
    wire["tasks"][0]["arms"]["mess-low"]["qualification"]["feature_fails"]["outcome"] = "passed"
    unqualified = StudyFixture(FixtureManifestV2.model_validate(wire), fixture.subjects)
    with pytest.raises(ValueError, match="mess-low has not qualified"):
        check_fixture(unqualified, store=_store, image=IMAGE, routing_digest=ROUTING)


def test_fixture_qualification_must_match_verified_evidence(tmp_path: Path) -> None:
    store, fixture = _study(tmp_path)
    wire = fixture.manifest.model_dump(mode="json")
    result = wire["tasks"][0]["arms"][MESS_LOW]["qualification"]["baseline_passes"]
    result["evidence"] = _digest_of(store, {"outcome": "failed"})
    with pytest.raises(ValueError, match="baseline_passes evidence mismatch"):
        check_fixture(
            StudyFixture(FixtureManifestV2.model_validate(wire), fixture.subjects),
            store=store,
            image=IMAGE,
            routing_digest=ROUTING,
        )
    corrupt = store.objects / result["evidence"].removeprefix("sha256:")
    corrupt.write_bytes(b'{"outcome":"passed"}')
    with pytest.raises(ValueError, match="baseline_passes evidence mismatch"):
        check_fixture(
            StudyFixture(FixtureManifestV2.model_validate(wire), fixture.subjects),
            store=store,
            image=IMAGE,
            routing_digest=ROUTING,
        )


def test_fixture_visible_coverage_and_hidden_tree_paths(tmp_path: Path) -> None:
    store, fixture = _study(tmp_path)
    wire = fixture.manifest.model_dump(mode="json")
    group = WorkflowTestGroup(
        name="visible_regression", files={}, command=("bun", "test"), restores=True
    )
    wire["tasks"][0]["visible_tests"][0]["digest"] = _digest_of(
        store, group.model_dump(mode="json")
    )
    with pytest.raises(ValueError, match="visible group lacks coverage"):
        check_fixture(
            StudyFixture(FixtureManifestV2.model_validate(wire), fixture.subjects),
            store=store,
            image=IMAGE,
            routing_digest=ROUTING,
        )
    tree = _tree(MESS_00) | {"tests/hidden/regression.test.ts": "// leaked"}
    trees = dict(fixture.subjects[0].realizations) | {MESS_00: tree}
    wire = fixture.manifest.model_dump(mode="json")
    wire["tasks"][0]["arms"][MESS_00]["tree_digest"] = workflow_tree_digest(tree)
    with pytest.raises(ValueError, match="contains hidden tests"):
        check_fixture(
            StudyFixture(FixtureManifestV2.model_validate(wire), (StudySubject(SUBJECT, trees),)),
            store=store,
            image=IMAGE,
            routing_digest=ROUTING,
        )


def test_fixture_must_declare_every_study_test_group(tmp_path: Path) -> None:
    _store, fixture = _study(tmp_path)
    wire = fixture.manifest.model_dump(mode="json")
    task = wire["tasks"][0]
    task["hidden_tests"] = [g for g in task["hidden_tests"] if g["name"] != "new_behavior"]
    dropped = StudyFixture(FixtureManifestV2.model_validate(wire), fixture.subjects)
    with pytest.raises(ValueError, match="lacks study test groups: new_behavior"):
        check_fixture(dropped, store=_store, image=IMAGE, routing_digest=ROUTING)
    # A hidden group declared visible is missing as a hidden group.
    wire = fixture.manifest.model_dump(mode="json")
    task = wire["tasks"][0]
    moved = [g for g in task["hidden_tests"] if g["name"] == "hidden_regression"]
    task["visible_tests"] = [*task["visible_tests"], *moved]
    task["hidden_tests"] = [g for g in task["hidden_tests"] if g not in moved]
    exposed = StudyFixture(FixtureManifestV2.model_validate(wire), fixture.subjects)
    with pytest.raises(ValueError, match="lacks study test groups: hidden_regression"):
        check_fixture(exposed, store=_store, image=IMAGE, routing_digest=ROUTING)


@pytest.mark.asyncio
async def test_execute_plan_grades_each_cell_against_its_own_arm(tmp_path: Path) -> None:
    store, fixture = _study(tmp_path)
    wrong = f"{SUBJECT}:{MESS_HIGH}:w1"
    adapter = ScriptedAdapter(store, wrong_baseline=frozenset({wrong}))
    runner = RecordingRunner()
    prepared = _plan(store, fixture, adapter, runner)
    evidence = await run(prepared, store)

    assert evidence["run"]["status"] == "complete", evidence["run"]
    assert len(adapter.dispatched) == len(ARM_IDS) * REPEATS
    verdicts = {cell: record["verdict"] for cell, record in evidence["evaluations"].items()}
    assert verdicts.pop(wrong) == "unavailable"
    assert evidence["evaluations"][wrong]["cause"] == "baseline_digest_mismatch"
    assert set(verdicts.values()) == {"correct"}
    # The refused cell never reached the runner; every other cell ran against
    # its own arm's tree.
    assert len(runner.calls) == len(ARM_IDS) * REPEATS - 1
    task = fixture.manifest.tasks[0]
    graded = {call["baseline_tree_digest"] for call in runner.calls}
    assert graded == {record.tree_digest for record in task.arms.values()}
    assert all(
        [group.name for group in call["groups"]]
        == ["visible_regression", "hidden_regression", "new_behavior"]
        for call in runner.calls
    )


def _coordinate(arm_id: str, repeat: int = 0) -> EvaluationCoordinate:
    return EvaluationCoordinate(
        cell_id=f"{SUBJECT}:{arm_id}:w{repeat}", evaluator_id="correctness", evaluator_repeat=0
    )


@pytest.mark.asyncio
async def test_cell_evaluator_takes_arm_baseline_and_digest_from_the_cell(tmp_path: Path) -> None:
    store, fixture = _study(tmp_path)
    runner = RecordingRunner()
    evaluator = CellEvaluator(store, fixture.manifest, runner)  # type: ignore[arg-type]
    task = fixture.manifest.tasks[0]

    async def grade(arm_id: str, given: str, reported: str) -> Any:
        repository = _tree(given)  # type: ignore[arg-type]
        coordinate = _coordinate(arm_id)
        return await evaluator.evaluate(
            input_value={"task": task.task_prompt, "repository": repository},
            output=_output(store, coordinate.cell_id, repository,
                           baseline_digest=workflow_tree_digest(_tree(reported))),  # type: ignore[arg-type]
            coordinate=coordinate,
        )

    for arm_id in (MESS_LOW, MESS_HIGH):
        result = await grade(arm_id, arm_id, arm_id)
        assert result.verdict == "correct"
        assert runner.calls[-1]["baseline_tree_digest"] == task.arms[arm_id].tree_digest
        assert runner.calls[-1]["baseline"] == _tree(arm_id)
    assert runner.calls[0]["baseline"] != runner.calls[1]["baseline"]

    # The worker reports the mess-00 tree for a mess-high cell: refused.
    mismatch = await grade(MESS_HIGH, MESS_HIGH, MESS_00)
    assert (mismatch.verdict, mismatch.reason_codes) == ("unavailable",
                                                         ("baseline_digest_mismatch",))
    # The worker was given another arm's realization: refused before any digest trust.
    swapped = await grade(MESS_HIGH, MESS_LOW, MESS_LOW)
    assert (swapped.verdict, swapped.reason_codes) == ("unavailable",
                                                       ("realization_digest_mismatch",))
    assert len(runner.calls) == 2


@pytest.mark.asyncio
async def test_cell_evaluator_refuses_unknown_subject_and_foreign_output(tmp_path: Path) -> None:
    store, fixture = _study(tmp_path)
    evaluator = CellEvaluator(store, fixture.manifest, RecordingRunner())  # type: ignore[arg-type]
    repository = _tree(MESS_00)
    digest = workflow_tree_digest(repository)
    unknown = EvaluationCoordinate(cell_id=f"other:{MESS_00}:w0", evaluator_id="correctness",
                                   evaluator_repeat=0)
    result = await evaluator.evaluate(
        input_value={"repository": repository},
        output=_output(store, unknown.cell_id, repository, baseline_digest=digest),
        coordinate=unknown,
    )
    assert result.reason_codes == ("unknown_subject",)
    foreign = await evaluator.evaluate(
        input_value={"repository": repository},
        output=_output(store, f"{SUBJECT}:{MESS_LOW}:w0", repository, baseline_digest=digest),
        coordinate=_coordinate(MESS_00),
    )
    assert type(foreign).__name__ == "EvaluationFailed"


@pytest.mark.asyncio
async def test_smoke_evaluator_reads_the_baseline_digest_from_worker_evidence(
    tmp_path: Path,
) -> None:
    """The wf-13 path no longer fabricates the submission's baseline digest."""
    store = ObjectStore(tmp_path / "store")
    smoke = load_fixture()
    manifest = smoke_manifest(store, smoke, image=IMAGE, routing_digest=ROUTING)
    runner = RecordingRunner()
    evaluator = CorrectnessEvaluator(store, smoke, manifest, runner)  # type: ignore[arg-type]
    coordinate = EvaluationCoordinate(
        cell_id=f"{SMOKE_EDIT_SUBJECT_ID}:{MESS_00}:w0", evaluator_id="correctness",
        evaluator_repeat=0,
    )
    realization = {"task": smoke.task, "repository": smoke.repository}
    honest = await evaluator.evaluate(
        input_value=realization,
        output=_output(store, coordinate.cell_id, smoke.repository,
                       baseline_digest=smoke.tree_digest),
        coordinate=coordinate,
    )
    assert honest.verdict == "correct"
    wrong = await evaluator.evaluate(
        input_value=realization,
        output=_output(store, coordinate.cell_id, smoke.repository,
                       baseline_digest=workflow_tree_digest({"other.ts": "x"})),
        coordinate=coordinate,
    )
    assert wrong.reason_codes == ("baseline_digest_mismatch",)
    assert len(runner.calls) == 1

@pytest.mark.asyncio
@pytest.mark.parametrize("evaluator_kind", ["study", "smoke"])
@pytest.mark.parametrize("failure", ["foreign", "integrity", "io"])
async def test_evaluators_reject_foreign_and_unreadable_worker_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, evaluator_kind: str, failure: str
) -> None:
    store, fixture = _study(tmp_path)
    smoke = load_fixture()
    runner = RecordingRunner()
    if evaluator_kind == "study":
        evaluator = CellEvaluator(store, fixture.manifest, runner)  # type: ignore[arg-type]
        repository = _tree(MESS_00)
        subject = SUBJECT
    else:
        evaluator = CorrectnessEvaluator(
            store,
            smoke,
            smoke_manifest(store, smoke, image=IMAGE, routing_digest=ROUTING),
            runner,  # type: ignore[arg-type]
        )
        repository = smoke.repository
        subject = SMOKE_EDIT_SUBJECT_ID
    coordinate = EvaluationCoordinate(
        cell_id=f"{subject}:{MESS_00}:w0", evaluator_id="correctness", evaluator_repeat=0
    )
    output = _output(
        store, coordinate.cell_id, repository, baseline_digest=workflow_tree_digest(repository)
    )
    if failure == "foreign":
        output["cell_id"] = f"{subject}:{MESS_LOW}:w0"
    elif failure == "integrity":
        (store.objects / output["result_ref"].removeprefix("sha256:")).write_bytes(b"corrupt")
    else:

        def unreadable(ref: str) -> bytes:
            raise OSError("disk unavailable")

        monkeypatch.setattr(store, "read_bytes", unreadable)
    result = await evaluator.evaluate(
        input_value={"repository": repository}, output=output, coordinate=coordinate
    )
    assert type(result).__name__ == "EvaluationFailed"
    assert result.error_type == ("MismatchedCell" if failure == "foreign" else "MissingCandidate")
    assert not runner.calls
