"""Parallel measurements keep cache results and import paths isolated."""

import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Lock
from types import SimpleNamespace

import pytest

from assay.code_metrics import analyze, tools
from assay.code_metrics.graph import build_module_graph


def test_parallel_snapshots_survive_cache_eviction(monkeypatch: pytest.MonkeyPatch) -> None:
    workers = 12
    barrier = Barrier(workers)

    def radon(files: dict[str, str]) -> dict[str, object]:
        barrier.wait(timeout=10)
        number = int(files["module.py"].split("=")[1])
        return {
            "radon.sloc": number,
            "radon.lloc": 1,
            "radon.cc": 0,
            "radon.halstead_volume": 0.0,
            "mi": {"module.py": 100.0},
        }

    monkeypatch.setattr(tools, "_radon", radon)
    monkeypatch.setattr(tools, "code_complexity", lambda text: SimpleNamespace(complexity=0))
    monkeypatch.setattr(tools, "_imports", lambda root, graph=None, direct_import_count=None: None)
    monkeypatch.setattr(
        tools, "_ruff", lambda root, ignore: {"ruff.violations": 0, "ruff.magic_values": 0}
    )
    monkeypatch.setattr(tools, "_mypy", lambda root: 0)
    monkeypatch.setattr(
        tools,
        "_jscpd",
        lambda root, config: {"jscpd.clones": 0, "jscpd.duplicated_lines": 0, "cloned_lines": {}},
    )
    monkeypatch.setattr(tools, "_functions", lambda root: [])

    def snapshot(number: int) -> int:
        return analyze({"module.py": f"x = {number}\n"}).existing_metrics.radon_sloc

    tools._CACHE.clear()
    try:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            results = list(executor.map(snapshot, range(workers * 4)))
        assert results == list(range(workers * 4))
        assert len(tools._CACHE) == 8
    finally:
        tools._CACHE.clear()


def test_parallel_import_graphs_use_their_own_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
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

    def extract(index: int) -> int:
        root = roots[index % 2]
        if index % 4 < 2:
            return tools._imports(root)  # type: ignore[return-value]
        snapshot = {
            path.relative_to(root).as_posix(): path.read_text() for path in root.rglob("*.py")
        }
        graph, _ = build_module_graph(snapshot)
        return len(graph.edges) + len(graph.external_dependencies)

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(extract, range(32)))
    assert results == [0, 1] * 16
    assert maximum_active == 1
    assert sys.path == original_path


def test_import_graph_failure_restores_path_and_releases_lock(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
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
