"""Hard failures are typed and identify their input."""

import subprocess

import pytest
from code_metrics_fixtures import stub_jscpd

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
    SnapshotSyntaxError,
    ToolUnavailable,
    ToolVersionMismatch,
)
from assay.code_metrics.pins import PINS

PACKAGE = {"src/pkg/__init__.py": "", "src/pkg/a.py": "x = 1\n"}
REAL_JSCPD = tools._jscpd


@pytest.fixture(autouse=True)
def stub_clones(monkeypatch: pytest.MonkeyPatch) -> None:
    tools._CACHE.clear()
    stub_jscpd(monkeypatch)


def test_preflight_unavailable_before_analyzers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api.shutil, "which", lambda name: None)
    monkeypatch.setattr(
        graph, "extract_module_graph", lambda *args, **kwargs: pytest.fail("graph ran")
    )
    with pytest.raises(ToolUnavailable, match=r"jscpd@5\.4\.0.*npx"):
        analyze(PACKAGE)


def test_invalid_path_and_component_configurations() -> None:
    with pytest.raises(SnapshotPathError, match=r"relative.*escape\.py") as path_error:
        analyze({"../escape.py": ""})
    assert str(path_error.value).count("analyze snapshot path") == 1
    for snapshot, offending in (
        ({"bad\n.py": ""}, "bad"),
        ({f"{'a' * 256}.py": ""}, "a" * 256),
        ({"pkg.py": "", "pkg.py/a.py": ""}, "pkg.py/a.py"),
    ):
        with pytest.raises(SnapshotPathError) as caught:
            analyze(snapshot)
        assert offending in str(caught.value)
    assert analyze({}).architecture.graph.modules == ()
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
    with pytest.raises(MalformedComponentConfig, match="42"):
        analyze(
            PACKAGE,
            config=CodeMetricsConfig(
                components=(ComponentConfig(42, ("src/pkg/a.py",)),)  # type: ignore[arg-type]
            ),
        )
    with pytest.raises(MalformedComponentConfig, match="42"):
        analyze(
            PACKAGE,
            config=CodeMetricsConfig(
                components=(ComponentConfig("alpha", (42,)),)  # type: ignore[arg-type]
            ),
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


def _fail_command(
    monkeypatch: pytest.MonkeyPatch, marker: str, failure: subprocess.CompletedProcess[str] | None
) -> None:
    original_run = subprocess.run

    def run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        command = args[0]
        if isinstance(command, list) and marker in command:
            if failure is None:
                raise subprocess.CalledProcessError(1, command, stderr="npm fetch failed")
            return failure
        return original_run(*args, **kwargs)  # type: ignore[call-overload,no-any-return]

    monkeypatch.setattr(tools.subprocess, "run", run)


def test_jscpd_fetch_failure_is_typed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tools, "_jscpd", REAL_JSCPD)
    _fail_command(monkeypatch, "npx", None)
    with pytest.raises(ToolUnavailable, match=r"jscpd@5\.4\.0: npm fetch failed"):
        analyze(PACKAGE)


def test_jscpd_analysis_failure_is_not_reported_as_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tools, "_jscpd", REAL_JSCPD)
    original_run = subprocess.run

    def run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        command = args[0]
        if isinstance(command, list) and "npx" in command:
            returncode = 0 if "--version" in command else 1
            return subprocess.CompletedProcess(command, returncode, "", "jscpd crashed")
        return original_run(*args, **kwargs)  # type: ignore[call-overload,no-any-return]

    monkeypatch.setattr(tools.subprocess, "run", run)
    with pytest.raises(AnalyzerFailed, match="jscpd failed: jscpd crashed"):
        analyze(PACKAGE)


def test_ruff_failure_is_not_reported_as_jscpd(monkeypatch: pytest.MonkeyPatch) -> None:
    failure = subprocess.CompletedProcess(args=[], returncode=2, stdout="", stderr="ruff crashed")
    _fail_command(monkeypatch, "ruff", failure)
    with pytest.raises(AnalyzerFailed, match="ruff failed: ruff crashed"):
        analyze(PACKAGE)


def test_unparsable_source_names_the_snapshot_path() -> None:
    expected = r"parse snapshot src/pkg/bad\.py, line 1"
    with pytest.raises(SnapshotSyntaxError, match=expected) as caught:
        analyze({**PACKAGE, "src/pkg/bad.py": "def f(:\n"})
    assert "/tmp" not in str(caught.value)


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
