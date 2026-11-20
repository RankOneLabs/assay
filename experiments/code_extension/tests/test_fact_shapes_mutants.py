import pytest
from code_extension.fact_shapes.attempts import Fact, Group, HolderSpec
from code_extension.fact_shapes.budget import Err, Ok
from code_extension.fact_shapes.cells import FactId, RepositoryPath
from code_extension.fact_shapes.mutants import Run, verdict


def facts() -> tuple[Fact, ...]:
    return tuple(
        Fact(
            FactId(name),
            (f"fact:{name}: accepts",),
            "reference",
            HolderSpec((RepositoryPath("policy.ts"),), ()),
        )
        for name in ("control", "anchor")
    )


def replay(control: str = "fail", anchor: str = "pass", regression: str = "passed") -> Run:
    return Run(
        {
            "visible_regression": Group(status=regression),
            "hidden_regression": Group(status="passed"),
            "new_behavior": Group(
                status="failed" if "fail" in (control, anchor) else "passed",
                stdout=f"({control}) fact:control: accepts\n({anchor}) fact:anchor: accepts\n",
            ),
        }
    )


def test_drop_requires_only_its_own_miss() -> None:
    good = replay()
    assert isinstance(
        verdict("reference", "drop-control", facts(), (good, good), FactId("control")), Ok
    )
    for bad in (replay(anchor="fail"), replay(regression="failed"), replay(control="pass")):
        result = verdict("reference", "drop-control", facts(), (bad, bad), FactId("control"))
        assert isinstance(result, Err)
        assert result.error.arm == "reference"
        assert result.error.patch == "drop-control"
        assert result.error.fact


def test_reference_and_reproduction() -> None:
    good = replay(control="pass")
    assert isinstance(verdict("reference", "reference", facts(), (good, good)), Ok)
    assert isinstance(verdict("reference", "reference", facts(), (good, replay())), Err)
    assert isinstance(verdict("reference", "reference", facts(), (good,)), Err)


def test_holder_only_typecheck() -> None:
    control, anchor = facts()
    control = Fact(control.id, control.titles, "type_enforced", control.holder)
    good = Run({}, "typecheck_failed", "policy.ts(1,1): error TS2322: missing value")
    assert isinstance(verdict(
        "type_enforced", "drop-control", (control, anchor), (good, good), control.id
    ), Ok)
    bad = Run(
        {}, "typecheck_failed", good.typecheck_output + "\nother.ts(2,1): error TS2322: broken"
    )
    assert isinstance(verdict(
        "type_enforced", "drop-control", (control, anchor), (bad, bad), control.id
    ), Err)


def test_missing_titles_do_not_prove_a_miss() -> None:
    good = replay()
    groups = dict(good.groups)
    groups["new_behavior"] = Group(status="failed", stdout="(pass) fact:anchor: accepts")
    missing = Run(groups)
    assert isinstance(verdict(
        "reference", "drop-control", facts(), (missing, missing), FactId("control")
    ), Err)


def test_retained_mutant_evidence_covers_every_arm() -> None:
    import json
    from dataclasses import asdict
    from pathlib import Path
    from typing import cast

    from code_extension.fact_shapes.alignment import fact_titles as source_titles
    from code_extension.fact_shapes.cells import CELLS, Shape
    from code_extension.fact_shapes.generate import scenario_name

    root = Path(__file__).resolve().parents[1] / "fixtures"
    for cell in CELLS:
        directory = root / scenario_name(cell) / "qualification/mutants" / cell.shape
        records = sorted(directory.glob("*.json"))
        assert len(records) == (
            4
            if cell.shape in {"outside_code", "type_enforced"}
            or (cell.shape == "existing_state" and cell.task_type == "additive")
            else 3
        )
        for path in records:
            evidence = json.loads(path.read_bytes())
            assert evidence["result"]["passed"], path
            assert set(evidence["scored_facts"]) == {cell.fact_id, cell.anchor_fact_id}
            assert evidence["result"]["arm"] == cell.shape
            assert evidence["patch_digest"].startswith("sha256:")
            assert len(evidence["runs"]) == 2
            scored = tuple(
                Fact(
                    fact_id,
                    source_titles((root / scenario_name(cell)
                                   / "hidden/new_behavior/tests/hidden/new-behavior"
                                   / f"{fact_id}.test.ts").read_text()),
                    cast(Shape, shape),
                    HolderSpec(tuple(RepositoryPath(p) for p in paths), ()),
                )
                for fact_id, shape, paths in (
                    (cell.fact_id, cell.shape, cell.holders),
                    (cell.anchor_fact_id, "reference", (f"{cell.feature}/anchor.ts",)),
                )
            )
            replays = tuple(
                Run(
                    {name: Group(status=group["status"], stdout="\n".join(
                        [f"(pass) {title}" for title in run["passing_titles"]]
                        + [f"(fail) {title}" for title in run["failing_titles"]]
                    ) if name == "new_behavior" else "")
                     for name, group in run["groups"].items()},
                    run["preflight_cause"], run["typecheck_output"],
                ) for run in evidence["runs"]
            )
            result = verdict(
                cell.shape, evidence["result"]["patch"], scored, replays,
                evidence["result"]["fact"],
                allow_preflight=path.name != "type-without-required-feature.patch.json",
            )
            assert isinstance(result, Ok), path
            assert asdict(result.value) == evidence["result"]
            for run in evidence["runs"]:
                assert "passing_titles" in run and "failing_titles" in run


@pytest.mark.asyncio
async def test_launch_retries_do_not_retry_candidate_failures(
    monkeypatch: "pytest.MonkeyPatch",
) -> None:
    from code_extension.qualify import LaunchRetryRunner

    from assay.investigations.workflow_correctness import (
        DockerWorkflowRunner,
        WorkflowCorrectnessResult,
        WorkflowRunnerSettings,
    )

    calls = 0
    responses = [
        WorkflowCorrectnessResult("unavailable", (), cause="SandboxUnavailable"),
        WorkflowCorrectnessResult("correct", ()),
    ]

    async def fake_run(_self: DockerWorkflowRunner, **_kwargs: object) -> WorkflowCorrectnessResult:
        nonlocal calls
        response = responses[min(calls, len(responses) - 1)]
        calls += 1
        return response

    monkeypatch.setattr(DockerWorkflowRunner, "run", fake_run)
    runner = LaunchRetryRunner(WorkflowRunnerSettings(image="sha256:" + "1" * 64))
    assert (
        await runner.run(
            baseline={},
            groups=(),
            baseline_tree_digest="tree",
            expected_tree_digest="tree",
            patch="",
        )
    ).verdict == "correct"
    assert calls == 2
    for cause in ("group_failure", "typecheck_nonzero_exit", "candidate_timeout"):
        calls = 0
        responses[:] = [WorkflowCorrectnessResult("incorrect", (), cause=cause)]
        assert (
            await runner.run(
                baseline={},
                groups=(),
                baseline_tree_digest="tree",
                expected_tree_digest="tree",
                patch="",
            )
        ).cause == cause
        assert calls == 1
    calls = 0
    responses[:] = [WorkflowCorrectnessResult("unavailable", (), cause="SandboxUnavailable")]
    assert (
        await runner.run(
            baseline={},
            groups=(),
            baseline_tree_digest="tree",
            expected_tree_digest="tree",
            patch="",
        )
    ).verdict == "unavailable"
    assert calls == 3


@pytest.mark.asyncio
async def test_gate_refuses_unknown_scenarios_before_docker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from code_extension.fact_shapes.mutants import gate_scenario

    def forbidden_image_lookup(_image: str) -> str:
        raise AssertionError("unknown scenarios must not reach Docker")

    monkeypatch.setattr("code_extension.qualify.observed_image_digest", forbidden_image_lookup)
    with pytest.raises(ValueError, match="unknown fact-shapes scenario"):
        await gate_scenario("missing-scenario", "unused-image")


def test_other_arms_titles_are_not_scored() -> None:
    good = replay()
    group = good.groups["new_behavior"]
    groups = dict(good.groups)
    groups["new_behavior"] = Group(
        status="failed", stdout=group.stdout + "(fail) fact:another_arm: accepts\n"
    )
    run = Run(groups)
    assert isinstance(
        verdict("reference", "drop-control", facts(), (run, run), FactId("control")), Ok
    )
    bad = replay(anchor="fail")
    assert isinstance(
        verdict("reference", "drop-control", facts(), (bad, bad), FactId("control")), Err
    )


def test_reference_ignores_other_arms_failed_titles() -> None:
    good = replay(control="pass")
    groups = dict(good.groups)
    groups["new_behavior"] = Group(
        status="failed",
        stdout=good.groups["new_behavior"].stdout + "(fail) fact:another_arm: accepts\n",
    )
    run = Run(groups)
    assert isinstance(verdict("reference", "reference", facts(), (run, run)), Ok)


def test_independent_type_drop_requires_titles() -> None:
    control, anchor = facts()
    control = Fact(control.id, control.titles, "type_enforced", control.holder)
    good = replay()
    assert isinstance(verdict(
        "type_enforced", "independent-drop", (control, anchor), (good, good), control.id,
        allow_preflight=False,
    ), Ok)
    for bad in (replay(anchor="fail"), replay(control="pass"), replay(regression="failed")):
        assert isinstance(verdict(
            "type_enforced", "independent-drop", (control, anchor), (bad, bad), control.id,
            allow_preflight=False,
        ), Err)
    preflight = Run({}, "typecheck_failed", "policy.ts(1,1): error TS2322: missing value")
    assert isinstance(verdict(
        "type_enforced", "independent-drop", (control, anchor), (preflight, preflight), control.id,
        allow_preflight=False,
    ), Err)


def test_independent_type_controls_cast_the_unchanged_label_map() -> None:
    import json
    import tempfile
    from pathlib import Path

    from code_extension.fact_shapes.cells import CELLS
    from code_extension.fact_shapes.generate import scenario_name
    from code_extension.fact_shapes.mutants import alternative_control
    from code_extension.fact_shapes.switches import LABEL_MAPS, PROGRESS_TYPE, label_type
    from code_extension.fixture import materialize, read_tree
    from code_extension.fixtures import load_scenario

    from assay.canonical import digest_bytes

    root = Path(__file__).resolve().parents[1] / "fixtures"
    for cell in CELLS:
        if cell.shape != "type_enforced":
            continue
        path = (root / scenario_name(cell) / "qualification/mutants/type_enforced"
                / "type-without-required-feature.patch.json")
        evidence = json.loads(path.read_bytes())
        fixture = load_scenario(scenario_name(cell), arm_id=cell.shape)
        drop = (root / scenario_name(cell) / "patches"
                / f"type_enforced.drop-{cell.fact_id}.patch").read_text()
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            materialize(target, fixture.repository, drop)
            label, patch = alternative_control(cell, fixture.repository, read_tree(target))
            assert label == "type-without-required-feature.patch"
            assert patch == evidence["control_patch"]
            assert evidence["patch_digest"] == digest_bytes(patch.encode())
            materialize(target, fixture.repository, patch)
            if cell.feature == "stage":
                labels, record = "stageProgress", PROGRESS_TYPE
            else:
                labels = LABEL_MAPS[cell.feature]
                record = f"Record<{label_type(cell.feature)}, string>"
            # The holder's literal is unchanged; only its declared type becomes a cast.
            assert (target / cell.holders[0]).read_text() == fixture.repository[
                cell.holders[0]
            ].replace(f"{labels}: {record} = {{", f"{labels} = {{").replace(
                " };\n", f" }} as unknown as {record};\n"
            )
        assert evidence["control_patch"] == patch
        assert evidence["result"]["passed"]
        for run in evidence["runs"]:
            assert run["preflight_cause"] is None
            assert run["groups"]["visible_regression"]["status"] == "passed"
            assert run["groups"]["hidden_regression"]["status"] == "passed"
            assert any(t.startswith(f"fact:{cell.fact_id}: ") for t in run["failing_titles"])
            assert any(t.startswith(f"fact:{cell.anchor_fact_id}: ") for t in run["passing_titles"])
            assert not any(t.startswith(f"fact:{cell.anchor_fact_id}: ")
                           for t in run["failing_titles"])


def test_follow_up_migration_control_includes_a_later_index() -> None:
    import tempfile
    from pathlib import Path

    from code_extension.fact_shapes.cells import CELLS
    from code_extension.fact_shapes.generate import scenario_name
    from code_extension.fact_shapes.mutants import alternative_control
    from code_extension.fixture import materialize, read_tree
    from code_extension.fixtures import load_scenario

    for cell in CELLS:
        if cell.shape != "outside_code":
            continue
        fixture = load_scenario(scenario_name(cell), arm_id=cell.shape)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            materialize(target, fixture.repository, fixture.arms[0].reference_patch)
            _, patch = alternative_control(cell, fixture.repository, read_tree(target))
        # Follow-ups come after every migration the service already has.
        count = sum(1 for path in fixture.repository if path.startswith("db/migrations/"))
        if cell.feature == "stage":
            # Stages (round 6): the follow-up replaces the run status trigger.
            assert f"db/migrations/{count + 1:03d}_run_status_both_ways.sql" in patch
            assert "DROP TRIGGER IF EXISTS runs_status_column;" in patch
            continue
        assert f"db/migrations/{count + 1:03d}_allow_" in patch
        assert f"db/migrations/{count + 2:03d}_index_" in patch
        assert "CREATE INDEX" in patch
