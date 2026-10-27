"""Run the fixture-derived 24-session grid without a model route."""

import asyncio
import json
from pathlib import Path

from assay.execution import RunSucceeded
from assay.store import ObjectStore
from verification_pilot.run import remeasure_archive, run_scripted


def test_scripted_grid_has_one_judgment_per_session(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    prepared, result = asyncio.run(run_scripted(store))
    assert isinstance(result, RunSucceeded)
    assert result.manifest.status == "complete"
    assert len(prepared.subjects) == 16
    assert len(prepared.snapshot.evaluators) == 1
    assert prepared.snapshot.evaluators[0].id == "pilot_judge"
    assert len(result.manifest.execution_records) == 24
    assert len(result.manifest.evaluation_records) == 24
    for record_ref in result.manifest.evaluation_records.values():
        record = json.loads(store.read_bytes(record_ref))
        assert record["payload"]["evaluator_id"] == "pilot_judge"
        assert record["verdict"]["value"] == "1.00"
    assert prepared.authorization.startswith("sha256:")


def test_remeasure_archive_preserves_original(tmp_path: Path, monkeypatch) -> None:
    archive = tmp_path / "archive"
    traces = archive / "traces"
    traces.mkdir(parents=True)
    original = b"original measures\n"
    (traces / "001-measures.json").write_bytes(original)
    (traces / "001-trajectory.json").write_text('{"turns": []}', encoding="utf-8")
    (archive / "index.json").write_text(json.dumps({"cell:a:w0": {
        "trajectory": "001-trajectory.json", "measures": "001-measures.json"}}), encoding="utf-8")
    monkeypatch.setattr("verification_pilot.run.observe", lambda trace, subject: [])
    assert remeasure_archive(archive, {"cell": object()}) == 1
    assert (traces / "001-measures.json").read_bytes() == original
    assert len(list(traces.glob("001-measures-*.json"))) == 1
