"""Typechecking a TypeScript snapshot with its project's own locked toolchain."""

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from assay import cli
from assay.code_metrics import CodeMetricsConfig, analyze, pins, toolchain, tools
from assay.code_metrics.cli_snapshot import snapshot_directory
from assay.code_metrics.errors import (
    ConfigurationError,
    ToolVersionMismatch,
    TypeScriptDependenciesUnavailable,
)
from assay.code_metrics.toolchain import TypeScriptToolchain, resolve_toolchain

# The analyzers' own installed tree is a real locked toolchain: its lockfile
# pins typescript, and npm ci installed exactly that.
LOCAL = TypeScriptToolchain(pins.NODE_TOOLS)
SOURCE = "export const answer: number = 42;\nconst unused = 1;\n"


def _project(**options: object) -> str:
    return json.dumps(
        {"compilerOptions": {"strict": True, "types": [], **options}, "include": ["src/**/*.ts"]}
    )


def test_toolchain_typechecks_with_the_tree_project_and_records_it() -> None:
    snapshot = {"src/a.ts": SOURCE, "tsconfig.json": _project(noUnusedLocals=True)}
    report = analyze(snapshot, config=CodeMetricsConfig(typescript_toolchain=LOCAL))
    assert report.typescript_metrics.type_errors == 1
    lock = hashlib.sha256((pins.NODE_TOOLS / "package-lock.json").read_bytes()).hexdigest()
    assert report.versions.tools["typecheck-typescript"] == pins.TYPESCRIPT.rsplit("@", 1)[1]
    assert report.versions.tools["typecheck-lock"] == f"sha256:{lock}"
    # The synthetic project knows nothing of the tree's options.
    default = analyze(snapshot)
    assert default.typescript_metrics.type_errors == 0
    assert not any(name.startswith("typecheck-") for name in default.versions.tools)


def test_cached_payload_is_keyed_by_the_project_file() -> None:
    tools._CACHE.clear()
    config = CodeMetricsConfig(typescript_toolchain=LOCAL)
    strict = {"src/a.ts": SOURCE, "tsconfig.json": _project(noUnusedLocals=True)}
    lenient = {"src/a.ts": SOURCE, "tsconfig.json": _project(noUnusedLocals=False)}
    assert analyze(strict, config=config).typescript_metrics.type_errors == 1
    assert analyze(lenient, config=config).typescript_metrics.type_errors == 0


def test_toolchain_requires_the_snapshot_project_file() -> None:
    with pytest.raises(ConfigurationError, match="tsconfig.json"):
        analyze({"src/a.ts": SOURCE}, config=CodeMetricsConfig(typescript_toolchain=LOCAL))
    # Without TypeScript there is nothing to typecheck and nothing to record.
    report = analyze({"a.py": "x = 1\n"}, config=CodeMetricsConfig(typescript_toolchain=LOCAL))
    assert report.typescript_metrics.type_errors is None
    assert "typecheck-typescript" not in report.versions.tools


@pytest.mark.parametrize(
    "options", [{"baseUrl": "."}, {"paths": {"@/*": ["./src/*"]}}, {"rootDirs": ["src"]}]
)
def test_project_that_maps_import_paths_is_refused(options: dict[str, object]) -> None:
    snapshot = {"src/a.ts": SOURCE, "tsconfig.json": _project(**options)}
    with pytest.raises(ConfigurationError, match="module graph resolves imports"):
        analyze(snapshot, config=CodeMetricsConfig(typescript_toolchain=LOCAL))


def _tree(tmp_path: Path, installed: str | None, *, tsc: bool = True) -> Path:
    lock = {"packages": {"": {}, "node_modules/typescript": {"version": "5.9.3"}}}
    tmp_path.mkdir()
    (tmp_path / "package-lock.json").write_text(json.dumps(lock))
    if installed is not None:
        package = tmp_path / "node_modules" / "typescript"
        package.mkdir(parents=True)
        (package / "package.json").write_text(json.dumps({"version": installed}))
    if tsc:
        (tmp_path / "node_modules" / ".bin").mkdir(parents=True)
        (tmp_path / "node_modules" / ".bin" / "tsc").touch()
    return tmp_path


def test_resolution_checks_installed_versions_against_the_lock(tmp_path: Path) -> None:
    resolved = resolve_toolchain(TypeScriptToolchain(_tree(tmp_path / "ok", "5.9.3")))
    assert resolved.typescript == "5.9.3"
    with pytest.raises(ToolVersionMismatch) as error:
        resolve_toolchain(TypeScriptToolchain(_tree(tmp_path / "drift", "5.9.2")))
    assert (error.value.tool, error.value.expected, error.value.resolved) == (
        "typescript", "5.9.3", "5.9.2"
    )
    with pytest.raises(TypeScriptDependenciesUnavailable, match="not installed"):
        resolve_toolchain(TypeScriptToolchain(_tree(tmp_path / "missing", None, tsc=False)))
    with pytest.raises(TypeScriptDependenciesUnavailable, match="tsc is missing"):
        resolve_toolchain(TypeScriptToolchain(_tree(tmp_path / "nobin", "5.9.3", tsc=False)))
    with pytest.raises(TypeScriptDependenciesUnavailable, match="unreadable lockfile"):
        resolve_toolchain(TypeScriptToolchain(tmp_path / "absent"))


def test_relative_dependencies_typecheck_from_the_temporary_tree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # What `--config metrics.yaml` with `typescript_dependencies: deps` produces.
    monkeypatch.chdir(pins.NODE_TOOLS.parent)
    relative = TypeScriptToolchain(Path(pins.NODE_TOOLS.name))
    assert Path(resolve_toolchain(relative).tsc).is_absolute()
    snapshot = {"src/a.ts": SOURCE, "tsconfig.json": _project(noUnusedLocals=True)}
    report = analyze(snapshot, config=CodeMetricsConfig(typescript_toolchain=relative))
    assert report.typescript_metrics.type_errors == 1


def test_install_copies_manifests_and_runs_npm_ci_with_dev_dependencies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifests = tmp_path / "manifests"
    manifests.mkdir()
    for name in toolchain.MANIFESTS:
        (manifests / name).write_text(f"{name}\n")
    monkeypatch.setattr(pins.shutil, "which", lambda name: "/usr/bin/npm")
    called: dict[str, object] = {}

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        called["command"], called["cwd"] = command, kwargs["cwd"]
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(pins.subprocess, "run", run)
    monkeypatch.setattr(toolchain, "resolve_toolchain", lambda item: None)
    target = tmp_path / "target"
    assert toolchain.install_typescript_dependencies(manifests, target, offline=True) == target
    assert all((target / name).read_text() == f"{name}\n" for name in toolchain.MANIFESTS)
    assert called == {
        "command": [
            "/usr/bin/npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund",
            "--include=dev", "--offline",
        ],
        "cwd": target,
    }
    # The default target is a per-user cache directory named by the lock digest.
    digest = hashlib.sha256(b"package-lock.json\n").hexdigest()
    assert toolchain.dependencies_directory(manifests).name == digest[:16]


def test_snapshot_directory_keeps_project_files(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.ts").write_text(SOURCE)
    (tmp_path / "tsconfig.json").write_text("{}\n")
    (tmp_path / "package.json").write_text("{}\n")
    files, _ = snapshot_directory(tmp_path)
    assert files == {"src/a.ts": SOURCE, "tsconfig.json": "{}\n"}


def test_cli_config_names_dependencies_relative_to_the_config_file(tmp_path: Path) -> None:
    config = tmp_path / "metrics.yaml"
    config.write_text("typescript_dependencies: deps\n")
    resolved = cli._code_metrics_config(str(config))
    assert resolved.typescript_toolchain == TypeScriptToolchain(tmp_path / "deps")
    config.write_text("typescript_dependencies: 3\n")
    with pytest.raises(ConfigurationError, match="typescript_dependencies"):
        cli._code_metrics_config(str(config))
