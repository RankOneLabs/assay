from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any

import paa_contracts
import pytest
from jig.core.types import CompletionParams, LLMResponse, ToolCall, Usage

from assay.adapters.consistency import DescribedClient, render_input
from assay.adapters.openrouter import HAIKU_BEDROCK, OpenRouterFactory
from assay.execution import WorkerSuccess
from assay.investigations.consistency import StructuralEvaluator, materialize_consistency
from assay.investigations.correctness import DockerPythonRunner, SandboxResult
from assay.investigations.dry_experiment import DryExperimentPrepared, DryExperimentSucceeded
from assay.investigations.realistic_fixtures import (
    REALISTIC_PILOT_FIXTURES,
    REALISTIC_PILOT_TASKS,
    realistic_repository_variants,
    repository_lines,
    validate_repository_fixture,
)
from assay.investigations.realistic_pilot import (
    prepare_realistic_pilot,
    realistic_haiku_settings,
    run_realistic_pilot,
)
from assay.models import StudySnapshot
from assay.repository import validate_repository
from assay.store import ObjectStore
from assay.verify import reference_closure, verify_snapshot

RUN_DOCKER_TESTS = os.environ.get("ASSAY_RUN_DOCKER_TESTS") == "1"


class FakeFactory:
    def __init__(self) -> None:
        self.calls: list[CompletionParams] = []

    def configuration(self) -> dict[str, Any]:
        return OpenRouterFactory(HAIKU_BEDROCK).configuration()

    def create(self) -> DescribedClient:
        owner = self

        class Client(DescribedClient):
            def configuration(self) -> dict[str, Any]:
                return owner.configuration()

            async def complete(self, params: CompletionParams) -> LLMResponse:
                owner.calls.append(copy.deepcopy(params))
                prompt = json.loads(params.messages[0].content)
                fixture = next(
                    item
                    for item in REALISTIC_PILOT_FIXTURES
                    if item.task.instruction == prompt["instruction"]
                )
                target = prompt["repository"][fixture.target_path]
                source = (
                    fixture.task.reused_source
                    if target.count(f"return {fixture.task.helper}(value)") == 3
                    else fixture.task.duplicated_source
                )
                return LLMResponse(
                    content="",
                    tool_calls=[ToolCall("submission", "submit_output", {"source": source})],
                    usage=Usage(1_000, 50, 0.001),
                    latency_ms=1,
                    model=HAIKU_BEDROCK.model,
                )

            async def aclose(self) -> None:
                return None

        return Client()


class PassingRunner(DockerPythonRunner):
    async def run(
        self,
        *,
        task: Any,
        repository: Any,
        target_path: str,
        source: str,
    ) -> SandboxResult:
        del repository, target_path, source
        return SandboxResult(len(task.test_cases), len(task.test_cases), ())


def contracts() -> dict[str, dict[str, Any]]:
    return {
        name: paa_contracts.load_schema(name)
        for name in ("paa-task", "paa-evidence-record", "paa-operating-record")
    }


def test_realistic_fixtures_are_large_valid_and_treatment_isolated() -> None:
    assert len(REALISTIC_PILOT_FIXTURES) == 4
    assert len({fixture.id for fixture in REALISTIC_PILOT_FIXTURES}) == 4
    for fixture in REALISTIC_PILOT_FIXTURES:
        validate_repository_fixture(fixture)
        clean = fixture.clean_repository
        inconsistent = fixture.inconsistent_repository
        assert clean.keys() == inconsistent.keys()
        assert len(clean) == 31
        assert 1_000 <= repository_lines(clean) <= 3_000
        assert repository_lines(clean) == repository_lines(inconsistent)
        assert [path for path in clean if clean[path] != inconsistent[path]] == [
            fixture.target_path
        ]
        clean_lines = clean[fixture.target_path].splitlines()
        inconsistent_lines = inconsistent[fixture.target_path].splitlines()
        changed = [
            (left, right)
            for left, right in zip(clean_lines, inconsistent_lines, strict=True)
            if left != right
        ]
        assert len(changed) == 3
        assert all(fixture.task.helper in left for left, _ in changed)
        assert all(fixture.task.helper not in right for _, right in changed)


def test_realistic_repositories_render_without_hidden_task_fields() -> None:
    for fixture in REALISTIC_PILOT_FIXTURES:
        value = {
            "task": fixture.task.model_dump(mode="json"),
            "repository": fixture.clean_repository,
            "base_subject_ref": "sha256:" + "0" * 64,
        }
        rendered = render_input(value, 64_000)
        assert isinstance(rendered, WorkerSuccess), rendered
        prompt = json.loads(rendered.output)
        assert prompt == {
            "instruction": fixture.task.instruction,
            "repository": dict(fixture.clean_repository),
        }
        assert "test_cases" not in rendered.output
        assert "base_subject_ref" not in rendered.output


def test_realistic_repositories_materialize_and_verify(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path / "store")
    snapshot = materialize_consistency(
        store,
        worker_configuration={"id": "fixture-worker", "version": "1"},
        evaluator=StructuralEvaluator(),
        schemas=contracts(),
        tasks=REALISTIC_PILOT_TASKS,
        evaluator_repeats=1,
        execution_schedule="subject-counterbalanced-v1",
        repository_variants=realistic_repository_variants(),
    )
    verify_snapshot(store, snapshot)
    assert isinstance(snapshot, StudySnapshot)
    assert len(snapshot.subjects) == 4
    assert len(snapshot.realizations) == 8
    for realization in snapshot.realizations:
        value = json.loads(store.read_bytes(realization.artifact_ref))
        fixture = next(
            item for item in REALISTIC_PILOT_FIXTURES if item.id == realization.subject_id
        )
        assert value["repository"] == dict(fixture.repository(realization.arm_id))


@pytest.mark.asyncio
async def test_realistic_pilot_prepares_and_runs_full_offline_acceptance(
    tmp_path: Path,
) -> None:
    store = ObjectStore(tmp_path / "store")
    factory = FakeFactory()
    runner = PassingRunner()
    prepared = prepare_realistic_pilot(
        store,
        factory=factory,
        settings=realistic_haiku_settings(),
        schemas=contracts(),
        runner=runner,
    )
    assert isinstance(prepared, DryExperimentPrepared), prepared
    assert prepared.executions == 16
    assert prepared.evaluations == 32
    assert not factory.calls
    assert len(reference_closure(store, (prepared.plan_ref,))) > 8

    result = await run_realistic_pilot(
        store,
        plan_ref=prepared.plan_ref,
        authorization=prepared.plan_ref,
        factory=factory,
        runner=runner,
        allow_paid=True,
        export_destination=tmp_path / "bundles",
    )
    assert isinstance(result, DryExperimentSucceeded), result
    assert len(factory.calls) == 16
    report = json.loads(store.read_bytes(result.abstraction_report_ref))
    comparison = report["comparisons"][0]
    assert comparison["n"] == 4
    assert comparison["improved"] == 4
    assert comparison["regressed"] == 0


@pytest.mark.parametrize("path", ["../secret.py", "/absolute.py", "a\\b.py", "a/./b.py"])
def test_repository_validation_rejects_unsafe_paths(path: str) -> None:
    with pytest.raises(ValueError, match="unsafe repository path"):
        validate_repository({path: "pass\n"})


@pytest.mark.asyncio
@pytest.mark.skipif(
    not RUN_DOCKER_TESTS, reason="requires explicitly prepared pinned Docker runtime"
)
async def test_realistic_reference_implementations_run_in_full_repository() -> None:
    runner = DockerPythonRunner()
    for fixture in REALISTIC_PILOT_FIXTURES:
        for arm, source in (
            ("clean", fixture.task.reused_source),
            ("inconsistent", fixture.task.duplicated_source),
        ):
            result = await runner.run(
                task=fixture.task,
                repository=fixture.repository(arm),
                target_path=fixture.target_path,
                source=source,
            )
            assert isinstance(result, SandboxResult), result
            assert result.passed == result.total == len(fixture.task.test_cases)


@pytest.mark.asyncio
@pytest.mark.skipif(
    not RUN_DOCKER_TESTS, reason="requires explicitly prepared pinned Docker runtime"
)
async def test_realistic_target_can_import_from_ephemeral_package() -> None:
    fixture = REALISTIC_PILOT_FIXTURES[0]
    target_source = (
        "from .validation.catalog import validate_name\n\n"
        "def normalize_sku(value):\n"
        "    return validate_name(value).upper() if value.strip() else \"\"\n"
    )
    repository = dict(fixture.clean_repository)
    repository[fixture.target_path] = target_source
    task = fixture.task.model_copy(update={"helper_source": target_source})
    result = await DockerPythonRunner().run(
        task=task,
        repository=repository,
        target_path=fixture.target_path,
        source=task.reused_source,
    )
    assert isinstance(result, SandboxResult), result
    assert result.passed == result.total == len(task.test_cases)
