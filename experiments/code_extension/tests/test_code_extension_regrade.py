"""Offline regrading preserves the first observation and verifies exported evidence."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from code_extension import diagnose, run
from code_extension.tests.test_code_extension_ledger import _manifest, _outcome, _plan
from workflow_edit.evaluation import WorkerCandidate

from assay.store import ObjectStore
from assay.verify import export_bundle, verify_bundle

LEGACY_REF = "sha256:7f60b6946084c4ef35c81fea380daa2c669a1f634e8edc85b11cf79cf97a3803"
LEGACY_BUNDLE = Path(__file__).resolve().parents[3] / "tests/fixtures/legacy-0.1.0-bundle/bundle"


def _object_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in (root / "objects").rglob("*")
        if path.is_file()
    }


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

    async def fake_evaluate(**_: object) -> SimpleNamespace:
        return SimpleNamespace(verdict="incorrect", cause="test_failure", groups=())

    monkeypatch.setattr(diagnose, "evaluate_scenario_candidate", fake_evaluate)
    first = diagnose.regrade_archive(tmp_path / "archive", "sha256:" + "1" * 64, tmp_path / "out")
    second = diagnose.regrade_archive(tmp_path / "archive", "sha256:" + "2" * 64, tmp_path / "out")
    assert len(first) == len(second) == 1 and first != second
    first_image = json.loads(first[0].read_text())["image_digest"]
    second_image = json.loads(second[0].read_text())["image_digest"]
    assert first_image != second_image
    assert store.read_bytes(manifest_ref) == manifest_bytes
    assert _object_bytes(run_dir) == originals


def test_shared_export_detects_tamper_and_extra_object(tmp_path: Path) -> None:
    exported = export_bundle(ObjectStore(LEGACY_BUNDLE), LEGACY_REF, tmp_path / "bundle")
    assert verify_bundle(exported, LEGACY_REF) == ()
    target = next(exported.objects.iterdir())
    original = target.read_bytes()
    target.write_bytes(b"tampered")
    assert verify_bundle(exported, LEGACY_REF)
    target.write_bytes(original)
    exported.publish_bytes(b"extra object")
    assert any(f.code == "bundle_closure" for f in verify_bundle(exported, LEGACY_REF))


def test_empty_offline_commands_never_prepare_a_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def forbidden(*_: object, **__: object) -> None:
        raise AssertionError("model path reached")

    monkeypatch.setattr(run, "_build", forbidden)
    monkeypatch.setattr(run, "execute", forbidden)
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
