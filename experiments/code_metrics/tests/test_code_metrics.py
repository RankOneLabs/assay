from __future__ import annotations

import pytest
from code_metrics import METRICS, measure, tool_versions

from metric_snapshots import BEFORE, DELEGATING, INLINED, _after


def test_unchanged_snapshot_measures_zero() -> None:
    result = measure(BEFORE, dict(BEFORE))
    assert set(result) == set(METRICS)
    assert all(value == 0 for value in result.values())


def test_delegating_change_adds_little() -> None:
    result = measure(BEFORE, _after(DELEGATING))
    assert result["radon.sloc"] == 2
    assert result["radon.cc"] == 1
    assert result["complexipy.cognitive"] == 0
    assert result["grimp.imports"] == 0
    assert result["new_lines"] == 2
    assert result["new_duplicated_lines"] == 0
    assert result["new_max_nesting_depth"] == 0


def test_inlined_copy_is_larger_more_complex_coupled_and_cloned() -> None:
    result = measure(
        BEFORE,
        _after(INLINED, "from shop.store import audit, load\n"),
        clone_min_lines=3,
        clone_min_tokens=15,
    )
    delegating = measure(BEFORE, _after(DELEGATING))
    assert result["radon.sloc"] > delegating["radon.sloc"]
    assert result["radon.cc"] == 4
    assert result["complexipy.cognitive"] > 0
    assert result["radon.halstead_volume"] > delegating["radon.halstead_volume"]
    assert result["grimp.imports"] == 1
    assert result["ruff.magic_values"] == 0
    assert result["jscpd.clones"] >= 1
    assert result["new_duplicated_lines"] == 4
    assert result["new_max_nesting_depth"] == 2


def test_default_clone_thresholds_miss_small_copies() -> None:
    result = measure(BEFORE, _after(INLINED, "from shop.store import audit, load\n"))
    assert result["jscpd.clones"] == 0


def test_undefined_names_count_as_ruff_and_mypy_findings() -> None:
    result = measure(BEFORE, _after("\n\ndef broken(request):\n    return missing(request)\n"))
    assert result["ruff.violations"] == 1
    assert result["mypy.errors"] == 1


def test_magic_value_comparison() -> None:
    result = measure(BEFORE, _after("\n\ndef big(request):\n    return request['n'] > 42\n"))
    assert result["ruff.magic_values"] == 1


def test_single_module_repository_has_no_import_graph() -> None:
    result = measure({"module.py": "x = 1\n"}, {"module.py": "import os\nx = 1\n"})
    assert result["grimp.imports"] is None
    assert result["new_lines"] == 1


def test_tool_versions_are_recorded() -> None:
    names = {"radon", "complexipy", "lizard", "grimp", "ruff", "mypy", "jscpd"}
    assert set(tool_versions()) == names
    assert all(tool_versions().values())


def test_ignored_ruff_rules_are_not_counted() -> None:
    unsorted = _after("", "import os\n")
    assert measure(BEFORE, unsorted)["ruff.violations"] >= 1
    assert measure(BEFORE, unsorted, ruff_ignore=("I001", "F401"))["ruff.violations"] == 0


def test_nested_function_decisions_count() -> None:
    nested = (
        "\n\ndef outer(request):\n    def pick(x):\n        return 1 if x else 2\n"
        "    return pick(request)\n"
    )
    assert measure(BEFORE, _after(nested))["radon.cc"] == 3


def test_first_and_last_python_file() -> None:
    added = measure({}, {"module.py": "x = 1\n"})
    assert added["radon.sloc"] == 1
    assert added["mypy.errors"] == 0
    assert added["grimp.imports"] is None
    assert measure({"module.py": "x = 1\n"}, {"README.md": ""})["radon.sloc"] == -1


def test_paths_outside_the_snapshot_are_refused() -> None:
    for path in ("../escape.py", "/tmp/escape.py", "a/../../escape.py"):
        with pytest.raises(ValueError, match="relative"):
            measure({}, {path: "x = 1\n"})
