"""Hard failures are typed and identify their input."""

import subprocess

import pytest

from assay.code_metrics import analyze, api, graph, tools
from assay.code_metrics.api import CodeMetricsConfig
from assay.code_metrics.components import ComponentConfig
from assay.code_metrics.errors import (
    AmbiguousComponentConfig,
    AnalyzerFailed,
    EmptyComponentPattern,
    MalformedComponentConfig,
    ReservedComponentName,
    SnapshotPathError,
    ToolUnavailable,
    ToolVersionMismatch,
)
from assay.code_metrics.pins import PINS

PACKAGE = {"src/pkg/__init__.py": "", "src/pkg/a.py": "x = 1\n"}


@pytest.fixture(autouse=True)
def stub_clones(monkeypatch: pytest.MonkeyPatch) -> None:
    tools._CACHE.clear()
    monkeypatch.setattr(
        tools,
        "_jscpd",
        lambda *args: {"jscpd.clones": 0, "jscpd.duplicated_lines": 0, "cloned_lines": {}},
    )


def test_preflight_unavailable_before_analyzers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api.shutil, "which", lambda name: None)
    monkeypatch.setattr(
        graph, "build_module_graph", lambda *args, **kwargs: pytest.fail("graph ran")
    )
    with pytest.raises(ToolUnavailable, match=r"jscpd@5\.4\.0.*npx"):
        analyze(PACKAGE)


def test_invalid_path_and_component_configurations() -> None:
    with pytest.raises(SnapshotPathError, match=r"relative.*escape\.py") as path_error:
        analyze({"../escape.py": ""})
    assert str(path_error.value).count("analyze snapshot path") == 1
    with pytest.raises(ReservedComponentName, match="unassigned"):
        analyze(
            PACKAGE,
            config=CodeMetricsConfig(
                components=(ComponentConfig("unassigned", ("src/pkg/a.py",)),)
            ),
        )
    with pytest.raises(MalformedComponentConfig, match="bad name"):
        analyze(
            PACKAGE,
            config=CodeMetricsConfig(components=(ComponentConfig("bad name", ("src/pkg/a.py",)),)),
        )
    with pytest.raises(EmptyComponentPattern, match="missing.py"):
        analyze(
            PACKAGE,
            config=CodeMetricsConfig(
                components=(ComponentConfig("alpha", ("src/pkg/missing.py",)),)
            ),
        )
    with pytest.raises(AmbiguousComponentConfig, match="pkg.a"):
        analyze(
            PACKAGE,
            config=CodeMetricsConfig(
                components=(
                    ComponentConfig("alpha", ("src/pkg/a.py",)),
                    ComponentConfig("beta", ("src/pkg/*.py",)),
                )
            ),
        )


def test_version_mismatch_names_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("assay.code_metrics.pins.version", lambda name: "0.0.0")
    with pytest.raises(ToolVersionMismatch, match=f"radon.*{PINS['radon']}"):
        analyze(PACKAGE)


def test_jscpd_fetch_failure_is_typed(monkeypatch: pytest.MonkeyPatch) -> None:
    from assay.code_metrics import tools

    def fail(*args: object) -> object:
        raise subprocess.CalledProcessError(1, "npx")

    monkeypatch.setattr(tools, "_jscpd", fail)
    with pytest.raises(ToolUnavailable, match=r"jscpd@5\.4\.0"):
        analyze(PACKAGE)


def test_mypy_abnormal_exit_is_typed(monkeypatch: pytest.MonkeyPatch) -> None:
    original_run = subprocess.run

    def fail(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        command = args[0]
        if isinstance(command, list) and "mypy" in command:
            return subprocess.CompletedProcess(
                args=command, returncode=2, stdout="", stderr="fatal"
            )
        return original_run(*args, **kwargs)

    monkeypatch.setattr(tools.subprocess, "run", fail)
    with pytest.raises(AnalyzerFailed) as caught:
        analyze(PACKAGE)
    assert "mypy" in str(caught.value)
    assert "src/pkg/a.py" in str(caught.value)
