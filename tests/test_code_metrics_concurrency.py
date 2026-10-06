"""Parallel measurements keep cache results and import paths isolated."""

import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Lock
from types import SimpleNamespace

import pytest

from assay.code_metrics import tools
from assay.code_metrics.models import _Config


def test_parallel_snapshots_survive_cache_eviction(monkeypatch: pytest.MonkeyPatch) -> None:
    workers = 12
    barrier = Barrier(workers)

    def radon(files: dict[str, str]) -> dict[str, str]:
        barrier.wait(timeout=10)
        return {"source": files["module.py"]}

    monkeypatch.setattr(tools, "_radon", radon)
    monkeypatch.setattr(tools, "code_complexity", lambda text: SimpleNamespace(complexity=0))
    monkeypatch.setattr(tools, "_imports", lambda root: None)
    monkeypatch.setattr(tools, "_ruff", lambda root, ignore: {})
    monkeypatch.setattr(tools, "_mypy", lambda root: 0)
    monkeypatch.setattr(tools, "_jscpd", lambda root, config: {})
    monkeypatch.setattr(tools, "_functions", lambda root: [])

    def snapshot(number: int) -> str:
        return tools._snapshot({"module.py": f"x = {number}\n"}, _Config(5, 50, ()))['source']

    tools._CACHE.clear()
    try:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            results = list(executor.map(snapshot, range(workers * 4)))
        assert results == [f"x = {number}\n" for number in range(workers * 4)]
        assert len(tools._CACHE) == 8
    finally:
        tools._CACHE.clear()


def test_parallel_import_graphs_use_their_own_snapshot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    roots = [tmp_path / "first", tmp_path / "second"]
    for index, root in enumerate(roots):
        package = root / "shop"
        package.mkdir(parents=True)
        (package / "__init__.py").write_text("")
        (package / "store.py").write_text("import os\n" * index)
    build_graph = tools.grimp.build_graph
    active = 0
    maximum_active = 0
    counter_lock = Lock()

    def delayed_build_graph(*args: str, **kwargs: object) -> tools.grimp.ImportGraph:
        nonlocal active, maximum_active
        base = sys.path[0]
        with counter_lock:
            active += 1
            maximum_active = max(maximum_active, active)
        try:
            # Let other workers attempt graph construction before resolving packages.
            time.sleep(0.01)
            assert sys.path[0] == base
            return build_graph(*args, **kwargs)
        finally:
            with counter_lock:
                active -= 1

    monkeypatch.setattr(tools.grimp, "build_graph", delayed_build_graph)
    original_path = sys.path.copy()
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(tools._imports, roots * 8))
    assert results == [0, 1] * 8
    assert maximum_active == 1
    assert sys.path == original_path


def test_import_graph_failure_restores_path_and_releases_lock(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    package = tmp_path / "shop"
    package.mkdir()
    (package / "__init__.py").write_text("")
    build_graph = tools.grimp.build_graph

    def fail(*args: str, **kwargs: object) -> None:
        raise RuntimeError("graph failed")

    original_path = sys.path.copy()
    monkeypatch.setattr(tools.grimp, "build_graph", fail)
    with pytest.raises(RuntimeError, match="graph failed"):
        tools._imports(tmp_path)
    assert sys.path == original_path
    monkeypatch.setattr(tools.grimp, "build_graph", build_graph)
    assert tools._imports(tmp_path) == 0
