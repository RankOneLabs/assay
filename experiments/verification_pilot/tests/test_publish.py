"""The pilot's export can be checked without its original object store."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from assay.execution import RunSucceeded, execute_plan
from assay.models import RuntimeProfile
from assay.store import ObjectStore
from verification_pilot.publish import _write_review_export, publish_model
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
    study_page = tmp_path / "study.md"
    study_page.write_text(
        "# Pilot\n<!-- ceiling-table:start -->\n"
        "| Route | Native | Quoted | Status |\n| --- | ---: | ---: | --- |\n"
        "| fixture | pending | pending | in progress |\n"
        "<!-- ceiling-table:end -->\n", encoding="utf-8",
    )
    report = publish_model(store, (str(run.manifest_ref),), destination,
                           model="fixture", own_group="group_a", qualified=True,
                           study_page=study_page)
    assert report["H2"]["comparison"]["n"] == 1
    assert (destination / "report.json").exists()
    assert (destination / "h2-review.txt").exists()
    assert report["review_exports"]["H2"]["status"] == "over_cap"
    assert report["review_exports"]["H2"]["cap_bytes"] == 64 * 1024 * 1024
    pending_row = ("| fixture | pending (0 observed) | pending (0 observed) "
                   "| pending | qualification pending |")
    assert pending_row in study_page.read_text()
    assert report["ceiling_effect"] == [
        {"model": "fixture", **report["analysis"]["routes"][0]["ceiling"][arm]}
        for arm in ("t1-native", "t1-quoted")
    ]
    assert all(row["n"] == 0 and row["exceeds_half"] is None
               for row in report["ceiling_effect"])
    assert study_page.read_text() == (destination / "study.md").read_text()
    assert (destination / "supporting-data.md").exists()
    assert report["escalation_chart"] == []
    assert "12 paired observations" in report["power"]["H1"]
    assert "12 paired observations" in report["power"]["H2"]
    assert "12 of 16" in report["power"]["H3"]
    assert "Four migration-matched pairs" in report["power"]["H4"]
    assert "No engine p-value" in report["power"]["H4"]
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


def test_review_export_uses_html_when_closure_fits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    objects = tmp_path / "objects"
    objects.mkdir()
    (objects / "small").write_bytes(b"small closure")

    def write_html(_store: ObjectStore, _ref: str, target: Path) -> Path:
        target.write_text("<html>review</html>", encoding="utf-8")
        return target

    monkeypatch.setattr("verification_pilot.publish.export_review", write_html)
    review = _write_review_export(ObjectStore(tmp_path / "store"), "ref", objects,
                                  tmp_path, "H2")
    assert review == {"closure_bytes": 13, "cap_bytes": 64 * 1024 * 1024,
                      "status": "html"}
    assert (tmp_path / "h2-review.html").exists()
    assert not (tmp_path / "h2-review.txt").exists()
