"""The one-share fixtures: the forge move/rewrite pair and #146."""

from __future__ import annotations

import json
from dataclasses import asdict, replace
from decimal import Decimal
from pathlib import Path

import pytest

from assay.investigations.workflow_correctness import workflow_tree_digest
from assay.models import RuntimeProfile
from assay.store import ObjectStore
from verification_pilot.budget import SpendGate
from verification_pilot.run import ScriptedWorker, paid_model_route
from verification_pilot.self_trust import refactor, rewrite
from verification_pilot.self_trust.bridge import SelfTrustBridgeClient
from verification_pilot.self_trust.fixtures import (
    CHANGES,
    FORGE_MOVE,
    FORGE_REWRITE,
    RESUME_146,
    SHARE,
    writable_prefixes_for,
)
from verification_pilot.self_trust.ladder import RUNGS
from verification_pilot.self_trust.logs import log_key
from verification_pilot.self_trust.refactor_session import recorded
from verification_pilot.self_trust.study import ARMS, compile_self_trust_plan, self_trust_subjects
from verification_pilot.settings import VerificationPilotSettings

NAMES = sorted(CHANGES)


def test_rerun_scopes_come_from_each_fixtures_changed_paths() -> None:
    assert writable_prefixes_for(
        RESUME_146.start_tree(), RESUME_146.finished_tree(omit=False),
        (RESUME_146.omission.path,)) == ("adapters/", "core/")
    assert RESUME_146.writable_prefixes == ("adapters/", "core/")
    for name in ("rewrite", "rewrite0"):
        rung = RUNGS[name]
        assert writable_prefixes_for(rung.start_tree(), rung.subject_tree(None),
                                     rung.omission_paths.values()) == ("src/", "tests/")
        assert rung.writable_prefixes == ("src/", "tests/")


def test_every_omission_names_its_start_tree_behavior_source() -> None:
    for change in CHANGES.values():
        assert change.omission.expected_behavior_source
        assert RUNGS[change.name].expected_behavior_sources[SHARE] == (
            change.omission.expected_behavior_source)
    for group, omission in refactor.OMISSIONS.items():
        assert refactor.MODULES[group] == omission.path
        assert RUNGS["refactor"].expected_behavior_sources[group] == (
            omission.expected_behavior_source)
    for group, omission in rewrite.OMISSIONS.items():
        assert RUNGS["rewrite"].expected_behavior_sources[group] == (
            omission.expected_behavior_source)
    assert rewrite.OMISSIONS["group_c"].path == "src/runtime/cohort-pull-request.ts"
    assert rewrite.OMISSIONS["group_c"].marker == "send_run_wake?.(completion.run_id"
    assert rewrite.OMISSIONS["group_c"].expected_behavior_source == "new_in_refactor"
    for rung in RUNGS.values():
        assert set(rung.expected_behavior_sources) == set(rung.order)
        assert set(rung.omission_paths) == set(rung.order)
        start = rung.start_tree()
        for source in rung.expected_behavior_sources.values():
            if source == "new_in_refactor":
                continue
            path, number = source.rsplit(":", 1)
            assert path in start, (rung.name, source)
            assert 1 <= int(number) <= len(start[path].splitlines()), (rung.name, source)


def test_changed_root_file_cannot_have_a_writable_directory_prefix() -> None:
    with pytest.raises(ValueError, match="changed root file"):
        writable_prefixes_for({"package.json": "before"}, {"package.json": "after"}, ())


def test_self_trust_bridge_configuration_uses_rung_scope(tmp_path: Path) -> None:
    subjects = {subject.id: subject for subject in self_trust_subjects()}
    bridge = SelfTrustBridgeClient(
        image="sha256:" + "1" * 64, runs_root=tmp_path, run_label="self-trust",
        model_route=paid_model_route("gemini-4-argon"), subjects=subjects,
        settings=VerificationPilotSettings(), api_key="test-key",
        spend_gate=SpendGate(Decimal("1")),
    )
    for name in ("rewrite", "rewrite0", "resume146"):
        subject = subjects[f"{name}-own_a-remnant_a"]
        assert bridge.configuration(subject)["writable_prefixes"] == list(
            RUNGS[name].writable_prefixes)


@pytest.mark.parametrize("violation", ["omission", "clean_change"])
def test_plan_refuses_paths_outside_rung_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, violation: str,
) -> None:
    rung = RUNGS["rewrite0"]
    if violation == "omission":
        broken = replace(rung, omission_paths={"group_a": "outside/omission.ts"})
    else:
        broken = replace(rung, writable_prefixes=("src/",))
    monkeypatch.setitem(RUNGS, rung.name, broken)
    store = ObjectStore(tmp_path / "store")
    worker = ScriptedWorker(store)
    runtime = RuntimeProfile(id="scripted", version="1",
                             configuration_ref=str(store.publish_json({"scripted": True})))
    subject = next(item for item in self_trust_subjects()
                   if item.id == "rewrite0-own_a-remnant_a")
    with pytest.raises(ValueError, match="outside writable_prefixes"):
        compile_self_trust_plan(
            store, runtime, worker_configurations={arm: worker.configuration(arm)
                                                   for arm in ARMS},
            active_subject_ids=(subject.id,), subjects_data=(subject,),
            active_arms=("st-native",))


def test_the_forge_pair_differs_only_in_the_kind_of_change() -> None:
    assert FORGE_MOVE.start_tree() == FORGE_REWRITE.start_tree()
    assert FORGE_MOVE.hidden_tests == FORGE_REWRITE.hidden_tests
    assert FORGE_MOVE.omission.path == FORGE_REWRITE.omission.path
    assert FORGE_MOVE.visible_tests == FORGE_REWRITE.visible_tests
    moved = set(FORGE_MOVE.subject_tree(None))
    assert moved == set(FORGE_REWRITE.subject_tree(None)) - {"src/forge/rules.ts"}


@pytest.mark.parametrize("name", NAMES)
def test_the_omission_is_one_span_in_one_file(name: str) -> None:
    change = CHANGES[name]
    clean, omitted = change.subject_tree(None), change.subject_tree(SHARE)
    assert [path for path in clean if clean[path] != omitted.get(path)] == [change.omission.path]
    assert change.omission.clean in clean[change.omission.path]
    assert change.omission.clean not in omitted[change.omission.path]


@pytest.mark.parametrize("name", NAMES)
def test_committed_image_check_holds_for_the_current_trees(name: str) -> None:
    rung = RUNGS[name]
    result = json.loads((rung.logs.parent / f"{name}-check.json").read_text(encoding="utf-8"))
    assert result["holds"] is True
    expected = {"start": rung.start_tree(), "clean": rung.subject_tree(None),
                f"omit-{SHARE}": rung.subject_tree(SHARE)}
    assert {case: entry["tree_digest"] for case, entry in result["cases"].items()} == {
        case: workflow_tree_digest(tree) for case, tree in expected.items()}


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("omit", [False, True])
def test_recorded_logs_match_the_current_plan(name: str, omit: bool) -> None:
    rung = RUNGS[name]
    entry = recorded(rung)[log_key(name, SHARE, omit)]
    calls = rung.plan_share(rung.start_tree(), SHARE, omit=omit)
    assert entry["calls"] == [asdict(call) for call in calls]
    assert entry["outputs"][-1].startswith("exit=0\n")
