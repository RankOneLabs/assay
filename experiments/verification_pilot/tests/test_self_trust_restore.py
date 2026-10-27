"""A correct scripted restore reaches the real capture, scope, and grading path."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from verification_pilot.fixtures import OwnershipGroup
from verification_pilot.self_trust.evaluation import measures
from verification_pilot.self_trust.ladder import RUNGS, Rung
from verification_pilot.self_trust.study import self_trust_subjects, subject_id

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "integrations" / "pier" / "src"))
from assay_pier_bridge.paths import (  # noqa: E402
    ArtifactCollectionRejected,
    check_submission_scope,
    regular_tree,
    submission_patch,
)


def _write_tree(root: Path, tree: dict[str, str]) -> None:
    for path, source in tree.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source, encoding="utf-8")


def _capture_restore(root: Path, rung: Rung, group: OwnershipGroup) -> tuple[
    dict[str, bytes], dict[str, bytes], str,
]:
    before, after = root / "before", root / "after"
    _write_tree(before, rung.subject_tree(group))
    _write_tree(after, rung.subject_tree(None))
    captured = submission_patch(before, after)
    return regular_tree(before), regular_tree(after), captured.patch.decode("utf-8")


def _image(rung: Rung) -> str:
    return str(json.loads((rung.logs.parent / f"{rung.name}-check.json").read_text(
        encoding="utf-8"))["image"])


def _require_image(image: str) -> None:
    try:
        daemon = subprocess.run(["docker", "info", "--format", "{{.ServerVersion}}"],
                                capture_output=True, text=True, timeout=30, check=False)
        if daemon.returncode:
            pytest.skip(f"Docker daemon unavailable: {daemon.stderr.strip()}")
        present = subprocess.run(["docker", "image", "inspect", image],
                                 capture_output=True, text=True, timeout=30, check=False)
        if present.returncode:
            pytest.skip(f"pinned Docker image unavailable: {image}")
    except (OSError, subprocess.TimeoutExpired) as error:
        pytest.skip(f"Docker unavailable: {error}")


@pytest.mark.parametrize("rung_name,group", [
    ("rewrite", "group_a"), ("rewrite", "group_b"), ("rewrite", "group_c"),
    ("rewrite0", "group_a"), ("resume146", "group_a"),
])
def test_scripted_restore_is_captured_accepted_and_graded(
    tmp_path: Path, rung_name: str, group: OwnershipGroup,
) -> None:
    rung = RUNGS[rung_name]
    image = _image(rung)
    _require_image(image)
    before, after, patch = _capture_restore(tmp_path, rung, group)
    changed = [path for path in before.keys() | after.keys() if before.get(path) != after.get(path)]
    assert changed == [rung.omission_paths[group]]
    check_submission_scope(before, after, writable_prefixes=rung.writable_prefixes)
    subject = next(item for item in self_trust_subjects()
                   if item.id == subject_id(rung_name, group, group))
    trajectory = {"turns": [{"turn": "T1", "workspace_diff": patch,
                             "submission": {"verdict": "complete"}}]}
    rows = measures(subject, trajectory, image)
    fixed = next(row["result"]["value"] for row in rows
                 if row["turn"] == "final" and row["name"] == "remnant_fixed")
    assert fixed is True


def test_resume146_restore_was_rejected_by_st_v1_scope(tmp_path: Path) -> None:
    before, after, _ = _capture_restore(tmp_path, RUNGS["resume146"], "group_a")
    with pytest.raises(ArtifactCollectionRejected) as rejected:
        check_submission_scope(before, after, writable_prefixes=("src/", "tests/"))
    assert rejected.value.cause == "out_of_scope_edit"
    assert rejected.value.rejected_path == "adapters/claude-code/index.ts"
