from __future__ import annotations

import copy
import json
import os
from dataclasses import replace
from pathlib import Path
from typing import Any

import paa_contracts
import pytest
from jig.core.types import CompletionParams, LLMResponse, ToolCall, Usage

from assay.adapters.consistency import SYSTEM_PROMPT, DescribedClient, render_input
from assay.adapters.openrouter import (
    GPT_OSS_120B_COREWEAVE,
    HAIKU_BEDROCK,
    OpenRouterFactory,
    OpenRouterSettings,
)
from assay.execution import WorkerSuccess
from assay.investigations.consistency import (
    CodingTask,
    StructuralEvaluator,
    materialize_consistency,
    parse_candidate_source,
)
from assay.investigations.correctness import DockerPythonRunner, SandboxFailure, SandboxResult
from assay.investigations.dry_experiment import (
    DryExperimentFailed,
    DryExperimentPrepared,
    DryExperimentSucceeded,
)
from assay.investigations.realistic_fixtures import (
    REALISTIC_PILOT_FIXTURES,
    REALISTIC_PILOT_TASKS,
    realistic_repository_variants,
    repository_lines,
    validate_repository_fixture,
)
from assay.investigations.realistic_pilot import (
    prepare_realistic_pilot,
    prepare_realistic_smoke,
    realistic_gpt_oss_smoke_settings,
    realistic_haiku_settings,
    run_realistic_pilot,
    run_realistic_smoke,
)
from assay.models import StudySnapshot
from assay.repository import validate_repository
from assay.store import ObjectStore
from assay.verify import reference_closure, verify_snapshot

RUN_DOCKER_TESTS = os.environ.get("ASSAY_RUN_DOCKER_TESTS") == "1"


class FakeFactory:
    def __init__(self, provider: OpenRouterSettings = HAIKU_BEDROCK) -> None:
        self.provider = provider
        self.calls: list[CompletionParams] = []

    def configuration(self) -> dict[str, Any]:
        return OpenRouterFactory(self.provider).configuration()

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
                    model=owner.provider.model,
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
        assert repository_lines(clean) == 1_225
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


def test_fixture_validation_rejects_a_fourth_changed_expression() -> None:
    fixture = REALISTIC_PILOT_FIXTURES[0]
    inconsistent = dict(fixture.inconsistent_repository)
    inconsistent[fixture.target_path] = inconsistent[fixture.target_path].replace(
        "return None if value is None else normalize_sku(value)",
        "return None if value is None else value.strip().upper()",
    )
    with pytest.raises(ValueError, match="exactly three target lines"):
        validate_repository_fixture(replace(fixture, inconsistent_repository=inconsistent))


def test_fixture_validation_rejects_changed_clean_line_without_helper_call() -> None:
    fixture = REALISTIC_PILOT_FIXTURES[0]
    clean = dict(fixture.clean_repository)
    clean[fixture.target_path] = clean[fixture.target_path].replace(
        "return normalize_sku(value)", "return str(value)", 1
    )
    with pytest.raises(ValueError, match="governed helper calls"):
        validate_repository_fixture(replace(fixture, clean_repository=clean))


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


def test_realistic_prompt_explains_same_module_append_boundary() -> None:
    assert "appended verbatim to the target file" in SYSTEM_PROMPT
    assert "Names already defined in that file are in scope" in SYSTEM_PROMPT
    fixture = REALISTIC_PILOT_FIXTURES[0]
    parse_candidate_source(
        fixture.task.reused_source,
        helper=fixture.task.helper,
        target_path=fixture.task.target_path,
    )
    with pytest.raises(ValueError, match="imports must not replace the repository helper"):
        parse_candidate_source(
            "from .normalization import normalize_sku\n\n"
            "def implement(value):\n"
            "    return normalize_sku(value)\n",
            helper=fixture.task.helper,
            target_path=fixture.task.target_path,
        )


@pytest.mark.parametrize(
    "source",
    [
        (
            "from . import normalization as target\n\n"
            "def implement(value):\n"
            "    return target.normalize_sku(value)\n"
        ),
        (
            "from .normalization import normalize_sku as unused\n\n"
            "def implement(value):\n"
            "    return normalize_sku(value)\n"
        ),
        (
            "import marketplace.normalization as target\n\n"
            "def implement(value):\n"
            "    return target.normalize_sku(value)\n"
        ),
    ],
)
def test_realistic_source_rejects_target_module_imports(source: str) -> None:
    fixture = REALISTIC_PILOT_FIXTURES[0]
    with pytest.raises(ValueError, match="imports from the target module are not allowed"):
        parse_candidate_source(
            source,
            helper=fixture.task.helper,
            target_path=fixture.task.target_path,
        )


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
    plan = json.loads(store.read_bytes(prepared.plan_ref))
    assert plan["cost_estimate"] == {
        "amount": 0.96,
        "coverage": "estimated",
        "currency": "USD",
    }
    assert {item["amount"] for item in plan["arm_cost_estimates"].values()} == {0.48}

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
    assert all(
        params.system is not None and SYSTEM_PROMPT in params.system for params in factory.calls
    )
    report = json.loads(store.read_bytes(result.abstraction_report_ref))
    comparison = report["comparisons"][0]
    assert comparison["n"] == 4
    assert comparison["improved"] == 4
    assert comparison["regressed"] == 0


@pytest.mark.asyncio
async def test_realistic_gpt_oss_smoke_prepares_and_runs_full_offline_acceptance(
    tmp_path: Path,
) -> None:
    store = ObjectStore(tmp_path / "store")
    factory = FakeFactory(GPT_OSS_120B_COREWEAVE)
    runner = PassingRunner()
    prepared = prepare_realistic_smoke(
        store,
        factory=factory,
        settings=realistic_gpt_oss_smoke_settings(),
        schemas=contracts(),
        runner=runner,
    )
    assert isinstance(prepared, DryExperimentPrepared), prepared
    assert prepared.executions == 4
    assert prepared.evaluations == 8
    assert not factory.calls
    snapshot = json.loads(store.read_bytes(prepared.snapshot_ref))
    assert [subject["id"] for subject in snapshot["subjects"]] == ["commerce-sku"]
    provider_profiles = {
        (
            arm["worker"]["provider"]["settings"]["model"],
            arm["worker"]["provider"]["settings"]["provider"],
            arm["worker"]["provider"]["settings"]["provider_name"],
            arm["worker"]["provider"]["settings"]["max_prompt_price"],
            arm["worker"]["provider"]["settings"]["max_completion_price"],
        )
        for arm in snapshot["arms"]
    }
    assert provider_profiles == {
        ("openai/gpt-oss-120b", "coreweave/fp4", "CoreWeave", 0.03, 0.17)
    }
    plan = json.loads(store.read_bytes(prepared.plan_ref))
    assert plan["cost_estimate"] == {
        "amount": 0.02,
        "coverage": "estimated",
        "currency": "USD",
    }
    assert {item["amount"] for item in plan["arm_cost_estimates"].values()} == {0.01}

    result = await run_realistic_smoke(
        store,
        plan_ref=prepared.plan_ref,
        authorization=prepared.plan_ref,
        factory=factory,
        runner=runner,
        allow_paid=True,
        export_destination=tmp_path / "bundles",
    )
    assert isinstance(result, DryExperimentSucceeded), result
    assert len(factory.calls) == 4
    assert all(
        params.system is not None and SYSTEM_PROMPT in params.system for params in factory.calls
    )
    report = json.loads(store.read_bytes(result.abstraction_report_ref))
    comparison = report["comparisons"][0]
    assert comparison["n"] == 1
    assert comparison["improved"] == 1
    assert comparison["regressed"] == 0


def test_realistic_gpt_oss_smoke_rejects_a_different_provider(tmp_path: Path) -> None:
    result = prepare_realistic_smoke(
        ObjectStore(tmp_path / "store"),
        factory=FakeFactory(HAIKU_BEDROCK),
        settings=realistic_gpt_oss_smoke_settings(),
        schemas=contracts(),
        runner=PassingRunner(),
    )
    assert isinstance(result, DryExperimentFailed), result
    assert result.message == "realistic smoke provider differs from the governed GPT-OSS profile"


@pytest.mark.parametrize(
    "path",
    ["../secret.py", "/absolute.py", "a\\b.py", "a/./b.py", "a/\x00.py", "a/line\nb.py"],
)
def test_repository_validation_rejects_unsafe_paths(path: str) -> None:
    with pytest.raises(ValueError, match="unsafe repository path"):
        validate_repository({path: "pass\n"})


def test_repository_validation_rejects_file_directory_collisions() -> None:
    with pytest.raises(ValueError, match="collides with a directory"):
        validate_repository({"pkg": "data", "pkg/module.py": "pass\n"})


@pytest.mark.asyncio
async def test_sandbox_rejects_repository_cases_over_tmpfs_budget() -> None:
    fixture = REALISTIC_PILOT_FIXTURES[0]
    repository = {fixture.target_path: fixture.task.helper_source + "#" * 300_000}
    result = await DockerPythonRunner().run(
        task=fixture.task,
        repository=repository,
        target_path=fixture.target_path,
        source=fixture.task.reused_source,
    )
    assert result == SandboxFailure(
        "InvalidInput", "repository cases exceed the sandbox storage budget"
    )


@pytest.mark.asyncio
async def test_sandbox_storage_budget_accounts_for_small_file_and_directory_overhead() -> None:
    fixture = REALISTIC_PILOT_FIXTURES[0]
    repository = {fixture.target_path: fixture.task.helper_source}
    repository.update({f"data/d{index}/value.txt": "x" for index in range(199)})
    result = await DockerPythonRunner().run(
        task=fixture.task,
        repository=repository,
        target_path=fixture.target_path,
        source=fixture.task.reused_source,
    )
    assert result == SandboxFailure(
        "InvalidInput", "repository cases exceed the sandbox storage budget"
    )


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
        "PACKAGE_INITIALIZED = False\n\n"
        "def normalize_sku(value):\n"
        "    if not PACKAGE_INITIALIZED:\n"
        "        return \"package-not-initialized\"\n"
        "    return validate_name(value).upper() if value.strip() else \"\"\n"
    )
    repository = dict(fixture.clean_repository)
    repository[fixture.target_path] = target_source
    package_init = "src/marketplace/__init__.py"
    repository[package_init] = (
        repository[package_init]
        + "\nfrom . import normalization\n"
        + "normalization.PACKAGE_INITIALIZED = True\n"
    )
    task = fixture.task.model_copy(update={"helper_source": target_source})
    result = await DockerPythonRunner().run(
        task=task,
        repository=repository,
        target_path=fixture.target_path,
        source=task.reused_source,
    )
    assert isinstance(result, SandboxResult), result
    assert result.passed == result.total == len(task.test_cases)


@pytest.mark.asyncio
@pytest.mark.skipif(
    not RUN_DOCKER_TESTS, reason="requires explicitly prepared pinned Docker runtime"
)
async def test_realistic_package_init_can_be_the_target() -> None:
    fixture = REALISTIC_PILOT_FIXTURES[0]
    target_path = "src/marketplace/__init__.py"
    target_source = "def normalize_sku(value):\n    return value.strip().upper()\n"
    repository = dict(fixture.clean_repository)
    repository[target_path] = target_source
    task = fixture.task.model_copy(
        update={"target_path": target_path, "helper_source": target_source}
    )
    result = await DockerPythonRunner().run(
        task=task,
        repository=repository,
        target_path=target_path,
        source=task.reused_source,
    )
    assert isinstance(result, SandboxResult), result
    assert result.passed == result.total == len(task.test_cases)


@pytest.mark.asyncio
@pytest.mark.skipif(
    not RUN_DOCKER_TESTS, reason="requires explicitly prepared pinned Docker runtime"
)
async def test_sandbox_target_can_shadow_a_cached_standard_library_module() -> None:
    helper_source = "def normalize(value):\n    return value.strip().upper()\n"
    task = CodingTask(
        id="cached-module-target",
        family="architectural",
        instruction="In json.py, add implement(value) returning normalized text.",
        helper="normalize",
        primitives=("strip", "upper"),
        helper_source=helper_source,
        target_path="json.py",
        test_cases=(
            {"input": " abc ", "expected": "ABC"},
            {"input": "x", "expected": "X"},
        ),
        reused_source="def implement(value):\n    return normalize(value)\n",
        duplicated_source="def implement(value):\n    return value.strip().upper()\n",
    )
    result = await DockerPythonRunner().run(
        task=task,
        repository={"json.py": helper_source},
        target_path="json.py",
        source=task.reused_source,
    )
    assert isinstance(result, SandboxResult), result
    assert result.passed == result.total == len(task.test_cases)


@pytest.mark.asyncio
@pytest.mark.skipif(
    not RUN_DOCKER_TESTS, reason="requires explicitly prepared pinned Docker runtime"
)
async def test_sandbox_removes_repository_between_cases() -> None:
    fixture = REALISTIC_PILOT_FIXTURES[0]
    task_value = fixture.task.model_dump(mode="json")
    task_value["test_cases"] = [
        {"input": None, "expected": 1},
        {"input": None, "expected": 1},
        {"input": None, "expected": 1},
    ]
    task = CodingTask.model_validate(task_value)
    source = (
        "from pathlib import Path\n"
        "def implement(value):\n"
        "    return len(tuple(Path('/tmp').glob('assay-repository-*')))\n"
    )
    result = await DockerPythonRunner().run(
        task=task,
        repository=fixture.clean_repository,
        target_path=fixture.target_path,
        source=source,
    )
    assert isinstance(result, SandboxResult), result
    assert result.passed == result.total == 3
