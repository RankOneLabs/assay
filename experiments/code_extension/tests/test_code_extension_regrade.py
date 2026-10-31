"""Offline regrading preserves the first observation and verifies exported evidence."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest
from code_extension import config, diagnose, run
from code_extension.tests.test_code_extension_ledger import _manifest, _outcome, _plan
from workflow_edit.evaluation import WorkerCandidate

from assay.adapters import smithers
from assay.investigations.workflow_correctness import (
    GroupResult,
    PreflightResult,
    RejectedChange,
    WorkflowCorrectnessResult,
)
from assay.models import RunManifest
from assay.store import ObjectStore
from assay.verify import export_bundle, verify_bundle, verify_manifest


def _object_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in (root / "objects").rglob("*")
        if path.is_file()
    }


def _forbid_model_constructors(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*_: object, **__: object) -> None:
        raise AssertionError("offline command constructed a model route, client, or completion")

    for route in (config.ModelRoute, run.bridge_protocol.ModelRoute):
        monkeypatch.setattr(route, "__init__", forbidden)
        monkeypatch.setattr(route, "model_validate", forbidden)
    monkeypatch.setattr(run.SmithersFactory, "__init__", forbidden)
    monkeypatch.setattr(run.SmithersFactory, "create", forbidden)
    monkeypatch.setattr(smithers.SmithersClient, "__init__", forbidden)
    monkeypatch.setattr(run.SmithersTurnCompletion, "__init__", forbidden)


def test_regrade_appends_distinct_image_records_without_changing_original(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, plan, authorization = _plan(tmp_path / "source")
    execution_ref, _ = _outcome(store, plan, authorization, success=True, trace={})
    manifest_ref = _manifest(store, plan, authorization, execution_ref, passed=True)
    manifest_bytes = store.read_bytes(manifest_ref)
    run_dir = tmp_path / "archive" / "runs" / "sample"
    shutil.copytree(store.root, run_dir)
    (run_dir / "run.json").write_text(
        json.dumps(
            {
                "plan_ref": authorization,
                "manifest_ref": manifest_ref,
            }
        ),
        encoding="utf-8",
    )
    originals = _object_bytes(run_dir)
    monkeypatch.setattr(
        diagnose,
        "worker_candidate",
        lambda *_: WorkerCandidate(
            patch=b"",
            tree_digest="sha256:" + "a" * 64,
            baseline_tree_digest="sha256:" + "b" * 64,
        ),
    )

    async def fake_evaluate(**_: object) -> WorkflowCorrectnessResult:
        return WorkflowCorrectnessResult(
            verdict="incorrect",
            cause="group_failure",
            groups=(
                GroupResult(
                    "visible_regression",
                    "failed",
                    "nonzero_exit",
                    stdout="one assertion failed",
                    stderr="test process exited",
                    exit_status=1,
                    timeout_s=120.0,
                ),
            ),
            preflight=PreflightResult("passed"),
            attribution="candidate_failure",
            rejected_changes=(
                RejectedChange(
                    "tests/visible/example.test.ts",
                    "restored",
                    "sha256:" + "a" * 64,
                    "sha256:" + "b" * 64,
                ),
            ),
        )

    monkeypatch.setattr(diagnose, "evaluate_scenario_candidate", fake_evaluate)
    _forbid_model_constructors(monkeypatch)
    first = diagnose.regrade_archive(tmp_path / "archive", "sha256:" + "1" * 64, tmp_path / "out")
    second = diagnose.regrade_archive(tmp_path / "archive", "sha256:" + "2" * 64, tmp_path / "out")
    assert len(first) == len(second) == 1 and first != second
    first_record = json.loads(first[0].read_text())
    first_image = first_record["image_digest"]
    second_image = json.loads(second[0].read_text())["image_digest"]
    assert first_image != second_image
    assert first_record["groups"] == [
        {
            "name": "visible_regression",
            "status": "failed",
            "cause": "nonzero_exit",
            "stdout": "one assertion failed",
            "stderr": "test process exited",
            "exit_status": 1,
            "timeout_s": 120.0,
        }
    ]
    assert first_record["preflight"] == {"status": "passed", "cause": None}
    assert first_record["attribution"] == "candidate_failure"
    assert first_record["rejected_changes"] == [
        {
            "path": "tests/visible/example.test.ts",
            "disposition": "restored",
            "baseline_digest": "sha256:" + "a" * 64,
            "candidate_digest": "sha256:" + "b" * 64,
        }
    ]
    assert store.read_bytes(manifest_ref) == manifest_bytes
    assert _object_bytes(run_dir) == originals


def test_extension_manifest_exports_when_honestly_incomplete_and_rejects_corruption(
    tmp_path: Path,
) -> None:
    store, plan, authorization = _plan(tmp_path / "source")
    missing = tuple(sorted(
        [*(cell.id for cell in plan.cells), *(item.id for item in plan.evaluations)]
    ))
    manifest = RunManifest(
        run_id="run",
        plan_ref=authorization,
        status="incomplete",
        execution_records={},
        evaluation_records={},
        missing_coordinates=missing,
    )
    manifest_ref = str(store.publish_json(manifest.model_dump(mode="json")))
    run_dir = tmp_path / "archive" / "runs" / "sample"
    shutil.copytree(store.root, run_dir)
    (run_dir / "run.json").write_text(
        json.dumps({"plan_ref": authorization, "manifest_ref": manifest_ref}),
        encoding="utf-8",
    )
    archived = ObjectStore(run_dir)
    assert [failure.code for failure in verify_manifest(archived, manifest_ref)] == [
        "incomplete_run"
    ]
    exported = export_bundle(archived, manifest_ref, tmp_path / "bundle")
    assert [failure.code for failure in verify_bundle(exported, manifest_ref)] == [
        "incomplete_run"
    ]
    target = next(exported.objects.iterdir())
    original = target.read_bytes()
    target.write_bytes(b"tampered")
    assert any(
        failure.code != "incomplete_run" for failure in verify_bundle(exported, manifest_ref)
    )
    target.write_bytes(original)
    exported.publish_bytes(b"extra object")
    assert any(f.code == "bundle_closure" for f in verify_bundle(exported, manifest_ref))

    inconsistent = manifest.model_copy(update={"missing_coordinates": missing[1:]})
    inconsistent_ref = str(archived.publish_json(inconsistent.model_dump(mode="json")))
    assert any(
        failure.code == "missing_coordinates"
        for failure in verify_manifest(archived, inconsistent_ref)
    )
    with pytest.raises(ValueError, match="cannot export invalid root"):
        export_bundle(archived, inconsistent_ref, tmp_path / "invalid-bundle")


def test_empty_offline_commands_never_prepare_a_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def forbidden(*_: object, **__: object) -> None:
        raise AssertionError("model path reached")

    monkeypatch.setattr(run, "_build", forbidden)
    monkeypatch.setattr(run, "execute", forbidden)
    _forbid_model_constructors(monkeypatch)
    archive = tmp_path / "empty"
    archive.mkdir()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "code_extension.run",
            "report",
            "--archive",
            str(archive),
            "--output",
            str(tmp_path / "report"),
        ],
    )
    run.main()
    assert len(json.loads(capsys.readouterr().out)) == 3
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "code_extension.run",
            "regrade",
            "--archive",
            str(archive),
            "--image",
            "sha256:" + "1" * 64,
            "--output",
            str(tmp_path / "regrade"),
        ],
    )
    run.main()
    assert json.loads(capsys.readouterr().out) == []
