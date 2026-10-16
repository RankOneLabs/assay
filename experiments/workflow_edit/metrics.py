"""The study's metric step: code metrics for a fixture tree before and after a patch.

TypeScript is typechecked as the fixture typechecks itself (spec part 2,
section 8.3): the runtime image's locked tree (`integrations/pier/workflow_edit`,
TypeScript 5.9.3, zod, @types/bun), installed once by ``npm ci`` outside the
metric step, and each tree's own ``tsconfig.json``. Measuring never installs or
fetches anything. Module/import edges and cycles come from the pinned
dependency-cruiser graph, which keeps type-only imports.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from assay.code_metrics import CodeMetricsComparison, CodeMetricsConfig, compare
from assay.code_metrics.cli_snapshot import snapshot_directory
from assay.code_metrics.toolchain import (
    TypeScriptToolchain,
    dependencies_directory,
    install_typescript_dependencies,
)
from workflow_edit.fixture import SmokeEditFixture, materialize

ROOT = Path(__file__).resolve().parents[2]
# The same manifests the image's Node stage installs; the fixture repository
# carries byte-identical copies (test_smoke_edit_fixture).
LOCK = ROOT / "integrations" / "pier" / "workflow_edit"
TYPESCRIPT = "5.9.3"


def install_toolchain(target: Path | None = None, *, offline: bool = False) -> Path:
    """Install the image's locked tree, by default into the per-user cache."""
    return install_typescript_dependencies(LOCK, target, offline=offline)


def metrics_config(dependencies: Path | None = None) -> CodeMetricsConfig:
    directory = dependencies_directory(LOCK) if dependencies is None else dependencies
    return CodeMetricsConfig(typescript_toolchain=TypeScriptToolchain(directory))


def measure_pair(
    before: Path, after: Path, *, dependencies: Path | None = None
) -> CodeMetricsComparison:
    """Compare two checked-out trees with the fixture's toolchain."""
    return compare(
        snapshot_directory(before)[0],
        snapshot_directory(after)[0],
        config=metrics_config(dependencies),
    )


def measure_patch(
    fixture: SmokeEditFixture, patch: str, *, dependencies: Path | None = None
) -> CodeMetricsComparison:
    """Compare the fixture's repository with the same tree after ``patch``."""
    with tempfile.TemporaryDirectory() as directory:
        before, after = Path(directory) / "before", Path(directory) / "after"
        materialize(before, fixture.repository)
        materialize(after, fixture.repository, patch)
        return measure_pair(before, after, dependencies=dependencies)
