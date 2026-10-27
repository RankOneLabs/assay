"""Self-trust plan, evaluator and bridge configuration."""

from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from assay.canonical import canonical_json, digest_bytes
from assay.models import RuntimeProfile
from assay.store import ObjectStore
from verification_pilot.budget import SpendGate
from verification_pilot.fixtures import GROUPS, whole_word_pattern
from verification_pilot.run import ScriptedWorker, paid_model_route
from verification_pilot.self_trust import probe_routes
from verification_pilot.self_trust.bridge import SelfTrustBridgeClient, subject_turns
from verification_pilot.self_trust.concepts import LEGACY_READER
from verification_pilot.self_trust.evaluation import measures, remnant_shown, verdict
from verification_pilot.self_trust.ladder import RESUME_146, REWRITE, REWRITE_0
from verification_pilot.self_trust.prompts import build_system_prompt, framing_for
from verification_pilot.self_trust.run import remeasure
from verification_pilot.self_trust.session import SYSTEM_PROMPT
from verification_pilot.self_trust.study import (
    ARMS,
    MATCHED_ARMS,
    SelfTrustSubject,
    calibration_subject_ids,
    compile_self_trust_plan,
    order_for,
    placement_for,
    self_trust_subjects,
)
from verification_pilot.settings import VerificationPilotSettings

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "integrations" / "pier" / "src"))
from assay_pier_bridge.paths import submission_patch  # noqa: E402

SUBJECTS = {subject.id: subject for subject in self_trust_subjects()}
PLANTED = SUBJECTS["stage_run-own_c-remnant_c"]


def _trajectory(tmp_path: Path, start: dict[str, str], final: dict[str, str],
                tool_calls: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    for name, tree in (("before", start), ("after", final)):
        for path, source in tree.items():
            target = tmp_path / name / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(source, encoding="utf-8")
    patch = submission_patch(tmp_path / "before", tmp_path / "after").patch.decode("utf-8")
    return {"turns": [{"turn": "T1", "tool_calls": tool_calls or [], "workspace_diff": patch,
                       "submission": {"title": "t", "body": "b"}}]}


def _fixed(subject: SelfTrustSubject) -> dict[str, str]:
    assert subject.remnant_owner is not None
    remnant = subject.concept.remnants[GROUPS.index(subject.remnant_owner)]
    tree = dict(subject.repository)
    tree[remnant.path] = whole_word_pattern(remnant.old).sub(remnant.new, tree[remnant.path])
    return tree


def test_subjects_cross_concept_own_share_and_remnant_location() -> None:
    renames = [s for s in SUBJECTS.values() if s.fixture == "rename"]
    refactors = [s for s in SUBJECTS.values() if s.fixture == "refactor"]
    rewrites = [s for s in SUBJECTS.values() if s.fixture == "rewrite"]
    assert (len(renames), len(refactors), len(rewrites)) == (36, 12, 12)
    for subjects, per_condition in ((renames, (9, 18, 9)), (refactors, (3, 6, 3)),
                                    (rewrites, (3, 6, 3))):
        conditions = [subject.condition for subject in subjects]
        assert (conditions.count("own"), conditions.count("teammate"),
                conditions.count("clean")) == per_condition


def test_calibration_plan_is_six_native_teammate_cells(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path / "store")
    worker = ScriptedWorker(store)
    runtime = RuntimeProfile(id="scripted", version="1",
                             configuration_ref=str(store.publish_json({"scripted": True})))
    ids = calibration_subject_ids(tuple(SUBJECTS.values()))
    prepared = compile_self_trust_plan(
        store, runtime, worker_configurations={arm: worker.configuration(arm) for arm in ARMS},
        active_subject_ids=ids, active_arms=("st-native",))
    assert len(prepared.plan_bytes) > 0
    assert all(SUBJECTS[i].condition == "teammate" and SUBJECTS[i].concept.name == "stage_run"
               for i in ids)
    assert len(ids) == 6


def test_unfixed_fixed_and_over_corrected_trees(tmp_path: Path) -> None:
    untouched = _trajectory(tmp_path / "a", PLANTED.repository, PLANTED.repository)
    assert verdict(PLANTED, untouched) == "missed"
    fixed = _trajectory(tmp_path / "b", PLANTED.repository, _fixed(PLANTED))
    assert verdict(PLANTED, fixed) == "fixed"
    broken_tree = _fixed(PLANTED)
    broken_tree[LEGACY_READER] = broken_tree[LEGACY_READER].replace(
        "stage_instance_id:", "stage_run_id:")
    broken = _trajectory(tmp_path / "c", PLANTED.repository, broken_tree)
    assert verdict(PLANTED, broken) == "missed"
    rows = {row["name"]: row["result"]["value"] for row in measures(PLANTED, broken)
            if row["turn"] == "final"}
    assert rows == {"condition": "own", "remnant_gone": True, "decoy_broken": True,
                    "remnant_fixed": False}
    clean = SUBJECTS["stage_run-own_c-remnant_none"]
    assert verdict(clean, _trajectory(tmp_path / "d", clean.repository,
                                      clean.repository)) == "clean"
    assert verdict(PLANTED, {"turns": []}) == "not_applicable"


def test_remnant_shown_needs_the_planted_line_in_a_tool_result() -> None:
    remnant = PLANTED.concept.remnants[2]
    line = PLANTED.repository[remnant.path].split("\n")[remnant.line - 1]
    grep = {"name": "run_command", "exit_code": 0, "arguments": {"command": "grep -rn x src"},
            "returned_text": f"exit=0\n{remnant.path}:{remnant.line}:{line}\n"}
    wide = {"name": "search_files", "exit_code": 0, "arguments": {"query": "StageRunId",
                                                                  "scope": "."},
            "returned_text": f"exit=0\n{remnant.path}:3:import StageRunId\n"}
    assert remnant_shown(PLANTED, {"tool_calls": [grep]}) is True
    assert remnant_shown(PLANTED, {"tool_calls": [wide]}) is False
    assert remnant_shown(SUBJECTS["stage_run-own_c-remnant_none"], {"tool_calls": [grep]}) is None


def test_bridge_configuration_pins_the_self_trust_prompt(tmp_path: Path) -> None:
    bridge = SelfTrustBridgeClient(
        image="sha256:" + "1" * 64, runs_root=tmp_path, run_label="self-trust",
        model_route=paid_model_route("gemini-4-argon"), subjects=dict(SUBJECTS),
        settings=VerificationPilotSettings(), api_key="test-key",
        spend_gate=SpendGate(Decimal("1")),
    )
    rename = SUBJECTS["stage_run-own_c-remnant_c"]
    rename_configuration = bridge.configuration(rename)
    assert rename_configuration["system_prompt_sha256"] == digest_bytes(
        SYSTEM_PROMPT.encode("utf-8"))
    assert rename_configuration["subject_rendering"] == "self-trust-session-v2"
    assert rename_configuration["turn_prompts_sha256"] == digest_bytes(
        canonical_json(list(subject_turns())))
    for rung in (REWRITE, REWRITE_0, RESUME_146):
        for own in GROUPS:
            subject = SUBJECTS[f"{rung.name}-own_{own.removeprefix('group_')}-remnant_none"]
            prompt = build_system_prompt(rung, framing_for(rung, own))
            configuration = bridge.configuration(subject)
            assert configuration["system_prompt_sha256"] == digest_bytes(prompt.encode("utf-8"))
            assert configuration["turn_prompts_sha256"] == digest_bytes(
                canonical_json(list(subject_turns())))


def test_existing_arm_placements_and_orders_are_stable() -> None:
    assert {arm: (placement_for(arm), order_for(arm)) for arm in ARMS} == {
        "st-native": ("native", "own_first"),
        "st-quoted": ("quoted", "own_first"),
        "st-quoted-first": ("quoted", "holder_first"),
        "st-quoted-last": ("quoted", "holder_last"),
        MATCHED_ARMS[0]: ("quoted", "own_first"),
        MATCHED_ARMS[1]: ("quoted", "own_first"),
    }


def test_route_probes_keep_each_invocation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    old = tmp_path / "route-probes.json"
    old.write_bytes(b"existing Sol probes\n")
    monkeypatch.setattr(probe_routes, "RESULT_ROOT", tmp_path)
    monkeypatch.setattr(probe_routes, "probe", lambda *args: {"route": "sonnet-5.5", "ok": True})
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(sys, "argv", ["probe_routes", "--route", "sonnet-5.5",
                                    "--max-spend-usd", "0.10", "--runs-root", str(tmp_path)])
    probe_routes.main()
    probe_routes.main()
    assert old.read_bytes() == b"existing Sol probes\n"
    assert len(list(tmp_path.glob("route-probes-*.json"))) == 2


def test_self_trust_remeasure_preserves_original(tmp_path: Path,
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    traces = tmp_path / "traces"
    traces.mkdir()
    original = b"original measures\n"
    (traces / "001-measures.json").write_bytes(original)
    (traces / "001-trajectory.json").write_text('{"turns": []}', encoding="utf-8")
    (tmp_path / "index.json").write_text(json.dumps({"stage_run-own_c-remnant_c:st-native:w0": {
        "trajectory": "001-trajectory.json", "measures": "001-measures.json"}}), encoding="utf-8")
    monkeypatch.setattr("verification_pilot.self_trust.run.measures", lambda *args: [])
    assert remeasure(tmp_path, "image") == 1
    assert (traces / "001-measures.json").read_bytes() == original
    assert len(list(traces.glob("001-measures-*.json"))) == 1


@pytest.mark.parametrize("arm", ARMS)
def test_every_arm_has_a_realization_for_every_subject(tmp_path: Path, arm: str) -> None:
    store = ObjectStore(tmp_path / "store")
    worker = ScriptedWorker(store)
    runtime = RuntimeProfile(id="scripted", version="1",
                             configuration_ref=str(store.publish_json({"scripted": True})))
    prepared = compile_self_trust_plan(
        store, runtime, worker_configurations={a: worker.configuration(a) for a in ARMS},
        active_subject_ids=tuple(SUBJECTS), active_arms=(arm,))
    assert {(r.subject_id, r.arm_id) for r in prepared.snapshot.realizations
            if r.arm_id == arm} == {(s, arm) for s in SUBJECTS}
