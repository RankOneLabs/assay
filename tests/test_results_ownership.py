"""Keep generated result and receipt material out of the source tree."""

from __future__ import annotations

import subprocess
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_BUNDLES = {
    PurePosixPath("evidence/typesafe-relevance-arms-2026-09"),
    PurePosixPath("evidence/typesafe-relevance-census-2026-09"),
    PurePosixPath("evidence/typesafe-relevance-fitted-rerun-2026-09"),
    PurePosixPath("evidence/typesafe-relevance-primary-2026-09"),
}
RUN_RECEIPTS_PROSE = {
    PurePosixPath("README.md"),
    PurePosixPath("experiments/README.md"),
    PurePosixPath("experiments/typesafe_relevance/README.md"),
    PurePosixPath("experiments/typesafe_relevance/run_packet.py"),
    PurePosixPath("tests/conftest.py"),
    PurePosixPath("experiments/conftest.py"),
    PurePosixPath("tests/test_results_ownership.py"),
}
RESULT_DIRECTORY_NAMES = {"evidence", "results", "receipts"}


def tracked_files() -> tuple[PurePosixPath, ...]:
    output = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    return tuple(PurePosixPath(item.decode()) for item in output.split(b"\0") if item)


def allowed_bundle(path: PurePosixPath) -> PurePosixPath | None:
    return next(
        (bundle for bundle in ALLOWED_BUNDLES if path == bundle or bundle in path.parents),
        None,
    )


def test_results_are_owned_by_the_receipts_repository() -> None:
    violations: list[str] = []
    paths = tracked_files()
    checksum_parents = {path.parent for path in paths if path.name == "checksums.json"}

    for path in paths:
        bundle = allowed_bundle(path)
        result_directory = any(part in RESULT_DIRECTORY_NAMES for part in path.parts[:-1])
        beneath_checksums = any(
            parent == path.parent or parent in path.parents for parent in checksum_parents
        )
        if (result_directory or beneath_checksums) and bundle is None:
            violations.append(f"result material outside allowlist: {path}")

        if path not in RUN_RECEIPTS_PROSE and bundle is None:
            content = (ROOT / path).read_bytes()
            if b"run-receipts" in content:
                violations.append(f"run-receipts reference outside prose allowlist: {path}")

    assert violations == []
