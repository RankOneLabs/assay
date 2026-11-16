import pytest
from code_extension.fact_shapes.attempts import Fact, Group, HolderSpec
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
    assert verdict("reference", "drop-control", facts(), (good, good), FactId("control")).passed
    for bad in (replay(anchor="fail"), replay(regression="failed"), replay(control="pass")):
        result = verdict("reference", "drop-control", facts(), (bad, bad), FactId("control"))
        assert not result.passed
        assert result.arm == "reference" and result.patch == "drop-control" and result.fact


def test_reference_and_reproduction() -> None:
    good = replay(control="pass")
    assert verdict("reference", "reference", facts(), (good, good)).passed
    assert not verdict("reference", "reference", facts(), (good, replay())).passed
    assert not verdict("reference", "reference", facts(), (good,)).passed


def test_holder_only_typecheck() -> None:
    control, anchor = facts()
    control = Fact(control.id, control.titles, "type_enforced", control.holder)
    good = Run({}, "typecheck_failed", "policy.ts(1,1): error TS2322: missing value")
    assert verdict(
        "type_enforced", "drop-control", (control, anchor), (good, good), control.id
    ).passed
    bad = Run(
        {}, "typecheck_failed", good.typecheck_output + "\nother.ts(2,1): error TS2322: broken"
    )
    assert not verdict(
        "type_enforced", "drop-control", (control, anchor), (bad, bad), control.id
    ).passed


def test_missing_titles_do_not_prove_a_miss() -> None:
    good = replay()
    groups = dict(good.groups)
    groups["new_behavior"] = Group(status="failed", stdout="(pass) fact:anchor: accepts")
    missing = Run(groups)
    assert not verdict(
        "reference", "drop-control", facts(), (missing, missing), FactId("control")
    ).passed


def test_retained_mutant_evidence_covers_every_arm() -> None:
    import json
    from pathlib import Path

    from code_extension.fact_shapes.cells import CELLS
    from code_extension.fact_shapes.generate import scenario_name

    root = Path(__file__).resolve().parents[1] / "fixtures"
    for cell in CELLS:
        directory = root / scenario_name(cell) / "qualification/mutants" / cell.shape
        records = sorted(directory.glob("*.json"))
        assert len(records) == (4 if cell.shape in {"outside_code", "existing_state"} else 3)
        for path in records:
            evidence = json.loads(path.read_bytes())
            assert evidence["result"]["passed"], path
            assert evidence["result"]["arm"] == cell.shape
            assert evidence["patch_digest"].startswith("sha256:")
            assert len(evidence["runs"]) == 2
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
