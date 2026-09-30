from __future__ import annotations

from code_metrics import METRICS, measure, tool_versions

VIEWS = """from shop.store import audit, load


def get_view(item_id):
    item = load(item_id)
    if item is None:
        return {"status": 404}
    audit("get", item_id)
    return {"status": 200, "body": item}
"""
BEFORE = {
    "src/shop/__init__.py": "",
    "src/shop/store.py": "DATA = {}\n\n\ndef load(item_id):\n    return DATA.get(item_id)\n\n\n"
    "def audit(action, item_id):\n    print(action, item_id)\n",
    "src/shop/views.py": VIEWS,
    "src/shop/routes.py": "from shop.views import get_view\n\n\n"
    "def get_route(request):\n    return get_view(request['id'])\n",
    "README.md": "not measured\n",
}
DELEGATING = "\n\ndef close_route(request):\n    return get_view(request['id'])\n"
INLINED = """

def close_route(request):
    item_id = request["id"]
    item = load(item_id)
    if item is None:
        return {"status": 404}
    audit("close", item_id)
    for key in ("owner", "status"):
        if key not in item:
            return {"status": 500}
    return {"status": 200, "body": item}
"""


def _after(addition: str, imports: str = "") -> dict[str, str]:
    routes = BEFORE["src/shop/routes.py"]
    return {**BEFORE, "src/shop/routes.py": imports + routes + addition}


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
