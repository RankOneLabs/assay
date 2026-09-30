from __future__ import annotations

from code_metrics import METRICS
from consistency_pilot.dry_metrics import apply_submission, summarize

TARGET = '''"""Routes."""

from shop.views import get_view


def get_route(request):
    return get_view(request["id"])
'''


def test_submission_imports_join_the_import_block() -> None:
    changed = apply_submission(
        TARGET,
        "from shop.views import close_view\n\n\ndef implement(request):\n"
        '    return close_view(request["id"])\n',
    )
    assert changed == (
        '"""Routes."""\n\nfrom shop.views import get_view\nfrom shop.views import close_view\n'
        '\n\ndef get_route(request):\n    return get_view(request["id"])\n\n\n'
        'def implement(request):\n    return close_view(request["id"])\n'
    )


def test_submission_without_imports_is_appended() -> None:
    changed = apply_submission("x = 1\n", "def implement(value):\n    return value\n")
    assert changed == "x = 1\n\n\ndef implement(value):\n    return value\n"


def test_imports_go_first_in_a_file_without_any() -> None:
    changed = apply_submission("x = 1\n", "import os\n\n\ndef implement():\n    return os.sep\n")
    assert changed.startswith("import os\n\nx = 1\n")


def test_summary_compares_each_arm_with_the_reference() -> None:
    cells = [
        {"subject": s, "arm": arm, "repeat": 0, **dict.fromkeys(METRICS, value)}
        for s in ("a", "b", "c")
        for arm, value in (("clean", 1), ("messy", 5))
    ]
    summary = summarize(cells, "clean")
    assert summary["messy"]["radon.sloc"] == 5
    assert summary["messy"]["radon.sloc_vs_ref"] == {"higher": 3, "lower": 0, "p": 0.25}


def test_summary_skips_metrics_a_repository_cannot_have() -> None:
    cells = [
        {"subject": "a", "arm": arm, "repeat": 0, **dict.fromkeys(METRICS, 1)}
        | {"grimp.imports": None}
        for arm in ("clean", "messy")
    ]
    summary = summarize(cells, "clean")
    assert summary["messy"]["grimp.imports"] is None
    assert summary["messy"]["grimp.imports_vs_ref"] == {"higher": 0, "lower": 0, "p": None}
