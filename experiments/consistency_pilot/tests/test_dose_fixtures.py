from __future__ import annotations

import ast

import pytest
from consistency_pilot.tests.test_layered_fixtures import _run_case

from assay.canonical import canonical_json
from assay.execution import EvaluationSuccess
from assay.investigations.consistency import StructuralEvaluator
from assay.investigations.dose_fixtures import (
    DOSE_ARMS,
    DOSE_TASKS,
    MESS_POSITIONS,
    dose_repository_variants,
)
from assay.models import EvaluationCoordinate

VARIANTS = dose_repository_variants()


def _functions(source: str) -> dict[str, ast.FunctionDef]:
    return {node.name: node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef)}


def _uses_abstraction(function: ast.FunctionDef, helper: str) -> bool:
    return any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and (node.func.id == helper or node.func.id.endswith("_view"))
        for node in ast.walk(function)
    )


def test_mess_levels_are_nested_and_keep_the_last_caller_clean() -> None:
    levels = sorted(MESS_POSITIONS)
    assert tuple(f"mess-{level:02d}" for level in levels) == DOSE_ARMS
    for lower, higher in zip(levels, levels[1:], strict=False):
        assert set(MESS_POSITIONS[lower]) < set(MESS_POSITIONS[higher])
    for level, positions in MESS_POSITIONS.items():
        assert len(positions) == level
        if level < 10:
            assert 9 not in positions


@pytest.mark.parametrize("task", DOSE_TASKS, ids=lambda task: task.id)
def test_arms_differ_only_in_how_many_callers_bypass_the_abstraction(task) -> None:
    arms = VARIANTS[task.id]
    assert tuple(arms) == DOSE_ARMS
    baseline = arms["mess-00"]
    helper_path = "src/" + task.helper_module.replace(".", "/") + ".py"
    assert baseline[helper_path] == task.helper_source
    distractors = {
        name
        for name, function in _functions(baseline[task.target_path]).items()
        if not _uses_abstraction(function, task.helper)
    }
    for arm, repository in arms.items():
        assert repository.keys() == baseline.keys()
        assert [p for p in repository if repository[p] != baseline[p]] in ([], [task.target_path])
        target = repository[task.target_path]
        functions = _functions(target)
        assert len(functions) == 10 + len(distractors)
        assert "implement" not in functions and task.helper not in functions
        bypassing = [
            name
            for name, function in functions.items()
            if name not in distractors and not _uses_abstraction(function, task.helper)
        ]
        assert len(bypassing) == int(arm.removeprefix("mess-"))
        tree = ast.parse(target)
        imported = {
            alias.asname or alias.name
            for node in tree.body
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
        }
        loaded = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        assert imported <= loaded, imported - loaded
        prompt = canonical_json({"instruction": task.instruction, "repository": repository})
        assert len(prompt) < 30_000


@pytest.mark.parametrize("task", DOSE_TASKS, ids=lambda task: task.id)
def test_reference_sources_pass_at_every_mess_level(task) -> None:
    for arm in DOSE_ARMS:
        repository = VARIANTS[task.id][arm]
        for source in (task.reused_source, task.duplicated_source):
            for case in task.test_cases:
                actual = _run_case(repository, task.target_path, source, case.input)
                assert canonical_json(actual) == canonical_json(case.expected), (arm, source)


@pytest.mark.asyncio
@pytest.mark.parametrize("task", DOSE_TASKS, ids=lambda task: task.id)
async def test_reference_sources_classify(task) -> None:
    for source, expected in (
        (task.reused_source, "reused"),
        (task.duplicated_source, "duplicated"),
    ):
        result = await StructuralEvaluator().evaluate(
            input_value={"task": task.model_dump(mode="json")},
            output={"source": source},
            coordinate=EvaluationCoordinate(
                cell_id=f"{task.id}:mess-00:w0", evaluator_id="abstraction", evaluator_repeat=0
            ),
        )
        assert isinstance(result, EvaluationSuccess), result
        assert result.verdict == expected
