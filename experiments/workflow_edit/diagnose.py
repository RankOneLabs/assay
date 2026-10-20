"""Name the tests behind each failed correctness group in the wf-13 smoke.

The evaluator records a verdict and one cause per group; it keeps no test
output. This replays every failed group of every evaluated candidate in the
same pinned image, with no network and the tree mounted read-only, and keeps
only the names of the failing tests (or the first typecheck errors). It is a
diagnosis of verdicts already recorded, never a second grade: the verdicts in
SMOKE.md are the evaluator's.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from workflow_edit.fixture import SmokeEditFixture, load_fixture, materialize

_FAIL = re.compile(r"^\(fail\) (.*?)(?: \[[\d.]+ms\])?$", re.MULTILINE)
_TS_ERROR = re.compile(r"^(\S+\.ts)\(\d+,\d+\): error (TS\d+): (.*)$", re.MULTILINE)
TYPECHECK = ("tsc", "--noEmit", "-p", "tsconfig.json")


def _install_tests(root: Path, fixture: SmokeEditFixture) -> None:
    for group in fixture.groups:
        if group.restores:
            continue
        for path, text in group.files.items():
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")


def _reset_visible_tests(root: Path, fixture: SmokeEditFixture) -> None:
    visible = root / "tests" / "visible"
    if visible.exists():
        shutil.rmtree(visible)
    for group in fixture.groups:
        if group.restores:
            for path, text in group.files.items():
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text, encoding="utf-8")


def _run(image: str, root: Path, argv: Sequence[str]) -> str:
    # The evaluator's own sandbox limits: this re-executes candidate code.
    name = "assay-workflow-diagnose-" + uuid.uuid4().hex
    try:
        completed = subprocess.run(
            [
                "docker", "run", "--rm", "--name", name, "--pull=never",
                "--network=none", "--read-only", "--cap-drop=ALL",
                "--security-opt=no-new-privileges", "--pids-limit", "64",
                "--memory", "512m", "--cpus", "1",
                "--tmpfs", "/tmp:rw,nosuid,nodev,size=256m", "--user", "1000:1000",
                "--env", "HOME=/tmp", "--env", "BUN_INSTALL_CACHE_DIR=/tmp/bun",
                "--volume", f"{root}:/w:ro", "--workdir", "/w",
                "--entrypoint", argv[0], image, *argv[1:],
            ],
            capture_output=True, text=True, timeout=300, check=False,
        )
    finally:
        # A timeout kills only the client; the container would keep running.
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=False)
    return completed.stdout + completed.stderr


def diagnose_candidate(
    image: str,
    fixture: SmokeEditFixture,
    patch: str,
    groups: Mapping[str, Mapping[str, Any]],
    *,
    scratch: Path,
) -> dict[str, Any]:
    root = Path(tempfile.mkdtemp(dir=scratch))
    # mkdtemp is 0700; the container user must be able to traverse the mount.
    root.chmod(0o755)
    try:
        preflight_causes = {
            g["cause"]
            for g in groups.values()
            if isinstance(g.get("cause"), str)
            and (
                g["cause"].startswith(("typecheck_", "build_"))
                or g["cause"]
                in {
                    "patch_rejected",
                    "test_path_collision",
                    "candidate_tree_digest_mismatch",
                    "toolchain_unavailable",
                    "sandbox_protocol_error",
                }
            )
        }
        cause = min(preflight_causes) if preflight_causes else None
        if cause is not None and cause != "typecheck_nonzero_exit":
            return {"preflight_cause": cause}
        materialize(root, fixture.repository, patch)
        _reset_visible_tests(root, fixture)
        if cause == "typecheck_nonzero_exit":
            errors = _TS_ERROR.findall(_run(image, root, TYPECHECK))
            return {
                "preflight_cause": cause,
                "typecheck_errors": [
                    {"file": file, "code": code, "message": message}
                    for file, code, message in errors[:5]
                ],
            }
        _install_tests(root, fixture)
        commands: dict[str, tuple[str, ...]] = {
            group.name: group.command for group in fixture.groups
        }
        return {
            "failing_tests": {
                name: sorted(set(_FAIL.findall(_run(image, root, commands[name]))))
                for name, group in sorted(groups.items())
                if group["status"] == "failed"
            }
        }
    finally:
        shutil.rmtree(root, ignore_errors=True)


def diagnose(smoke: Mapping[str, Any], *, scratch: Path) -> dict[str, Any]:
    fixture = load_fixture()
    image = smoke["image"]
    cells = {}
    for cell_id, record in sorted(smoke["evaluations"].items()):
        if record["verdict"] == "correct":
            continue
        patch = smoke["cells"][cell_id]["patch"]
        cells[cell_id] = diagnose_candidate(
            image, fixture, patch, record["groups"], scratch=scratch
        )
    return {
        "image": image,
        "basis": "replay of evaluator-failed groups; verdicts are the evaluator's",
        "cells": cells,
    }
