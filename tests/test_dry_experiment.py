from __future__ import annotations

import asyncio
import copy
import json
import os
from pathlib import Path
from typing import Any

import paa_contracts
import pytest
from jig.core.types import CompletionParams, LLMResponse, ToolCall, Usage
from pydantic import ValidationError

from assay.adapters.consistency import DescribedClient
from assay.adapters.openrouter import HAIKU_BEDROCK, OpenRouterFactory
from assay.execution import EvaluationFailed, EvaluationSuccess
from assay.investigations.consistency import EXPERIMENT_TASKS, CodingTask, StructuralEvaluator
from assay.investigations.correctness import (
    DockerPythonRunner,
    DockerRunnerSettings,
    FunctionalCorrectnessEvaluator,
    SandboxFailure,
    SandboxResult,
)
from assay.investigations.dry_experiment import (
    DryExperimentFailed,
    DryExperimentPrepared,
    DryExperimentSucceeded,
    haiku_dry_settings,
    prepare_dry_experiment,
    run_dry_experiment,
)
from assay.models import EvaluationCoordinate, ExecutionPlan, StudySnapshot
from assay.store import ObjectStore
from assay.verify import verify_bundle, verify_manifest

RUN_DOCKER_TESTS = os.environ.get("ASSAY_RUN_DOCKER_TESTS") == "1"


def contracts() -> dict[str, dict[str, Any]]:
    return {
        name: paa_contracts.load_schema(name)
        for name in ("paa-task", "paa-evidence-record", "paa-operating-record")
    }


class FakeFactory:
    def __init__(self) -> None:
        self.calls: list[CompletionParams] = []
        self.created = 0
        self.closed = 0

    def configuration(self) -> dict[str, Any]:
        return OpenRouterFactory(HAIKU_BEDROCK).configuration()

    def create(self) -> DescribedClient:
        self.created += 1
        owner = self

        class Client(DescribedClient):
            def configuration(self) -> dict[str, Any]:
                return owner.configuration()

            async def complete(self, params: CompletionParams) -> LLMResponse:
                owner.calls.append(copy.deepcopy(params))
                prompt = json.loads(params.messages[0].content)
                task = next(
                    item for item in EXPERIMENT_TASKS if item.instruction == prompt["instruction"]
                )
                repository_source = prompt["repository"]["module.py"]
                source = (
                    task.reused_source
                    if f"return {task.helper}(" in repository_source
                    else task.duplicated_source
                )
                return LLMResponse(
                    content="",
                    tool_calls=[
                        ToolCall(
                            "submission",
                            "submit_output",
                            {"source": source},
                        )
                    ],
                    usage=Usage(10, 5, 0.001),
                    latency_ms=1,
                    model=HAIKU_BEDROCK.model,
                )

            async def aclose(self) -> None:
                owner.closed += 1

        return Client()


class PassingRunner(DockerPythonRunner):
    async def run(
        self, *, task: CodingTask, repository_source: str, source: str
    ) -> SandboxResult | SandboxFailure:
        del repository_source, source
        return SandboxResult(len(task.test_cases), len(task.test_cases), ())


class BoundaryRunner(DockerPythonRunner):
    async def _check_runtime(self) -> SandboxFailure | None:
        return None

    async def _finish_cleanup(self, process: Any, name: str) -> bool:
        del process, name
        return True


def coordinate() -> EvaluationCoordinate:
    return EvaluationCoordinate(
        cell_id="subject:clean:w0", evaluator_id="correctness", evaluator_repeat=0
    )


def repository(task: CodingTask, source: str) -> str:
    return task.helper_source + "\n" + source.replace("implement", "existing_feature")


def test_experiment_population_is_balanced_and_has_hidden_cases() -> None:
    assert len(EXPERIMENT_TASKS) == 12
    assert {
        family: sum(task.family == family for task in EXPERIMENT_TASKS)
        for family in (
            "cosmetic",
            "architectural",
            "semantic",
        )
    } == {"cosmetic": 4, "architectural": 4, "semantic": 4}
    assert len({task.id for task in EXPERIMENT_TASKS}) == 12
    assert all(len(task.test_cases) >= 3 for task in EXPERIMENT_TASKS)


def test_prepare_rejects_governed_profile_drift_before_client_creation(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path / "store")
    factory = FakeFactory()
    changed_settings = haiku_dry_settings().model_copy(update={"max_total_requests": 49})
    result = prepare_dry_experiment(
        store,
        factory=factory,
        settings=changed_settings,
        schemas=contracts(),
        runner=PassingRunner(),
    )
    assert isinstance(result, DryExperimentFailed)
    assert result.error_type == "ValueError"
    assert factory.created == 0

    class ChangedFactory(FakeFactory):
        def configuration(self) -> dict[str, Any]:
            configuration = super().configuration()
            return {**configuration, "model": "different/model"}

    changed_factory = ChangedFactory()
    result = prepare_dry_experiment(
        store,
        factory=changed_factory,
        settings=haiku_dry_settings(),
        schemas=contracts(),
        runner=PassingRunner(),
    )
    assert isinstance(result, DryExperimentFailed)
    assert result.error_type == "ValueError"
    assert changed_factory.created == 0


@pytest.mark.asyncio
async def test_all_reference_sources_have_declared_structure() -> None:
    evaluator = StructuralEvaluator()
    for task in EXPERIMENT_TASKS:
        for source, expected in (
            (task.reused_source, "reused"),
            (task.duplicated_source, "duplicated"),
        ):
            result = await evaluator.evaluate(
                input_value={"task": task.model_dump(mode="json")},
                output={"source": source},
                coordinate=EvaluationCoordinate(
                    cell_id=f"{task.id}:clean:w0",
                    evaluator_id="abstraction",
                    evaluator_repeat=0,
                ),
            )
            assert isinstance(result, EvaluationSuccess), result
            assert result.verdict == expected


@pytest.mark.asyncio
async def test_structural_docstrings_primitives_and_source_boundary() -> None:
    evaluator = StructuralEvaluator()
    task = next(item for item in EXPERIMENT_TASKS if item.id == "canonical-email")

    async def evaluate(source: str) -> EvaluationSuccess | EvaluationFailed:
        return await evaluator.evaluate(
            input_value={"task": task.model_dump(mode="json")},
            output={"source": source},
            coordinate=EvaluationCoordinate(
                cell_id="canonical-email:clean:w0",
                evaluator_id="abstraction",
                evaluator_repeat=0,
            ),
        )

    docstring = await evaluate(
        'def implement(value):\n    """Normalize the email."""\n'
        "    return normalize_email(value)\n"
    )
    assert isinstance(docstring, EvaluationSuccess), docstring
    assert docstring.verdict == "reused"

    annotated = await evaluate(
        "def implement(value: str) -> str:\n    return normalize_email(value)\n"
    )
    assert isinstance(annotated, EvaluationSuccess), annotated
    assert annotated.verdict == "reused"

    mixed = await evaluate(
        "def implement(value):\n    return normalize_email(value.strip())\n"
    )
    assert isinstance(mixed, EvaluationSuccess), mixed
    assert mixed.verdict == "mixed"

    ambiguous = await evaluate(
        "def implement(value):\n    result = normalize_email(value)\n    return result\n"
    )
    assert isinstance(ambiguous, EvaluationFailed), ambiguous
    assert ambiguous.error_type == "AmbiguousStructure"

    replacement = await evaluate(
        "def normalize_email(value):\n    return value\n"
        "def implement(value):\n    return normalize_email(value)\n"
    )
    assert isinstance(replacement, EvaluationFailed), replacement
    assert replacement.error_type == "InvalidOutput"

    decoding = next(item for item in EXPERIMENT_TASKS if item.id == "record-decoding")

    async def evaluate_decoding(source: str) -> EvaluationSuccess | EvaluationFailed:
        return await evaluator.evaluate(
            input_value={"task": decoding.model_dump(mode="json")},
            output={"source": source},
            coordinate=EvaluationCoordinate(
                cell_id="record-decoding:clean:w0",
                evaluator_id="abstraction",
                evaluator_repeat=0,
            ),
        )

    qualified = await evaluate_decoding(
        "def implement(value):\n    return json.loads(value)\n"
    )
    assert isinstance(qualified, EvaluationSuccess), qualified
    assert qualified.verdict == "duplicated"

    aliased = await evaluate_decoding(
        "from json import loads as decode\n"
        "def implement(value):\n    return decode(value)\n"
    )
    assert isinstance(aliased, EvaluationSuccess), aliased
    assert aliased.verdict == "duplicated"

    wrong_origin = await evaluate_decoding(
        "import pickle\ndef implement(value):\n    return pickle.loads(value)\n"
    )
    assert isinstance(wrong_origin, EvaluationFailed), wrong_origin
    assert wrong_origin.error_type == "AmbiguousStructure"
    assert wrong_origin.detail == {
        "route": "structural",
        "calls": ["pickle.loads"],
        "family": "architectural",
    }


def test_legacy_task_shape_remains_valid_for_structural_evaluation() -> None:
    task = EXPERIMENT_TASKS[0].model_dump(mode="json")
    task["primitive"] = task.pop("primitives")[0]
    task.pop("test_cases")
    parsed = CodingTask.model_validate(task)
    assert parsed.primitives == (task["primitive"],)
    assert parsed.test_cases == ()


def test_sandbox_configuration_binds_isolation_and_runtime() -> None:
    configuration = DockerPythonRunner().configuration()
    assert configuration["host_mounts"] == []
    assert configuration["network"] == "none"
    assert configuration["root_filesystem"] == "read-only"
    assert configuration["capabilities"] == "drop-all"
    assert configuration["no_new_privileges"] is True
    assert configuration["seccomp"] == "builtin"
    assert configuration["pull"] == "never"
    assert configuration["settings"] == {
        "image": ("python@sha256:2be5d3cb08aa616c6e38d922bd7072975166b2de772004f79ee1bae59fe983dc"),
        "platform": "linux/amd64",
        "docker_client_version": "29.6.1",
        "docker_server_version": "29.1.2",
        "command_timeout_s": 5.0,
        "startup_timeout_s": 10.0,
        "timeout_s": 5.0,
        "max_output_bytes": 65_536,
        "memory": "64m",
        "cpus": "0.5",
        "pids_limit": 32,
    }
    assert DockerPythonRunner(
        DockerRunnerSettings(max_output_bytes=1024)
    ).configuration()["harness_sha256"] != configuration["harness_sha256"]
    with pytest.raises(ValidationError):
        DockerRunnerSettings(image="python:latest")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("command_timeout_s", 0),
        ("startup_timeout_s", -1),
        ("timeout_s", float("inf")),
        ("max_output_bytes", 0),
    ],
)
def test_sandbox_settings_reject_nonpositive_or_nonfinite_bounds(
    field: str, value: float
) -> None:
    with pytest.raises(ValidationError):
        DockerRunnerSettings.model_validate({field: value})


@pytest.mark.asyncio
async def test_pre_readiness_timeout_is_infrastructure_failure(monkeypatch: Any) -> None:
    class Writer:
        def write(self, value: bytes) -> None:
            del value

        async def drain(self) -> None:
            return None

        def close(self) -> None:
            return None

    class NeverReady:
        async def readexactly(self, size: int) -> bytes:
            del size
            await asyncio.Future()
            raise AssertionError

    class Process:
        stdin = Writer()
        stdout = NeverReady()
        stderr = NeverReady()
        returncode = None

    async def create(*args: Any, **kwargs: Any) -> Process:
        del args, kwargs
        return Process()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create)
    runner = BoundaryRunner(DockerRunnerSettings(startup_timeout_s=0.01))
    task = EXPERIMENT_TASKS[0]
    result = await runner.run(
        task=task,
        repository_source=repository(task, task.reused_source),
        source=task.reused_source,
    )
    assert isinstance(result, SandboxFailure), result
    assert result.error_type == "SandboxStartupTimeout"


@pytest.mark.asyncio
@pytest.mark.skipif(
    not RUN_DOCKER_TESTS, reason="requires explicitly prepared pinned Docker runtime"
)
async def test_pinned_container_accepts_both_reference_implementations() -> None:
    runner = DockerPythonRunner()
    for task in EXPERIMENT_TASKS:
        for source in (task.reused_source, task.duplicated_source):
            result = await runner.run(
                task=task,
                repository_source=repository(task, source),
                source=source,
            )
            assert isinstance(result, SandboxResult), result
            assert result.passed == result.total == len(task.test_cases)
            assert not result.failures


@pytest.mark.asyncio
@pytest.mark.skipif(
    not RUN_DOCKER_TESTS, reason="requires explicitly prepared pinned Docker runtime"
)
async def test_container_failures_are_bounded_incorrect_verdicts() -> None:
    runner = DockerPythonRunner(DockerRunnerSettings(timeout_s=3.0))
    evaluator = FunctionalCorrectnessEvaluator(runner)
    task = EXPERIMENT_TASKS[0]
    for source, expected_kind in (
        ("def implement(value):\n    return 'wrong'\n", "mismatch"),
        ("def implement(value):\n    while True:\n        pass\n", "timeout"),
        (
            "import os\ndef implement(value):\n    os.write(1, b'x' * 70000)\n    return value\n",
            "output_limit",
        ),
    ):
        result = await evaluator.evaluate(
            input_value={
                "task": task.model_dump(mode="json"),
                "repository": {"module.py": repository(task, task.reused_source)},
            },
            output={"source": source},
            coordinate=coordinate(),
        )
        assert isinstance(result, EvaluationSuccess), result
        assert result.verdict == "incorrect"
        assert {item["kind"] for item in result.detail["failures"]} == {expected_kind}


@pytest.mark.asyncio
@pytest.mark.skipif(
    not RUN_DOCKER_TESTS, reason="requires explicitly prepared pinned Docker runtime"
)
async def test_candidate_cannot_forge_supervisor_result_protocol() -> None:
    runner = DockerPythonRunner()
    task = EXPERIMENT_TASKS[0]
    forged = json.dumps(
        {"passed": len(task.test_cases), "total": len(task.test_cases), "failures": []},
        separators=(",", ":"),
    )
    source = (
        "import os\n"
        "def implement(value):\n"
        f"    os.write(1, {forged.encode()!r})\n"
        "    os._exit(0)\n"
    )
    result = await runner.run(
        task=task,
        repository_source=repository(task, task.reused_source),
        source=source,
    )
    assert isinstance(result, SandboxResult), result
    assert result.passed == 0
    assert {item["kind"] for item in result.failures} == {"protocol_error"}


@pytest.mark.asyncio
@pytest.mark.skipif(
    not RUN_DOCKER_TESTS, reason="requires explicitly prepared pinned Docker runtime"
)
async def test_container_has_no_network_root_write_or_provider_credential() -> None:
    runner = DockerPythonRunner()
    base = EXPERIMENT_TASKS[0]
    task_value = base.model_dump(mode="json")
    task_value["test_cases"] = [{"input": None, "expected": True}]
    task = CodingTask.model_validate(task_value)
    sources = (
        (
            "def implement(value):\n"
            "    try:\n"
            "        open('/assay-write-probe', 'w')\n"
            "    except OSError:\n"
            "        return True\n"
            "    return False\n"
        ),
        (
            "import socket\n"
            "def implement(value):\n"
            "    connection = socket.socket()\n"
            "    connection.settimeout(0.25)\n"
            "    try:\n"
            "        connection.connect(('1.1.1.1', 80))\n"
            "    except OSError:\n"
            "        return True\n"
            "    finally:\n"
            "        connection.close()\n"
            "    return False\n"
        ),
        ("import os\ndef implement(value):\n    return 'OPENROUTER_API_KEY' not in os.environ\n"),
    )
    for source in sources:
        result = await runner.run(task=task, repository_source=task.helper_source, source=source)
        assert isinstance(result, SandboxResult), result
        assert result.passed == result.total == 1


@pytest.mark.asyncio
async def test_prepare_and_run_full_offline_acceptance(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path / "store")
    factory = FakeFactory()
    runner = PassingRunner()
    prepared = prepare_dry_experiment(
        store,
        factory=factory,
        settings=haiku_dry_settings(),
        schemas=contracts(),
        runner=runner,
    )
    assert isinstance(prepared, DryExperimentPrepared), prepared
    assert prepared.executions == 48 and prepared.evaluations == 96
    assert factory.created == 0
    snapshot = StudySnapshot.model_validate_json(store.read_bytes(prepared.snapshot_ref))
    plan = ExecutionPlan.model_validate_json(store.read_bytes(prepared.plan_ref))
    assert {arm.conditions["assay_execution_schedule"] for arm in snapshot.arms} == {
        "subject-counterbalanced-v1"
    }
    ordered_subjects = sorted(subject.id for subject in snapshot.subjects)
    for subject_index, subject_id in enumerate(ordered_subjects):
        cells = [cell for cell in plan.cells if cell.subject_id == subject_id]
        expected = (
            [
                ("clean", 0),
                ("inconsistent", 0),
                ("inconsistent", 1),
                ("clean", 1),
            ]
            if subject_index % 2 == 0
            else [
                ("inconsistent", 0),
                ("clean", 0),
                ("clean", 1),
                ("inconsistent", 1),
            ]
        )
        assert [(cell.arm_id, cell.worker_repeat) for cell in cells] == expected

    denied = await run_dry_experiment(
        store,
        plan_ref=prepared.plan_ref,
        authorization=prepared.plan_ref,
        factory=factory,
        runner=runner,
    )
    assert isinstance(denied, DryExperimentFailed)
    assert not factory.calls

    occupied_destination = tmp_path / "occupied-bundle"
    occupied_destination.mkdir()
    blocked_export = await run_dry_experiment(
        store,
        plan_ref=prepared.plan_ref,
        authorization=prepared.plan_ref,
        factory=factory,
        runner=runner,
        allow_paid=True,
        export_destination=occupied_destination,
    )
    assert isinstance(blocked_export, DryExperimentFailed)
    assert not factory.calls

    destination = tmp_path / "bundle"
    result = await run_dry_experiment(
        store,
        plan_ref=prepared.plan_ref,
        authorization=prepared.plan_ref,
        factory=factory,
        runner=runner,
        allow_paid=True,
        export_destination=destination,
    )
    assert isinstance(result, DryExperimentSucceeded), result
    assert factory.created == factory.closed == len(factory.calls) == 48
    assert verify_manifest(store, result.manifest_ref) == ()
    assert (
        verify_bundle(ObjectStore(destination / "abstraction"), result.abstraction_report_ref) == ()
    )
    assert (
        verify_bundle(ObjectStore(destination / "correctness"), result.correctness_report_ref) == ()
    )

    abstraction = json.loads(store.read_bytes(result.abstraction_report_ref))
    correctness = json.loads(store.read_bytes(result.correctness_report_ref))
    for report in (abstraction, correctness):
        comparison = report["comparisons"][0]
        assert comparison["n"] == 12
        assert not comparison["non_common_subjects"]
    abstraction_comparison = abstraction["comparisons"][0]
    assert abstraction_comparison["reference"] == "inconsistent"
    assert abstraction_comparison["candidate"] == "clean"
    assert abstraction_comparison["reference_distribution"] == {"duplicated": 12}
    assert abstraction_comparison["candidate_distribution"] == {"reused": 12}
    assert abstraction_comparison["improved"] == 12
    assert abstraction_comparison["regressed"] == 0
    assert abstraction_comparison["p_value"] == 2 / 4096
    assert abstraction_comparison["decision"] == "improved"
    assert correctness["comparisons"][0]["reference_distribution"] == {"correct": 12}
    assert correctness["comparisons"][0]["candidate_distribution"] == {"correct": 12}
    assert correctness["comparisons"][0]["p_value"] == 1.0
    assert correctness["comparisons"][0]["decision"] == "no_detected_difference"
