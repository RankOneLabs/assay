from __future__ import annotations

import ast
import json
import subprocess
import sys

import pytest

from assay.canonical import canonical_json
from assay.execution import EvaluationSuccess
from assay.investigations.consistency import StructuralEvaluator, parse_candidate_source
from assay.investigations.correctness import _CANDIDATE_HARNESS
from assay.investigations.layered_fixtures import LAYERED_TASKS, layered_repository_variants
from assay.models import EvaluationCoordinate

VARIANTS = layered_repository_variants()


def _run_case(repository: dict[str, str], target_path: str, source: str, value: object) -> object:
    """The sandbox's per-case child harness, run locally without Docker."""
    payload = {
        "repository": repository,
        "target_path": target_path,
        "source": source,
        "input": value,
    }
    completed = subprocess.run(
        [sys.executable, "-I", "-S", "-c", _CANDIDATE_HARNESS],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    result = json.loads(completed.stdout)
    assert result["ok"], result
    return result["actual"]


def test_population_shape() -> None:
    assert len(LAYERED_TASKS) == 12
    assert len({task.id for task in LAYERED_TASKS}) == 12
    families = [task.family for task in LAYERED_TASKS]
    assert {family: families.count(family) for family in families} == {
        "route-view": 4,
        "domain-rule": 4,
        "cross-module": 4,
    }
    assert set(VARIANTS) == {task.id for task in LAYERED_TASKS}


@pytest.mark.parametrize("task", LAYERED_TASKS, ids=lambda task: task.id)
def test_arms_differ_only_in_how_the_target_reaches_the_behaviour(task) -> None:
    clean = VARIANTS[task.id]["clean"]
    inconsistent = VARIANTS[task.id]["inconsistent"]
    assert clean.keys() == inconsistent.keys()
    assert [path for path in clean if clean[path] != inconsistent[path]] == [task.target_path]
    helper_path = "src/" + task.helper_module.replace(".", "/") + ".py"
    assert clean[helper_path] == task.helper_source
    assert f"def {task.helper}(" in task.helper_source
    for repository in (clean, inconsistent):
        assert "def implement(" not in repository[task.target_path]
        # The model sees the repository as canonical JSON with the instruction.
        prompt = canonical_json({"instruction": task.instruction, "repository": repository})
        assert len(prompt) < 24_000
    clean_target = clean[task.target_path]
    inconsistent_target = inconsistent[task.target_path]
    assert task.helper not in inconsistent_target
    inline_calls = {
        node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", None)
        for node in ast.walk(ast.parse(inconsistent_target))
        if isinstance(node, ast.Call)
    }
    assert set(task.primitives) <= inline_calls
    if task.family == "route-view":
        # The view to reuse exists but is not routed in either arm.
        assert task.helper not in clean_target
        assert not any(primitive in clean_target for primitive in task.primitives)
    else:
        assert clean_target.count(f"{task.helper}(") >= 3


@pytest.mark.parametrize("task", LAYERED_TASKS, ids=lambda task: task.id)
def test_reference_sources_pass_in_both_arms(task) -> None:
    for arm in ("clean", "inconsistent"):
        repository = VARIANTS[task.id][arm]
        for source in (task.reused_source, task.duplicated_source):
            parse_candidate_source(
                source,
                helper=task.helper,
                target_path=task.target_path,
                helper_module=task.helper_module,
            )
            for case in task.test_cases:
                actual = _run_case(repository, task.target_path, source, case.input)
                assert canonical_json(actual) == canonical_json(case.expected), (arm, source)


@pytest.mark.asyncio
@pytest.mark.parametrize("task", LAYERED_TASKS, ids=lambda task: task.id)
async def test_reference_sources_classify(task) -> None:
    evaluator = StructuralEvaluator()
    for source, expected in (
        (task.reused_source, "reused"),
        (task.duplicated_source, "duplicated"),
    ):
        result = await evaluator.evaluate(
            input_value={"task": task.model_dump(mode="json")},
            output={"source": source},
            coordinate=EvaluationCoordinate(
                cell_id=f"{task.id}:clean:w0", evaluator_id="abstraction", evaluator_repeat=0
            ),
        )
        assert isinstance(result, EvaluationSuccess), result
        assert result.verdict == expected


async def verdict(source: str) -> str:
    """Structural verdict (or failure type) for an email-key submission."""
    task = next(item for item in LAYERED_TASKS if item.id == "email-key")
    result = await StructuralEvaluator().evaluate(
        input_value={"task": task.model_dump(mode="json")},
        output={"source": source},
        coordinate=EvaluationCoordinate(
            cell_id="email-key:clean:w0", evaluator_id="abstraction", evaluator_repeat=0
        ),
    )
    return getattr(result, "verdict", None) or result.error_type


@pytest.mark.asyncio
async def test_helper_imports_are_accepted_only_from_the_helper_module() -> None:
    body = '\ndef implement(payload):\n    return normalize_email(payload["email"])\n'
    assert await verdict("from accounts.utils import normalize_email" + body) == "reused"
    assert await verdict("from .utils import normalize_email" + body) == "reused"
    assert await verdict("from accounts.audit import normalize_email" + body) == "InvalidOutput"
    assert await verdict("import normalize_email" + body) == "InvalidOutput"
    assert (
        await verdict(
            "from accounts import utils\n"
            'def implement(payload):\n    return utils.normalize_email(payload["email"])\n'
        )
        == "reused"
    )
    assert (
        await verdict(
            "from accounts.utils import normalize_email as canon\n"
            'def implement(payload):\n    return canon(payload["email"])\n'
        )
        == "reused"
    )


@pytest.mark.asyncio
async def test_function_local_imports_count_only_for_the_helper_module() -> None:
    local = 'def implement(payload):\n    from {} import {}\n    return {}(payload["email"])\n'
    helper = local.format("accounts.utils", "normalize_email", "normalize_email")
    aliased = local.format("accounts.utils", "normalize_email as canon", "canon")
    impostor = local.format("accounts.audit", "email_domain as normalize_email", "normalize_email")
    assert await verdict(helper) == "reused"
    assert await verdict(aliased) == "reused"
    assert await verdict(impostor) == "AmbiguousStructure"
    for bound in ("normalize_email", "normalize_email as canon"):
        conditional = (
            "def implement(payload):\n    if payload:\n"
            f"        from accounts.utils import {bound}\n"
            f'    return {bound.split()[-1]}(payload["email"])\n'
        )
        assert await verdict(conditional) == "AmbiguousStructure"


@pytest.mark.asyncio
async def test_helper_calls_need_the_helper_origin() -> None:
    method = 'def implement(payload):\n    return payload.normalize_email(payload["email"])\n'
    elsewhere = (
        "from accounts.audit import normalize_email as canon\n"
        'def implement(payload):\n    return canon(payload["email"])\n'
    )
    assert await verdict(method) == "AmbiguousStructure"
    assert await verdict(elsewhere) == "AmbiguousStructure"


@pytest.mark.asyncio
async def test_nothing_after_a_returning_try_or_with_body_is_unconditional() -> None:
    after_try = (
        "def implement(payload):\n    try:\n        return payload.strip().lower()\n"
        "    except AttributeError:\n        pass\n"
        '    return normalize_email(payload["email"])\n'
    )
    after_with = (
        "import contextlib\n"
        "def implement(payload):\n    with contextlib.suppress(KeyError):\n"
        "        return payload\n"
        '    return normalize_email(payload["email"])\n'
    )
    assert await verdict(after_try) == "AmbiguousStructure"
    assert await verdict(after_with) == "AmbiguousStructure"
