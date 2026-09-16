"""A clean core wheel installs and runs without Jig; the legacy path is lazy."""

from __future__ import annotations

from pathlib import Path

from test_review_packaging import (
    InstalledWheel,
    _installed_environment,
    _run,
    installed_wheel,  # noqa: F401 -- reused as a pytest fixture
)

FIXTURE_BUNDLE = Path(__file__).parent / "fixtures" / "legacy-0.1.0-bundle" / "bundle"
FIXTURE_MANIFEST_REF = "sha256:7f60b6946084c4ef35c81fea380daa2c669a1f634e8edc85b11cf79cf97a3803"

REPORT_FIXTURE_BUNDLE = Path(__file__).parent / "fixtures" / "legacy-0.1.0-report-bundle" / "bundle"
REPORT_FIXTURE_REF = "sha256:c89c984a842bd43d60f6b504b1465e76fda06554981f7fe20e97e9a1b329b91c"


def test_installed_wheel_has_no_jig(installed_wheel: InstalledWheel) -> None:  # noqa: F811
    result = _run(
        [installed_wheel.python, "-c", "import jig"],
        cwd=installed_wheel.outside,
        env=_installed_environment(),
    )
    assert result.returncode != 0
    assert "No module named 'jig'" in result.stderr


def test_core_modules_import_without_jig(installed_wheel: InstalledWheel) -> None:  # noqa: F811
    program = """
import assay
import assay.planning
import assay.verify
import assay.report_engine
import assay.references
import assay.schema_export
import assay.protocols
import assay.review.model
import assay.review.index
import assay.review.read
import assay.review.export
import assay.investigations.consistency
import assay.investigations.dry_common
import assay.investigations.realistic_fixtures
import assay.investigations.dry_experiment
import assay.investigations.pilot
import assay.investigations.realistic_pilot
import assay.adapters
import assay.adapters.openrouter_policy
print("ok")
"""
    result = _run(
        [installed_wheel.python, "-c", program],
        cwd=installed_wheel.outside,
        env=_installed_environment(),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ok" in result.stdout


def test_jig_only_paths_fail_actionably_without_the_legacy_extra(
    installed_wheel: InstalledWheel,  # noqa: F811
) -> None:
    program = """
import assay.adapters
try:
    assay.adapters.JigWorker
except ModuleNotFoundError as error:
    print(f"JigWorker: {error}")

import assay.investigations.pilot as pilot
try:
    pilot._import_legacy_worker_stack()
except ModuleNotFoundError as error:
    print(f"pilot: {error}")

import assay.investigations.dry_experiment as dry_experiment
try:
    dry_experiment.haiku_dry_settings()
except ModuleNotFoundError as error:
    print(f"dry_experiment: {error}")

import assay.investigations.realistic_pilot as realistic_pilot
try:
    realistic_pilot.realistic_haiku_settings()
except ModuleNotFoundError as error:
    print(f"realistic_pilot: {error}")
"""
    result = _run(
        [installed_wheel.python, "-c", program],
        cwd=installed_wheel.outside,
        env=_installed_environment(),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    for name in ("JigWorker", "pilot", "dry_experiment", "realistic_pilot"):
        line = next(line for line in result.stdout.splitlines() if line.startswith(f"{name}: "))
        assert "assay[legacy]" in line


def test_fixed_legacy_bundle_verifies_in_a_jig_free_install(
    installed_wheel: InstalledWheel,  # noqa: F811
) -> None:
    program = """
import sys
from assay.store import ObjectStore
from assay.verify import verify_bundle, verify_manifest

store = ObjectStore(sys.argv[1])
root = sys.argv[2]
assert verify_manifest(store, root) == (), verify_manifest(store, root)
assert verify_bundle(store, root) == (), verify_bundle(store, root)
print("ok")
"""
    result = _run(
        [installed_wheel.python, "-c", program, FIXTURE_BUNDLE, FIXTURE_MANIFEST_REF],
        cwd=installed_wheel.outside,
        env=_installed_environment(),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ok" in result.stdout


def test_fixed_legacy_report_recomputes_identically_in_a_jig_free_install(
    installed_wheel: InstalledWheel,  # noqa: F811
) -> None:
    program = """
import json
import sys
from assay.canonical import canonical_json, digest_bytes
from assay.models import ReportConfig
from assay.report_engine import build_report
from assay.store import ObjectStore
from assay.verify import verify_bundle, verify_report

store = ObjectStore(sys.argv[1])
root = sys.argv[2]
assert verify_report(store, root) == (), verify_report(store, root)
assert verify_bundle(store, root) == (), verify_bundle(store, root)

report = json.loads(store.read_bytes(root))
config = ReportConfig.model_validate(json.loads(store.read_bytes(report["config_ref"])))
recomputed = build_report(store, config)
assert recomputed == report
assert digest_bytes(canonical_json(recomputed)) == root
print("ok")
"""
    result = _run(
        [installed_wheel.python, "-c", program, REPORT_FIXTURE_BUNDLE, REPORT_FIXTURE_REF],
        cwd=installed_wheel.outside,
        env=_installed_environment(),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ok" in result.stdout
