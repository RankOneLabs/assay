"""A clean core wheel installs and runs without Jig; the legacy path is lazy."""

from __future__ import annotations

from test_review_packaging import (
    InstalledWheel,
    _installed_environment,
    _run,
    installed_wheel,  # noqa: F401 -- reused as a pytest fixture
)


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
