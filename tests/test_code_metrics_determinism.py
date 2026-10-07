"""Stable serialization and one analyzer invocation per snapshot."""

import os
import subprocess
import sys
from collections import Counter

import pytest

from assay.code_metrics import api, graph, tools

SNAPSHOT = {
    "src/pkg/__init__.py": "",
    "src/pkg/a.py": "import pkg.b\n",
    "src/pkg/b.py": "x = 1\n",
}


@pytest.fixture(autouse=True)
def stub_clones(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        tools,
        "_jscpd",
        lambda *args: {"jscpd.clones": 0, "jscpd.duplicated_lines": 0, "cloned_lines": {}},
    )


def test_one_graph_and_each_tool_per_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: Counter[str] = Counter()

    def wrap(owner: object, name: str) -> None:
        original = getattr(owner, name)

        def counted(*args: object, **kwargs: object) -> object:
            calls[name] += 1
            return original(*args, **kwargs)

        monkeypatch.setattr(owner, name, counted)

    for owner, name in (
        (graph.grimp, "build_graph"),
        (tools, "_radon"),
        (tools, "_ruff"),
        (tools, "_mypy"),
        (tools, "_jscpd"),
        (tools, "_functions"),
    ):
        wrap(owner, name)
    first = api.analyze(SNAPSHOT).model_dump_json()
    second = api.analyze(SNAPSHOT).model_dump_json()
    assert first == second
    assert calls == Counter(
        {name: 2 for name in ("build_graph", "_radon", "_ruff", "_mypy", "_jscpd", "_functions")}
    )


def test_hash_seed_does_not_change_report() -> None:
    code = (
        "from assay.code_metrics import analyze, tools; "
        "tools._jscpd = lambda *args: {'jscpd.clones': 0, "
        "'jscpd.duplicated_lines': 0, 'cloned_lines': {}}; "
        f"print(analyze({SNAPSHOT!r}).model_dump_json())"
    )
    outputs = []
    for seed in ("1", "73"):
        completed = subprocess.run(
            [sys.executable, "-c", code],
            env={**os.environ, "PYTHONHASHSEED": seed},
            capture_output=True,
            text=True,
            check=True,
        )
        outputs.append(completed.stdout)
    assert outputs[0] == outputs[1]
