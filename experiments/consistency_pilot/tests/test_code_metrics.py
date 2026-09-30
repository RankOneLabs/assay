from __future__ import annotations

from consistency_pilot.code_metrics import function_metrics, summarize

TARGET = """from shop.views import get_view


def get_route(request):
    item = load(request["id"])
    if item is None:
        return {"status": 404}
    return {"status": 200, "body": item}
"""


def test_delegating_route_is_small_and_unique() -> None:
    metrics = function_metrics(
        "from shop.views import close_view\n\n\ndef implement(request):\n"
        '    return close_view(request["id"])\n',
        TARGET,
    )
    assert metrics["lines"] == 2
    assert metrics["statements"] == 1
    assert metrics["complexity"] == 1
    assert metrics["nesting"] == 0
    assert metrics["fan_out"] == 1
    assert metrics["imports"] == 1
    assert metrics["magic_numbers"] == 0
    assert metrics["new_lint"] == 0


def test_inlined_route_scores_as_larger_copied_and_branchier() -> None:
    metrics = function_metrics(
        "def implement(request):\n"
        '    item = load(request["id"])\n'
        "    if item is None:\n"
        '        return {"status": 404}\n'
        '    return {"status": 200, "body": item, "limit": 50}\n',
        TARGET,
    )
    assert metrics["statements"] == 4
    assert metrics["complexity"] == 2
    assert metrics["nesting"] == 1
    assert metrics["magic_numbers"] == 3
    assert metrics["clone_similarity"] > 0.8


def test_undefined_names_count_as_new_lint() -> None:
    metrics = function_metrics(
        "def implement(value):\n    return missing_helper(value)\n", "x = 1\n"
    )
    assert metrics["new_lint"] == 1


def test_summary_compares_each_arm_with_the_reference() -> None:
    cells = [
        {
            "subject": s,
            "arm": arm,
            "repeat": 0,
            **dict.fromkeys(
                (
                    "lines",
                    "statements",
                    "complexity",
                    "nesting",
                    "fan_out",
                    "imports",
                    "magic_numbers",
                    "clone_similarity",
                    "new_lint",
                ),
                value,
            ),
        }
        for s in ("a", "b", "c")
        for arm, value in (("clean", 1), ("messy", 5))
    ]
    summary = summarize(cells, "clean")
    assert summary["messy"]["lines"] == 5
    assert summary["messy"]["lines_vs_ref"] == {"higher": 3, "lower": 0, "p": 0.25}
