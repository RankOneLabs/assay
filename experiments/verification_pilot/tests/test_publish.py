"""The pilot's export can be checked without its original object store."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from assay.execution import RunSucceeded, execute_plan
from assay.models import RuntimeProfile
from assay.store import ObjectStore
from verification_pilot.publish import publish_model
from verification_pilot.report import h1_ownership_gap, h4_own_vs_teammate, verified_observations
from verification_pilot.run import GridEvaluator, ScriptedWorker, subject_truth
from verification_pilot.study import compile_pilot_plan, pilot_subjects


@pytest.mark.asyncio
async def test_publish_bundle_verifies_with_assay_cli_offline(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path / "source")
    subjects = pilot_subjects()
    worker = ScriptedWorker(store)
    prepared = compile_pilot_plan(
        store, RuntimeProfile(id="scripted", version="1",
                              configuration_ref=str(store.publish_json({"route": "fixture"}))),
        worker_configuration=worker.configuration("t1-native"), subjects_data=subjects,
        active_subject_ids=(subjects[0].id,),
    )
    by_id = {subject.id: subject for subject in subjects}
    evaluator = GridEvaluator(store, by_id,
                              {subject.id: subject_truth(subject) for subject in subjects})
    run = await execute_plan(
        plan_bytes=prepared.plan_bytes, authorization=prepared.authorization,
        snapshot=prepared.snapshot, store=store,
        workers={arm.id: worker for arm in prepared.snapshot.arms},
        evaluators={item.id: evaluator for item in prepared.snapshot.evaluators},
    )
    assert isinstance(run, RunSucceeded)
    destination = tmp_path / "published"
    report = publish_model(store, (str(run.manifest_ref),), destination,
                           model="fixture", own_group="group_a")
    assert report["H2"]["comparison"]["n"] == 1
    assert (destination / "report.json").exists()
    assert (destination / "h2-review.txt").exists()
    for bundle, ref in ((destination / "manifest-1", str(run.manifest_ref)),
                        (destination / "h2", report["H2"]["report_ref"])):
        verified = subprocess.run(
            [sys.executable, "-c", "from assay.cli import main; raise SystemExit(main())",
             "verify", str(bundle), ref], capture_output=True, text=True, check=False,
        )
        assert verified.returncode == 0, verified.stdout + verified.stderr
    rows = verified_observations(ObjectStore(destination / "manifest-1"),
                                 (str(run.manifest_ref),), "fixture")
    for arm in ("t1-native", "t1-quoted"):
        assert h1_ownership_gap(rows, arm) == report["H1"][arm]
        assert h4_own_vs_teammate(rows, arm, own_group="group_a") == report["H4"][arm]


def test_publish_rejects_nonempty_destination(tmp_path: Path) -> None:
    destination = tmp_path / "published"
    destination.mkdir()
    (destination / "old").write_text("old")
    with pytest.raises(ValueError, match="destination must be empty"):
        publish_model(ObjectStore(tmp_path / "source"), (), destination,
                      model="fixture", own_group="group_a")
