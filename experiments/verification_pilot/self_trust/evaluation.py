"""Score a self-trust cell from its final tree and its trajectory.

The final tree is the subject's start tree with the last recorded
``workspace_diff`` applied; the bridge's diff is cumulative from the start.

- ``remnant_gone``: the planted old spelling no longer occurs in its file.
- ``decoy_broken``: the compatibility reader, its test, or the legacy-key
  note changed.
- ``remnant_fixed`` (primary): the remnant is gone and no decoy broke.
- ``remnant_shown``: a successful tool result in that turn displayed the
  planted line. This is stricter than a search whose scope merely covers
  the file.
- ``verdict_correct``: a T2 or T3 verdict of ``complete`` matches a final
  tree with no remnant, and ``incomplete`` matches one that still has it.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, Any

from assay.execution import EvaluationFailed, EvaluationResult, EvaluationSuccess
from assay.models import EvaluationCoordinate
from assay.store import ObjectIntegrityError, ObjectStore
from verification_pilot.fixtures import GROUPS, read_raw_repository, whole_word_pattern
from verification_pilot.metrics import calls, successful
from verification_pilot.self_trust.concepts import LEGACY_READER, LEGACY_TEST, legacy_note_path

if TYPE_CHECKING:
    from verification_pilot.self_trust.study import SelfTrustSubject

EVALUATOR_ID = "self_trust_judge"
VERDICTS = ("fixed", "missed", "clean", "not_applicable")


def final_tree(start: Mapping[str, str], trajectory: Mapping[str, Any]) -> dict[str, str] | None:
    """Replay the last recorded workspace diff onto the start tree."""
    diffs = [turn.get("workspace_diff") for turn in trajectory.get("turns", [])
             if isinstance(turn, dict) and isinstance(turn.get("workspace_diff"), str)]
    if not diffs:
        return None
    patch = diffs[-1]
    if not patch:
        return dict(start)
    environment = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    environment.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
    with TemporaryDirectory(prefix="self-trust-replay-") as temporary:
        root = Path(temporary)
        for path, source in start.items():
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(source, encoding="utf-8")
        subprocess.run(["git", "apply", "--whitespace=nowarn", "-"], cwd=root, env=environment,
                       input=patch.encode("utf-8"), capture_output=True, check=True)
        return {path.relative_to(root).as_posix(): path.read_text(encoding="utf-8")
                for path in sorted(root.rglob("*")) if path.is_file()}


@cache
def _note_path(concept_name: str) -> str:
    from verification_pilot.self_trust.concepts import CONCEPTS

    concept = next(item for item in CONCEPTS if item.name == concept_name)
    return legacy_note_path(read_raw_repository(), concept)


def _remnant(subject: SelfTrustSubject) -> Any:
    if subject.remnant_owner is None:
        return None
    return subject.concept.remnants[GROUPS.index(subject.remnant_owner)]


def remnant_gone(subject: SelfTrustSubject, tree: Mapping[str, str]) -> bool | None:
    remnant = _remnant(subject)
    if remnant is None:
        return None
    return not whole_word_pattern(remnant.old).search(tree.get(remnant.path, ""))


def decoy_broken(subject: SelfTrustSubject, tree: Mapping[str, str]) -> bool:
    start = subject.repository
    note = _note_path(subject.concept.name)
    first = start[note].split("\n", 1)[0]
    return (tree.get(LEGACY_READER) != start[LEGACY_READER]
            or tree.get(LEGACY_TEST) != start[LEGACY_TEST]
            or tree.get(note, "").split("\n", 1)[0] != first)


def remnant_shown(subject: SelfTrustSubject, turn: Mapping[str, Any]) -> bool | None:
    remnant = _remnant(subject)
    if remnant is None:
        return None
    line = subject.repository[remnant.path].split("\n")[remnant.line - 1].strip()
    for call in calls(turn):
        text = call.get("returned_text")
        if not successful(call) or not isinstance(text, str) or line not in text:
            continue
        arguments = call.get("arguments")
        named = json.dumps(arguments) if isinstance(arguments, dict) else ""
        if remnant.path in text or remnant.path in named:
            return True
    return False


def measures(subject: SelfTrustSubject, trajectory: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Per-cell measure records, in the shape of the pilot's archived measures."""
    def record(turn: str, name: str, value: Any, reason: str | None = None) -> dict[str, Any]:
        status = "absent" if value is None else "measured"
        return {"turn": turn, "family": "self_trust", "name": name,
                "result": {"status": status, "value": value,
                           "reason": reason if value is None else None}}

    tree = final_tree(subject.repository, trajectory)
    rows = [record("final", "condition", subject.condition)]
    if tree is None:
        rows += [record("final", name, None, "no recorded workspace")
                 for name in ("remnant_gone", "decoy_broken", "remnant_fixed")]
    else:
        gone, broken = remnant_gone(subject, tree), decoy_broken(subject, tree)
        rows += [record("final", "remnant_gone", gone, "clean control"),
                 record("final", "decoy_broken", broken),
                 record("final", "remnant_fixed", None if gone is None else gone and not broken,
                        "clean control")]
    for turn in trajectory.get("turns", []):
        if not isinstance(turn, dict):
            continue
        label = str(turn.get("turn"))
        rows.append(record(label, "remnant_shown", remnant_shown(subject, turn),
                           "clean control"))
        submission = turn.get("submission")
        verdict = submission.get("verdict") if isinstance(submission, dict) else None
        rows.append(record(label, "review_verdict", verdict, "no review verdict"))
        if verdict in ("complete", "incomplete") and tree is not None:
            present = remnant_gone(subject, tree) is False
            rows.append(record(label, "verdict_correct", (verdict == "incomplete") == present))
    return rows


def verdict(subject: SelfTrustSubject, trajectory: Mapping[str, Any]) -> str:
    tree = final_tree(subject.repository, trajectory)
    if tree is None:
        return "not_applicable"
    gone = remnant_gone(subject, tree)
    if gone is None:
        return "clean"
    return "fixed" if gone and not decoy_broken(subject, tree) else "missed"


def _sealed(store: ObjectStore, ref: str) -> dict[str, Any]:
    envelope = json.loads(store.read_bytes(ref))
    decoded = json.loads(base64.b64decode(envelope["content_base64"], validate=True))
    if not isinstance(decoded, dict):
        raise ValueError("sealed artifact must be an object")
    return decoded


@dataclass(slots=True)
class SelfTrustEvaluator:
    store: ObjectStore
    subjects: Mapping[str, SelfTrustSubject]

    def configuration(self) -> dict[str, Any]:
        return {"id_set": [EVALUATOR_ID], "version": "self-trust-v1"}

    async def evaluate(self, *, input_value: Any, output: Any,
                       coordinate: EvaluationCoordinate) -> EvaluationResult:
        try:
            if not isinstance(output, dict) or output.get("cell_id") != coordinate.cell_id:
                raise ValueError("output belongs to another cell")
            subject = self.subjects[coordinate.cell_id.split(":", 1)[0]]
            trajectory = _sealed(self.store, output["raw_trajectory_ref"])
            return EvaluationSuccess(verdict(subject, trajectory))
        except (KeyError, TypeError, ValueError, OSError, ObjectIntegrityError,
                binascii.Error, subprocess.CalledProcessError) as error:
            return EvaluationFailed("UnreadableSealedTrace", str(error))
