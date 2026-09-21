from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_ROOT = REPOSITORY_ROOT / "evidence"


def _assert_digest(content: bytes, expected: str, path: str) -> None:
    assert hashlib.sha256(content).hexdigest() == expected, path


def _verify_census_manifest(manifest_path: Path, manifest: dict[str, object]) -> None:
    assert manifest["algorithm"] == "sha256"
    evidence_files = manifest["evidence_files"]
    source_files = manifest["source_files_at_commit"]
    assert isinstance(evidence_files, dict)
    assert isinstance(source_files, dict)

    for name, digest in sorted(evidence_files.items()):
        assert isinstance(name, str) and isinstance(digest, str)
        _assert_digest((manifest_path.parent / name).read_bytes(), digest, name)

    commit = manifest["source_commit"]
    assert isinstance(commit, str)
    for name, digest in sorted(source_files.items()):
        assert isinstance(name, str) and isinstance(digest, str)
        blob = subprocess.run(
            ["git", "show", f"{commit}:{name}"],
            cwd=REPOSITORY_ROOT,
            check=True,
            capture_output=True,
        ).stdout
        _assert_digest(blob, digest, name)


def _verify_flat_manifest(manifest_path: Path, manifest: dict[str, object]) -> None:
    for name, digest in sorted(manifest.items()):
        assert isinstance(digest, str)
        _assert_digest((manifest_path.parent / name).read_bytes(), digest, name)


def test_all_evidence_manifests(optional_run_receipts_checkout: Path | None) -> None:
    roots = {root.resolve() for root in (EVIDENCE_ROOT, optional_run_receipts_checkout) if root}
    roots = {root for root in roots if root.is_dir()}
    if not roots:
        pytest.skip("neither in-tree evidence nor ASSAY_RUN_RECEIPTS is present")

    manifests = sorted(path for root in roots for path in root.rglob("checksums.json"))
    assert manifests
    for manifest_path in manifests:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if "evidence_files" in manifest:
            _verify_census_manifest(manifest_path, manifest)
        else:
            _verify_flat_manifest(manifest_path, manifest)
