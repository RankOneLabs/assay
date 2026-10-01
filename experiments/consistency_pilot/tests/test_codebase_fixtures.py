from __future__ import annotations

import ast
import json
import re
import subprocess
import sys

import pytest

from assay.canonical import canonical_json
from assay.execution import EvaluationSuccess
from assay.investigations.codebase_fixtures import (
    CODEBASE_TASKS,
    SNAPSHOTS,
    codebase_repository_variants,
)
from assay.investigations.consistency import StructuralEvaluator
from assay.investigations.correctness import (
    _CANDIDATE_HARNESS,
    DockerRunnerSettings,
    _repository_case_storage_bytes,
)
from assay.models import EvaluationCoordinate

VARIANTS = codebase_repository_variants()


def _helper_path(task) -> str:
    return "src/" + task.helper_module.replace(".", "/") + ".py"


def _run_case(repository: dict[str, str], target_path: str, source: str, value: object) -> object:
    """The sandbox's per-case child harness, run locally without Docker.

    Unlike the sandbox, site-packages stays on the path: the snapshots import
    httpx, aiosqlite and pydantic, which the codebase sandbox image provides.
    """
    payload = {
        "repository": repository,
        "target_path": target_path,
        "source": source,
        "input": value,
    }
    completed = subprocess.run(
        [sys.executable, "-I", "-c", _CANDIDATE_HARNESS],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    result = json.loads(completed.stdout)
    assert result["ok"], result
    return result["actual"]


def test_population_shape() -> None:
    assert len({task.id for task in CODEBASE_TASKS}) == len(CODEBASE_TASKS) == 11
    families = [task.family for task in CODEBASE_TASKS]
    assert {family: families.count(family) for family in families} == {
        "jig-llm": 4,
        "jig-feedback": 3,
        "scout-platforms": 4,
    }
    assert set(VARIANTS) == {task.id for task in CODEBASE_TASKS}
    for snapshot in SNAPSHOTS.values():
        assert re.fullmatch(r"[0-9a-f]{40}", snapshot["commit"])
        assert snapshot["repository"].endswith(("/jig.git", "/scout.git"))


@pytest.mark.parametrize("task", CODEBASE_TASKS, ids=lambda task: task.id)
def test_arms_differ_only_in_the_helpers_callers(task) -> None:
    clean = VARIANTS[task.id]["clean"]
    inconsistent = VARIANTS[task.id]["inconsistent"]
    assert clean.keys() == inconsistent.keys()
    snapshot = SNAPSHOTS[task.family]["files"]
    assert {path: clean[path] for path in snapshot} == snapshot
    call = re.compile(rf"\b{task.helper}\(")
    callers = {
        path for path, text in clean.items() if path != _helper_path(task) and call.search(text)
    }
    assert len(callers) >= 2
    changed = {path for path in clean if clean[path] != inconsistent[path]}
    assert changed == callers
    assert not any(call.search(inconsistent[path]) for path in changed)
    assert f"def {task.helper}(" in task.helper_source
    assert task.helper_source in clean[_helper_path(task)]
    helper_import = f"from {task.helper_module} import {task.helper}\n"
    assert helper_import in clean[task.target_path]
    assert not call.search(clean[task.target_path])
    assert clean[task.target_path] == inconsistent[task.target_path]
    budget = DockerRunnerSettings(tmpfs_size="4m").repository_storage_budget_bytes
    for repository in (clean, inconsistent):
        for path, text in repository.items():
            ast.parse(text, path)
        prompt = canonical_json({"instruction": task.instruction, "repository": repository})
        assert len(prompt) <= 196_608
        storage = _repository_case_storage_bytes(repository, task.target_path, task.reused_source)
        assert storage * len(task.test_cases) <= budget


@pytest.mark.parametrize("task", CODEBASE_TASKS, ids=lambda task: task.id)
def test_reference_sources_pass_in_both_arms(task) -> None:
    for arm in ("clean", "inconsistent"):
        repository = VARIANTS[task.id][arm]
        for source in (task.reused_source, task.duplicated_source):
            for case in task.test_cases:
                actual = _run_case(repository, task.target_path, source, case.input)
                assert canonical_json(actual) == canonical_json(case.expected), (arm, source)


@pytest.mark.asyncio
@pytest.mark.parametrize("task", CODEBASE_TASKS, ids=lambda task: task.id)
async def test_reference_sources_classify(task) -> None:
    for source, expected in (
        (task.reused_source, "reused"),
        (task.duplicated_source, "duplicated"),
    ):
        result = await StructuralEvaluator().evaluate(
            input_value={"task": task.model_dump(mode="json")},
            output={"source": source},
            coordinate=EvaluationCoordinate(
                cell_id=f"{task.id}:clean:w0", evaluator_id="abstraction", evaluator_repeat=0
            ),
        )
        assert isinstance(result, EvaluationSuccess), result
        assert result.verdict == expected
