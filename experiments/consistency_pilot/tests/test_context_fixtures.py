from __future__ import annotations

import ast

import pytest
from consistency_pilot.tests.test_layered_fixtures import _run_case

from assay.canonical import canonical_json
from assay.investigations.context_fixtures import (
    CONTEXT_ARMS,
    CONTEXT_TARGETS,
    context_repository_variants,
)
from assay.investigations.correctness import (
    REPOSITORY_STORAGE_BUDGET_BYTES,
    _repository_case_storage_bytes,
)
from assay.investigations.dose_fixtures import (
    DOSE_TASKS,
    PLACEMENT_LAYOUT,
    dose_repository_variants,
)

VARIANTS = context_repository_variants()
TAIL_07 = dose_repository_variants({"tail-07": PLACEMENT_LAYOUT["tail-07"]})


@pytest.mark.parametrize("task", DOSE_TASKS, ids=lambda task: task.id)
def test_padding_only_adds_unrelated_modules(task) -> None:
    arms = VARIANTS[task.id]
    assert tuple(arms) == CONTEXT_ARMS
    base = TAIL_07[task.id]["tail-07"]
    assert arms["ctx-00"] == base
    for arm, repository in arms.items():
        assert {path: repository[path] for path in base} == base
        added = {path: content for path, content in repository.items() if path not in base}
        for path, content in added.items():
            ast.parse(content)
            assert task.helper not in content, path
        size = sum(len(content.encode()) for content in repository.values())
        assert size >= CONTEXT_TARGETS[arm]
        prompt = canonical_json({"instruction": task.instruction, "repository": repository})
        assert len(prompt) <= 131_072
        storage = _repository_case_storage_bytes(repository, task.target_path, task.reused_source)
        assert storage <= REPOSITORY_STORAGE_BUDGET_BYTES


@pytest.mark.parametrize("task", DOSE_TASKS, ids=lambda task: task.id)
def test_reference_sources_pass_in_the_largest_repository(task) -> None:
    repository = VARIANTS[task.id]["ctx-90"]
    for source in (task.reused_source, task.duplicated_source):
        case = task.test_cases[0]
        actual = _run_case(repository, task.target_path, source, case.input)
        assert canonical_json(actual) == canonical_json(case.expected)
