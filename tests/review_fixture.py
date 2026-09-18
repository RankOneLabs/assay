from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import paa_contracts
import pytest

from assay.canonical import canonical_json, digest_bytes
from assay.execution import RunSucceeded, WorkerFailure, WorkerResult, WorkerSuccess, execute_plan
from assay.investigations.consistency import (
    TASKS,
    CodingTask,
    StructuralEvaluator,
    materialize_consistency,
)
from assay.models import Exclusion, StudySnapshot
from assay.planning import compile_plan
from assay.store import ObjectStore
from assay.verify import export_bundle, verify_bundle, verify_manifest, verify_snapshot

if TYPE_CHECKING:
    from review_fixture_studies import ReviewStudies

HOSTILE_STRINGS = (
    "</script><script>window.pwned=true</script>",
    "</ScRiPt><ScRiPt>window.mixedCase=true</sCrIpT>",
    "<strong>fixture markup</strong>",
    "'single quotes'",
    '"double quotes"',
    "fish & chips",
    "line\u2028separator",
    "paragraph\u2029separator",
)
HOSTILE_TEXT = " | ".join(HOSTILE_STRINGS)
HOSTILE_REPOSITORY_PATH = "review/" + "__".join(HOSTILE_STRINGS) + ".py"


def contracts() -> dict[str, dict[str, Any]]:
    """Load the canonical PAA contracts in test code only."""
    return {
        name: paa_contracts.load_schema(name)
        for name in ("paa-task", "paa-evidence-record", "paa-operating-record")
    }


class ReviewWorker:
    """Offline worker with one execution failure and one ambiguous successful output."""

    def __init__(self) -> None:
        self.failed = False
        self.returned_ambiguous = False

    def configuration(self, arm_id: str) -> dict[str, Any]:
        del arm_id
        return {"id": "review-fixture", "version": "1", "offline": True}

    async def run(self, *, input_value: Any, arm_id: str) -> WorkerResult:
        task_id = input_value["task"]["id"]
        if arm_id == "clean" and task_id == TASKS[1].id and not self.failed:
            self.failed = True
            return WorkerFailure(
                "InjectedFailure",
                "review fixture failure: " + HOSTILE_TEXT,
                trace={"diagnostics": list(HOSTILE_STRINGS)},
            )
        if arm_id == "inconsistent" and task_id == TASKS[0].id and not self.returned_ambiguous:
            self.returned_ambiguous = True
            source = f'"""{HOSTILE_TEXT}"""\ndef implement(value): return value\n'
            return WorkerSuccess({"source": source})
        task = next(task for task in TASKS if task.id == task_id)
        source = task.reused_source if arm_id == "clean" else task.duplicated_source
        return WorkerSuccess({"source": source})


@dataclass(frozen=True)
class ReviewFixture:
    store: ObjectStore
    snapshot: StudySnapshot
    result: RunSucceeded
    bundle: ObjectStore
    damaged_stores: dict[str, ObjectStore]
    studies: ReviewStudies

    @property
    def manifest_ref(self) -> str:
        return str(self.result.manifest_ref)


def _tasks() -> tuple[CodingTask, ...]:
    first = TASKS[0].model_copy(
        update={"instruction": TASKS[0].instruction + " Review label: " + HOSTILE_TEXT}
    )
    return (first, TASKS[1])


def _repositories(tasks: tuple[CodingTask, ...]) -> dict[str, dict[str, dict[str, str]]]:
    variants: dict[str, dict[str, dict[str, str]]] = {}
    for task in tasks:
        variants[task.id] = {}
        for arm in ("clean", "inconsistent"):
            example = task.reused_source if arm == "clean" else task.duplicated_source
            variants[task.id][arm] = {
                task.target_path: task.helper_source
                + "\n"
                + example.replace("implement", "existing_feature"),
                HOSTILE_REPOSITORY_PATH: "# " + HOSTILE_TEXT + "\n",
            }
    return variants


def _damaged_bundle_variants(
    bundle: ObjectStore, result: RunSucceeded, root: Path
) -> dict[str, ObjectStore]:
    evaluation_ref = next(iter(result.manifest.evaluation_records.values()))
    execution_ref = next(iter(result.manifest.execution_records.values()))
    targets = {
        "manifest": str(result.manifest_ref),
        "evaluation": evaluation_ref,
        "execution": execution_ref,
        "unexpected": "sha256:" + "0" * 64,
    }
    damaged: dict[str, ObjectStore] = {}
    for name, target_ref in targets.items():
        destination = root / name
        shutil.copytree(bundle.root, destination)
        variant = ObjectStore(destination)
        object_path = variant.objects / target_ref.removeprefix("sha256:")
        object_path.write_bytes(("damaged-" + name).encode())
        damaged[name] = variant
    return damaged


async def materialize_review_fixture(root: Path) -> ReviewFixture:
    """Build the complete offline review run, export, and corrupt-object variants."""
    store = ObjectStore(root / "store")
    worker = ReviewWorker()
    evaluator = StructuralEvaluator()
    tasks = _tasks()
    snapshot = materialize_consistency(
        store,
        worker_configuration=worker.configuration("clean"),
        evaluator=evaluator,
        schemas=contracts(),
        tasks=tasks,
        evaluator_repeats=1,
        repository_variants=_repositories(tasks),
    )
    verify_snapshot(store, snapshot)
    snapshot_ref = str(store.publish_json(snapshot.model_dump(mode="json")))
    plan = compile_plan(
        snapshot,
        snapshot_ref=snapshot_ref,
        worker_repeats=2,
        jig_revision="review-fixture",
        concurrency=2,
        exclusions=(
            Exclusion(
                subject_id=TASKS[1].id,
                arm_id="inconsistent",
                classification="fixture",
                reason="predeclared review-fixture exclusion",
            ),
        ),
    )
    plan_bytes = canonical_json(plan.model_dump(mode="json"))
    outcome = await execute_plan(
        plan_bytes=plan_bytes,
        authorization=digest_bytes(plan_bytes),
        snapshot=snapshot,
        store=store,
        workers={"clean": worker, "inconsistent": worker},
        evaluators={"abstraction": evaluator},
    )
    if not isinstance(outcome, RunSucceeded):
        raise AssertionError(f"review fixture run failed: {outcome}")
    # The one injected execution failure leaves its own evaluation genuinely
    # unavailable, so the manifest is honestly incomplete — that is the
    # scenario this fixture exists to exercise, not a defect in the fixture.
    if outcome.manifest.status != "incomplete" or len(outcome.manifest.missing_coordinates) != 1:
        raise AssertionError("review fixture manifest must have exactly one unavailable evaluation")
    manifest_failures = [
        failure.code for failure in verify_manifest(store, str(outcome.manifest_ref))
    ]
    if manifest_failures != ["incomplete_run"]:
        raise AssertionError(f"review fixture manifest does not verify: {manifest_failures}")

    bundle = export_bundle(store, str(outcome.manifest_ref), root / "bundle")
    bundle_failures = [failure.code for failure in verify_bundle(bundle, str(outcome.manifest_ref))]
    if bundle_failures != ["incomplete_run"]:
        raise AssertionError(f"review fixture bundle does not verify: {bundle_failures}")
    damaged = _damaged_bundle_variants(bundle, outcome, root / "damaged")
    from review_fixture_studies import materialize_review_studies

    studies = await materialize_review_studies(store, root / "report-bundles")
    return ReviewFixture(store, snapshot, outcome, bundle, damaged, studies)


@pytest.fixture
async def review_fixture(tmp_path: Path) -> ReviewFixture:
    return await materialize_review_fixture(tmp_path)


def read_records(store: ObjectStore, refs: Any) -> list[dict[str, Any]]:
    return [json.loads(store.read_bytes(ref)) for ref in refs]
