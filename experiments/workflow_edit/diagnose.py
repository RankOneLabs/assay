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
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from workflow_edit.fixture import SmokeEditFixture, load_fixture

_FAIL = re.compile(r"^\(fail\) (.*?)(?: \[[\d.]+ms\])?$", re.MULTILINE)
_TS_ERROR = re.compile(r"^(\S+\.ts)\(\d+,\d+\): error (TS\d+): (.*)$", re.MULTILINE)
TYPECHECK = ("tsc", "--noEmit", "-p", "tsconfig.json")


def _materialize(root: Path, fixture: SmokeEditFixture, patch: str) -> None:
    for path, text in fixture.repository.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    subprocess.run(
        ["patch", "-p1", "--quiet", "--batch"], cwd=root, input=patch.encode(), check=True
    )
    for group in fixture.groups:
        for path, text in group.files.items():
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")


def _run(image: str, root: Path, argv: Sequence[str]) -> str:
    completed = subprocess.run(
        [
            "docker", "run", "--rm", "--network", "none", "--read-only",
            "--tmpfs", "/tmp:size=256m", "--user", "1000:1000",
            "--env", "HOME=/tmp", "--env", "BUN_INSTALL_CACHE_DIR=/tmp/bun",
            "--volume", f"{root}:/w:ro", "--workdir", "/w",
            "--entrypoint", argv[0], image, *argv[1:],
        ],
        capture_output=True, text=True, timeout=300, check=False,
    )
    return completed.stdout + completed.stderr


def diagnose_candidate(
    image: str, fixture: SmokeEditFixture, patch: str, groups: Mapping[str, Mapping[str, Any]],
    *, scratch: Path,
) -> dict[str, Any]:
    root = Path(tempfile.mkdtemp(dir=scratch))
    try:
        _materialize(root, fixture, patch)
        if any(g.get("cause") == "typecheck_nonzero_exit" for g in groups.values()):
            errors = _TS_ERROR.findall(_run(image, root, TYPECHECK))
            return {"typecheck_errors": [
                {"file": file, "code": code, "message": message}
                for file, code, message in errors[:5]
            ]}
        commands: dict[str, tuple[str, ...]] = {
            group.name: group.command for group in fixture.groups
        }
        return {"failing_tests": {
            name: sorted(set(_FAIL.findall(_run(image, root, commands[name]))))
            for name, group in sorted(groups.items()) if group["status"] == "failed"
        }}
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
