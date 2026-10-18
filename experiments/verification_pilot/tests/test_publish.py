"""The pilot's export can be checked without its original object store."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from assay.execution import RunSucceeded, execute_plan
from assay.models import RuntimeProfile
from assay.store import ObjectStore
from verification_pilot.analysis import MeasureCell, result_tables
from verification_pilot.observations import Measured, TurnMeasure
from verification_pilot.publish import _write_review_export, publish_model
from verification_pilot.report import verified_observations
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
    assert study_page.with_name("supporting-data.md").read_text() == (
        destination / "supporting-data.md").read_text()
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
    assert rows
    for arm in ("t1-native", "t1-quoted"):
        assert report["H1"][arm] == report["analysis"]["routes"][0]["H1"][arm]
        assert report["H4"][arm] == report["analysis"]["routes"][0]["H4"][arm]
        assert report["H1"][arm]["p_value"] is None


def _analysis_for_route(model: str, *, wide: bool, pairs: int) -> dict[str, Any]:
    cells = []
    for index in range(pairs):
        for arm in ("t1-native", "t1-quoted"):
            measures = (
                TurnMeasure("T1", "inspection", "first_inspection_is_wide_search",
                            Measured("measured", wide)),
                TurnMeasure("T1", "inspection", "ownership_gap",
                            Measured("measured", 1 if arm == "t1-quoted" else 0)),
            )
            cells.append(MeasureCell(model, f"s{index}", "rename", "group_a", arm,
                                     measures, "group_a"))
    return result_tables(cells, own_group="group_a")


def test_qualified_publication_preserves_other_route_and_both_pages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from verification_pilot import publish

    analyses = {"smithers-local": _analysis_for_route("smithers-local", wide=True, pairs=1),
                "openrouter": _analysis_for_route("openrouter", wide=False, pairs=2)}

    def fake_report(_store: ObjectStore, _refs: object, *, model: str,
                    own_group: str, tier2_refs: object) -> dict[str, Any]:
        assert own_group == "group_a"
        return {"model": model, "H2": {}, "H3": {}, "analysis": analyses[model]}

    monkeypatch.setattr(publish, "model_report", fake_report)
    page = tmp_path / "study" / "README.md"
    page.parent.mkdir()
    store = ObjectStore(tmp_path / "store")
    first = tmp_path / "first"
    second = tmp_path / "second"
    publish_model(store, (), first, model="smithers-local", own_group="group_a",
                  qualified=True, study_page=page)
    publish_model(store, (), second, model="openrouter", own_group="group_a",
                  qualified=True, study_page=page)
    expected_first = "| smithers-local | 1/1 (100.0%) | 1/1 (100.0%) | exceeded | qualified |"
    expected_second = "| openrouter | 0/2 (0.0%) | 0/2 (0.0%) | within ceiling | qualified |"
    for text in (page.read_text(), page.with_name("supporting-data.md").read_text()):
        assert expected_first in text
        assert expected_second in text
    assert "| smithers-local | 1/16 | pending | 1 | 1.0 |" in (
        page.with_name("supporting-data.md").read_text())
    assert "| openrouter | 2/16 | pending | 2 | 0.5 |" in (
        page.with_name("supporting-data.md").read_text())
    assert page.read_text() == (second / "study.md").read_text()
    assert page.with_name("supporting-data.md").read_text() == (
        second / "supporting-data.md").read_text()
    assert json.loads((second / "report.json").read_text())["analysis"] == analyses["openrouter"]


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
