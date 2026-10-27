"""Run the fixture-derived 24-session grid without a model route."""

import asyncio
import base64
import json
import shutil
from pathlib import Path

from assay.execution import RunSucceeded
from assay.store import ObjectStore
from verification_pilot.run import archive_manifest, remeasure_archive, run_scripted
from verification_pilot.self_trust.settings import countable


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


def test_archive_copies_configuration_and_revalidation_without_store(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path / "store")
    configuration = {
        "model_route": {"model": "anthropic/claude-sonnet-5.5",
                        "provider": "amazon-bedrock", "endpoint": "https://route.example"},
        "bounds": {"max_turns": 150, "max_output_tokens": 8192},
        "max_tool_calls_per_turn": 100, "max_tool_calls_per_cell": 300,
        "timeout_s": 1800, "system_prompt_sha256": "sha256:system",
        "turn_prompts_sha256": "sha256:turns", "tools_sha256": "sha256:tools",
        "protocol_version": "st-v2",
    }
    config_ref = str(store.publish_json(configuration))
    worker_ref = str(store.publish_json({"binding": {
        "configuration_ref": config_ref, "image_digest": "sha256:image"}}))
    trajectory = {"events": [], "turns": [{"submission": {"verdict": "incomplete"}}]}
    trajectory_ref = str(store.publish_json({"content_base64": base64.b64encode(
        json.dumps(trajectory).encode()).decode()}))
    output_ref = str(store.publish_json({"raw_trajectory_ref": trajectory_ref}))
    record_ref = str(store.publish_json({"status": "succeeded", "trace_ref": worker_ref,
                                         "output_ref": output_ref}))
    manifest_ref = str(store.publish_json({"run_id": "new-run", "execution_records": {
        "subject:st-native:w0": record_ref}}))
    subject = type("Subject", (), {"repository": {"src/a.ts": "export const a = 1;"}})()
    archive = archive_manifest(store, manifest_ref, tmp_path / "archive",
                               {"subject": subject}, measure=lambda *_: [{"name": "grade"}])
    shutil.rmtree(store.root)
    entry = json.loads((archive / "index.json").read_text())["subject:st-native:w0"]
    assert entry["configuration"] == {**configuration, "configuration_ref": config_ref}
    recorded = entry["revalidation"]
    assert recorded["new_run_id"] == "new-run" and recorded["original_run_id"] is None
    assert recorded["protocol_version"] == "st-v2"
    assert recorded["image_hash"] == "sha256:image"
    assert recorded["model_route"] == configuration["model_route"]
    assert recorded["bounds"] == {**configuration["bounds"],
                                  "max_tool_calls_per_turn": 100,
                                  "max_tool_calls_per_cell": 300, "timeout_s": 1800}
    assert recorded["fixture_hash"].startswith("sha256:")
    assert recorded["terminal_status"] == "completed_valid"
    measures = json.loads((archive / "traces" / entry["measures"]).read_text())
    assert recorded["grader_version"] == measures[0]["code_revision"]


def test_replacement_archive_keeps_original_and_retry_reference(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path / "store")
    cell = "subject:st-native:w0"
    config_ref = str(store.publish_json({"protocol_version": "st-v2"}))
    worker_ref = str(store.publish_json({"binding": {"configuration_ref": config_ref},
                                         "bridge_outcome": {"cause": "provider_response"}}))
    record_ref = str(store.publish_json({"status": "failed", "trace_ref": worker_ref}))
    subject = object()
    original_manifest = str(store.publish_json({"run_id": "original", "execution_records": {
        cell: record_ref}}))
    original = archive_manifest(store, original_manifest, tmp_path / "archives",
                                {"subject": subject})
    replacement_worker = str(store.publish_json({"binding": {"configuration_ref": config_ref}}))
    trajectory_ref = str(store.publish_json({"content_base64": base64.b64encode(json.dumps({
        "turns": [{"submission": {"verdict": "incomplete"}}]}).encode()).decode()}))
    output_ref = str(store.publish_json({"raw_trajectory_ref": trajectory_ref}))
    replacement_record = str(store.publish_json({"status": "succeeded",
                                                  "trace_ref": replacement_worker,
                                                  "output_ref": output_ref}))
    replacement_manifest = str(store.publish_json({"run_id": "replacement", "execution_records": {
        cell: replacement_record}}))
    replacement = archive_manifest(store, replacement_manifest, tmp_path / "archives",
                                   {"subject": subject}, measure=lambda *_: [],
                                   retry_of={cell: cell},
                                   original_run_ids={cell: "original"})
    assert original.exists() and replacement.exists()
    old = json.loads((original / "index.json").read_text())[cell]["revalidation"]
    new = json.loads((replacement / "index.json").read_text())[cell]["revalidation"]
    assert old["retry_of"] is None
    assert new["retry_of"] == cell and new["original_run_id"] == "original"
    assert not countable(old["terminal_status"], old["terminal_cause"])
    assert countable(new["terminal_status"], new["terminal_cause"])
