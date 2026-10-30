"""Archive rows survive a stop and retain the bridge's sealed candidate identity."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from code_extension.archive import AttemptArchive, AttemptArchiveRecord
from code_extension.bridge import EXTENSION_TOOLS  # type: ignore[attr-defined]
from code_extension.fixtures import load_scenario
from code_extension.probe import _run_script, _scripted_client
from code_extension.settings import TOOL_CALL_CEILING_REASON, ExtensionAgentSettings
from workflow_edit.tests.test_workflow_edit_bridge import FakeSandbox

from assay.canonical import canonical_json, digest_bytes
from assay.fixture_manifest import FixtureManifestV3
from assay.models import CellCoordinate, ExecutionOutcome, RunManifest
from assay.store import ObjectStore

SHA = "sha256:" + "a" * 64
TREE = "sha256:" + "b" * 64
BASE = "sha256:" + "c" * 64


def _configuration() -> dict[str, object]:
    settings = ExtensionAgentSettings.for_model("qwen-coder-32b")
    return {
        "arm_prompt": "Implement feature", "writable_prefixes": ["src/"],
        "bounds": {"max_turns": settings.max_turns,
                   "max_output_tokens": settings.max_output_tokens,
                   "max_tool_output_bytes": settings.max_tool_output_bytes},
        "timeout_s": settings.timeout_s,
        "model_context_limit_tokens": settings.model_context_limit_tokens,
        "request_timeout_s": settings.request_timeout_s,
        "per_cell_tool_call_ceiling": "unavailable",
        "per_cell_tool_call_ceiling_reason": TOOL_CALL_CEILING_REASON,
        "tools_sha256": digest_bytes(canonical_json(EXTENSION_TOOLS)),
        "model_route": {"model": "qwen-coder-32b", "provider": "smithers-local"},
    }


def _open(
    tmp_path: Path, secret: str = "publication-secret",
) -> tuple[AttemptArchive, CellCoordinate]:
    source = ObjectStore(tmp_path / "source")
    plan_ref = str(source.publish_json({"plan": "authorized"}))
    snapshot_ref = str(source.publish_json({"snapshot": "qualified"}))
    authorization_ref = str(source.publish_json({"approval": "granted"}))
    archive = AttemptArchive("run-1", tmp_path / "runs", secrets=(secret,))
    coordinate = CellCoordinate(
        subject_id="subject", arm_id="baseline", worker_repeat=0, realization_ref=SHA,
    )
    archive.begin_attempt(
        coordinate=coordinate, plan_ref=plan_ref, snapshot_ref=snapshot_ref,
        authorization_ref=authorization_ref, configuration=_configuration(),
        sidecar=None, source=source,
    )
    return archive, coordinate


def _envelope(store: ObjectStore, path: str, data: bytes) -> str:
    return str(store.publish_json({
        "path": path, "content_base64": base64.b64encode(data).decode(),
    }))


def test_record_round_trips_and_declares_every_evidence_field(tmp_path: Path) -> None:
    archive, coordinate = _open(tmp_path)
    record = archive.read(coordinate.id)
    assert AttemptArchiveRecord.model_validate_json(record.model_dump_json()) == record
    assert set(AttemptArchiveRecord.model_fields) >= {
        "study_id", "protocol_id", "protocol_version", "cohort_id", "scenario_id",
        "worker_repeat", "schedule_seed", "schedule_order", "plan_ref", "snapshot_ref",
        "authorization_ref", "code_revision", "dirty_source_digest", "fixture_ref",
        "request_ref", "configuration_ref", "prompt_ref", "prompt_digest",
        "tools_digest", "submission_digest",
        "scope_digest", "lockfile_digests", "image_digest", "grader_identity",
        "requested_model", "requested_profile", "actual_model", "actual_provider",
        "routing_digest", "requested_sampling", "provider_reported_sampling",
        "effective_bounds", "started_at", "completed_at", "request_trace_ref",
        "response_trace_ref", "tool_trace_ref", "request_ids", "errors",
        "token_usage", "price", "candidate", "completion_status", "completion_cause",
        "evaluator_output_refs",
    }
    assert record.effective_bounds["timeout_s"] == 900.0
    assert record.effective_bounds["per_cell_tool_call_ceiling"] == "unavailable"
    assert record.effective_bounds["per_cell_tool_call_ceiling_reason"] == (
        TOOL_CALL_CEILING_REASON
    )
    assert record.candidate.patch_ref is None
    assert archive.objects.read_bytes(record.plan_ref)
    assert record.snapshot_ref and archive.objects.read_bytes(record.snapshot_ref)
    assert record.authorization_ref and archive.objects.read_bytes(record.authorization_ref)


def test_interruption_keeps_partial_row_and_names_unavailable_candidate(tmp_path: Path) -> None:
    archive, coordinate = _open(tmp_path)
    source = ObjectStore(tmp_path / "source")
    before = (archive.directory / "index.json").read_bytes()
    assert archive.read(coordinate.id).completion_status == "dispatched"
    settled = archive.settle_attempt(coordinate.id, source=source,
                                     interruption="operator interrupted")
    assert settled.completion_status == "interrupted"
    assert settled.candidate.patch_ref is None
    assert any("CandidateUnavailable" in error for error in settled.errors)
    assert before != (archive.directory / "index.json").read_bytes()
    assert archive.read(coordinate.id) == settled
    assert AttemptArchive.open_existing("run-1", tmp_path / "runs").read(
        coordinate.id
    ) == settled
    assert all(path.stat().st_size for path in (archive.directory / "objects").rglob("*"
                                                  ) if path.is_file())


def test_infrastructure_failure_preserves_partial_trace(tmp_path: Path) -> None:
    archive, coordinate = _open(tmp_path)
    failure = archive.fail_attempt(
        coordinate.id, cause="container_start",
        trace=canonical_json({"events": [{"kind": "container_start_failure"}]}),
    )
    assert failure.completion_status == "failed"
    assert failure.worker_trace_ref is not None
    assert failure.candidate.patch_ref is None
    assert "CandidateUnavailable" in failure.errors[-1]
    assert archive.read(coordinate.id) == failure


def test_unlisted_credentials_are_redacted_before_persistence(tmp_path: Path) -> None:
    archive, coordinate = _open(tmp_path)
    trace = canonical_json({
        "x-api-key": "unlisted-token", "api_key": "another-unlisted-token",
        "nested": {"access_token": "nested-token"},
        "messages": ["Basic dXNlcjpwYXNz", "sk-standalone12345"],
    })
    failure = archive.fail_attempt(coordinate.id, cause="provider_error", trace=trace)
    assert failure.worker_trace_ref is not None
    assert archive.objects.read_bytes(failure.worker_trace_ref) == canonical_json({
        "redacted_header": "[REDACTED]", "nested": {
            "redacted_header": "[REDACTED]",
        }, "messages": ["[REDACTED-BASIC]", "[REDACTED-API-KEY]"],
    })
    for path in archive.directory.rglob("*"):
        if path.is_file():
            data = path.read_bytes()
            assert b"unlisted-token" not in data
            assert b"nested-token" not in data
            assert b"dXNlcjpwYXNz" not in data
            assert b"sk-standalone12345" not in data
            assert b"x-api-key" not in data


def test_failed_attempt_rejects_redacted_recovery_patch(tmp_path: Path) -> None:
    archive, coordinate = _open(tmp_path)
    failure = archive.fail_attempt(
        coordinate.id, cause="container_stop",
        workspace_patch=b"diff --git a/src/a b/src/a\n+publication-secret\n",
    )
    assert failure.candidate.patch_ref is None
    assert failure.candidate.recoverable_workspace_ref is None
    assert "CandidateRedacted: candidate patch contained a credential" in failure.errors
    assert "CandidateUnavailable: no patch or recoverable workspace" in failure.errors
    assert all(b"publication-secret" not in path.read_bytes()
               for path in archive.directory.rglob("*") if path.is_file())


def test_evaluator_details_and_grader_output_resolve_from_archive(tmp_path: Path) -> None:
    archive, coordinate = _open(tmp_path)
    source = ObjectStore(tmp_path / "source")
    grader_ref = str(source.publish_json({
        "groups": {"visible": {"status": "failed", "stdout": "publication-secret"}},
    }))
    detail_ref = str(source.publish_json({
        "groups": {"visible": {"status": "failed", "cause": "assertion"}},
        "evaluator_record_ref": grader_ref,
    }))
    evidence_ref = str(source.publish_json({
        "verdict": {"value": "incorrect"},
        "payload": {"detail_refs": [detail_ref]},
        "source_references": [detail_ref],
    }))
    outcome = ExecutionOutcome(
        run_id="run-1", plan_ref=archive.read(coordinate.id).plan_ref,
        started_at="2026-01-01T00:00:00Z", completed_at="2026-01-01T00:00:01Z",
        coordinate=coordinate, status="failed", input_ref=SHA,
        error_type="CandidateTrialError", error_message="worker stopped",
    )
    outcome_ref = str(source.publish_json(outcome.model_dump(mode="json")))
    manifest = RunManifest(
        run_id="run-1", plan_ref=archive.read(coordinate.id).plan_ref, status="complete",
        execution_records={coordinate.id: outcome_ref},
        evaluation_records={f"{coordinate.id}:correctness:e0": evidence_ref},
        missing_coordinates=(),
    )
    settled = archive.settle_attempt(
        coordinate.id, source=source,
        manifest_ref=str(source.publish_json(manifest.model_dump(mode="json"))),
    )
    assert len(settled.evaluator_output_refs) == 1
    archived_evidence = json.loads(archive.objects.read_bytes(
        settled.evaluator_output_refs[0]
    ))
    archived_detail_ref = archived_evidence["payload"]["detail_refs"][0]
    assert archived_detail_ref in archived_evidence["source_references"]
    archived_detail = json.loads(archive.objects.read_bytes(archived_detail_ref))
    archived_grader = json.loads(archive.objects.read_bytes(
        archived_detail["evaluator_record_ref"]
    ))
    assert archived_detail["groups"]["visible"]["status"] == "failed"
    assert archived_grader["groups"]["visible"]["stdout"] == "[REDACTED]"
    assert all(b"publication-secret" not in path.read_bytes()
               for path in archive.directory.rglob("*") if path.is_file())


def test_sealed_candidate_triple_and_redaction(tmp_path: Path) -> None:
    secret = "publication-secret"
    archive, coordinate = _open(tmp_path, secret)
    source = ObjectStore(tmp_path / "source")
    patch = b"diff --git a/src/a b/src/a\n+value\n"
    patch_ref = _envelope(source, "candidate.patch", patch)
    result_ref = _envelope(source, "result.json", canonical_json({
        "tree_digest": TREE, "baseline_tree_digest": BASE,
    }))
    trajectory_ref = _envelope(source, "trajectory.json", canonical_json({
        "messages": [{"role": "user", "content": secret}],
        "turns": [{"request_id": "req-1", "tool_calls": [{
            "name": "write_file", "authorization": secret,
        }]}],
        "events": [], "actual_usage": {"prompt_tokens": 1,
                                      "completion_tokens": 2, "requests": 1},
    }))
    output_ref = str(source.publish_json({
        "patch_ref": patch_ref, "result_ref": result_ref,
        "raw_trajectory_ref": trajectory_ref,
    }))
    outcome = ExecutionOutcome(
        run_id="run-1", plan_ref=archive.read(coordinate.id).plan_ref,
        started_at="2026-01-01T00:00:00Z",
        completed_at="2026-01-01T00:00:01Z", coordinate=coordinate,
        status="succeeded", input_ref=SHA, output_ref=output_ref,
    )
    outcome_ref = str(source.publish_json(outcome.model_dump(mode="json")))
    manifest = RunManifest(
        run_id="run-1", plan_ref=archive.read(coordinate.id).plan_ref,
        status="complete",
        execution_records={coordinate.id: outcome_ref}, evaluation_records={},
        missing_coordinates=(),
    )
    manifest_ref = str(source.publish_json(manifest.model_dump(mode="json")))
    settled = archive.settle_attempt(coordinate.id, source=source,
                                     manifest_ref=manifest_ref)
    assert settled.candidate.patch_ref == digest_bytes(patch)
    assert archive.objects.read_bytes(settled.candidate.patch_ref) == patch
    assert (settled.candidate.final_tree_digest,
            settled.candidate.baseline_tree_digest) == (TREE, BASE)
    assert settled.request_ids == ("req-1",)
    assert settled.price.unknown_cost is True
    assert settled.completion_status == "succeeded"
    for path in archive.directory.rglob("*"):
        if path.is_file():
            data = path.read_bytes().lower()
            assert secret.encode() not in data
            assert b'"authorization"' not in data
            assert b"x-api-key" not in data
    assert json.loads((archive.directory / "index.json").read_bytes())[coordinate.id]


def test_timeout_retains_last_workspace_patch_and_trace(tmp_path: Path) -> None:
    archive, coordinate = _open(tmp_path)
    source = ObjectStore(tmp_path / "source")
    patch = b"diff --git a/src/a b/src/a\n+unfinished\n"
    patch_ref = _envelope(source, "stopped/candidate.patch", patch)
    trajectory_ref = _envelope(source, "trajectory.json", canonical_json({
        "messages": [], "turns": [],
        "events": [{"kind": "stopped", "cause": "agent_deadline"}],
    }))
    trace_ref = str(source.publish_json({"artifact_refs": {
        "stopped/candidate.patch": patch_ref, "trajectory.json": trajectory_ref,
    }}))
    outcome = ExecutionOutcome(
        run_id="run-1", plan_ref=archive.read(coordinate.id).plan_ref,
        started_at="2026-01-01T00:00:00Z",
        completed_at="2026-01-01T00:15:00Z", coordinate=coordinate,
        status="failed", input_ref=SHA, trace_ref=trace_ref,
        error_type="CandidateTrialError", error_message="agent deadline",
    )
    outcome_ref = str(source.publish_json(outcome.model_dump(mode="json")))
    manifest = RunManifest(
        run_id="run-1", plan_ref=archive.read(coordinate.id).plan_ref,
        status="complete",
        execution_records={coordinate.id: outcome_ref}, evaluation_records={},
        missing_coordinates=(),
    )
    manifest_ref = str(source.publish_json(manifest.model_dump(mode="json")))
    settled = archive.settle_attempt(coordinate.id, source=source,
                                     manifest_ref=manifest_ref)
    assert settled.completion_status == "failed"
    assert settled.completion_cause == "agent_deadline"
    assert settled.candidate.recoverable_workspace_ref == digest_bytes(patch)
    assert archive.objects.read_bytes(settled.candidate.patch_ref or "") == patch
    assert settled.worker_trace_ref and settled.trajectory_ref


def test_model_free_bridge_submission_reaches_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("code_extension.bridge.observed_image_digest", lambda _image: SHA)
    monkeypatch.setattr("code_extension.probe.observed_image_digest", lambda _image: SHA)
    fixture = load_scenario("dispatch-handler")
    manifest = FixtureManifestV3.model_validate_json(
        (Path(__file__).resolve().parents[1] / "fixtures" / "dispatch-handler"
         / "qualification" / "manifest.json").read_bytes()
    )
    path = "src/domain/run-event.ts"
    changed = fixture.repository[path] + "\n// scripted archive probe\n"
    bridge = _scripted_client(fixture, manifest, "image", tmp_path / "trial", [
        ("write_file", {"path": path, "content": changed}),
    ])
    bridge.sandbox_factory = FakeSandbox
    result, trajectory, config, report = _run_script(bridge, fixture, "image")
    assert [call["name"] for turn in trajectory["turns"]
            for call in turn["tool_calls"]] == ["write_file", "submit_output"]
    source = ObjectStore(tmp_path / "source")
    output_ref = str(source.publish_json({
        "patch_ref": _envelope(source, "candidate.patch", result.artifacts["candidate.patch"]),
        "result_ref": _envelope(source, "result.json", result.artifacts["result.json"]),
        "raw_trajectory_ref": _envelope(source, "trajectory.json",
                                         result.artifacts["trajectory.json"]),
    }))
    coordinate = CellCoordinate(subject_id=fixture.subject_id, arm_id="baseline",
                                worker_repeat=0, realization_ref=SHA)
    plan_ref = str(source.publish_json({"plan": "scripted"}))
    outcome = ExecutionOutcome(
        run_id="scripted", plan_ref=plan_ref, started_at="2026-01-01T00:00:00Z",
        completed_at="2026-01-01T00:00:01Z", coordinate=coordinate,
        status="succeeded", input_ref=SHA, output_ref=output_ref,
    )
    outcome_ref = str(source.publish_json(outcome.model_dump(mode="json")))
    run_manifest = RunManifest(
        run_id="scripted", plan_ref=plan_ref, status="complete",
        execution_records={coordinate.id: outcome_ref}, evaluation_records={},
        missing_coordinates=(),
    )
    manifest_ref = str(source.publish_json(run_manifest.model_dump(mode="json")))
    archive = AttemptArchive("scripted", tmp_path / "archive")
    archive.begin_attempt(coordinate=coordinate, plan_ref=plan_ref, snapshot_ref=None,
                          authorization_ref=None, configuration=config,
                          sidecar=fixture.sidecar, source=source)
    settled = archive.settle_attempt(coordinate.id, source=source,
                                     manifest_ref=manifest_ref)
    assert settled.candidate.patch_ref == result.outcome.patch_ref
    assert settled.candidate.final_tree_digest == report["tree_digest"]
    assert settled.candidate.baseline_tree_digest == report["baseline_tree_digest"]
    assert archive.objects.read_bytes(settled.candidate.patch_ref or "") == (
        result.artifacts["candidate.patch"]
    )
