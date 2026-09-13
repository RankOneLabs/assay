from __future__ import annotations

import ast
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
from review_fixture import ReviewFixture, materialize_review_fixture

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src" / "assay"
REVIEW = PACKAGE / "review"
CLI = PACKAGE / "cli.py"


@dataclass(frozen=True)
class InstalledWheel:
    fixture: ReviewFixture
    python: Path
    assay: Path
    wheel: Path
    outside: Path


def _run(
    arguments: list[str | Path], *, cwd: Path, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(value) for value in arguments],
        cwd=cwd,
        env=env,
        capture_output=True,
        check=False,
        text=True,
    )


@pytest.fixture(scope="module")
async def installed_wheel(tmp_path_factory: pytest.TempPathFactory) -> InstalledWheel:
    root = tmp_path_factory.mktemp("review-wheel")
    fixture = await materialize_review_fixture(root / "fixture")
    uv = shutil.which("uv")
    assert uv is not None

    clean_bin = root / "build-bin"
    clean_bin.mkdir()
    (clean_bin / "uv").symlink_to(uv)
    build_env = {**os.environ, "PATH": str(clean_bin), "UV_OFFLINE": "1"}
    assert shutil.which("node", path=build_env["PATH"]) is None
    assert shutil.which("bun", path=build_env["PATH"]) is None
    result = _run(
        [clean_bin / "uv", "build", "--wheel", "--out-dir", root / "dist"],
        cwd=ROOT,
        env=build_env,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    wheel = next((root / "dist").glob("assay-*.whl"))

    environment = root / "environment"
    result = _run([uv, "venv", "--python", sys.executable, environment], cwd=root)
    assert result.returncode == 0, result.stdout + result.stderr
    python = environment / "bin" / "python"
    assay = environment / "bin" / "assay"
    install_env = {**os.environ, "UV_OFFLINE": "1"}
    result = _run([uv, "pip", "install", "--python", python, wheel], cwd=root, env=install_env)
    assert result.returncode == 0, result.stdout + result.stderr
    return InstalledWheel(fixture, python, assay, wheel, root / "outside")


def _module_name(path: Path) -> str:
    relative = path.relative_to(ROOT / "src").with_suffix("")
    parts = relative.parts
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _import_targets(node: ast.Import | ast.ImportFrom, module_name: str) -> set[str]:
    if isinstance(node, ast.Import):
        return {alias.name for alias in node.names}

    if node.level == 0:
        base = node.module or ""
    else:
        package = module_name.rsplit(".", 1)[0]
        parts = package.split(".")
        keep = len(parts) - node.level + 1
        prefix = parts[:keep]
        base = ".".join((*prefix, *((node.module or "").split("."))))
        base = base.rstrip(".")

    targets = {base} if base else set()
    targets.update(f"{base}.{alias.name}".lstrip(".") for alias in node.names)
    return targets


def _imports_review(node: ast.Import | ast.ImportFrom, module_name: str) -> bool:
    return any(target == "assay.review" or target.startswith("assay.review.")
               for target in _import_targets(node, module_name))


def test_core_modules_do_not_import_review() -> None:
    violations: list[str] = []
    for path in sorted(PACKAGE.rglob("*.py")):
        if path == CLI or path.is_relative_to(REVIEW):
            continue
        module_name = _module_name(path)
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)) and _imports_review(
                node, module_name
            ):
                violations.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert not violations, "core modules import assay.review: " + ", ".join(violations)


def test_cli_review_imports_are_inside_handler_functions() -> None:
    tree = ast.parse(CLI.read_text(), filename=str(CLI))
    violations: list[int] = []

    class ImportVisitor(ast.NodeVisitor):
        function_depth = 0

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self.function_depth += 1
            self.generic_visit(node)
            self.function_depth -= 1

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self.function_depth += 1
            self.generic_visit(node)
            self.function_depth -= 1

        def visit_Import(self, node: ast.Import) -> None:
            if self.function_depth == 0 and _imports_review(node, "assay.cli"):
                violations.append(node.lineno)

        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
            if self.function_depth == 0 and _imports_review(node, "assay.cli"):
                violations.append(node.lineno)

    ImportVisitor().visit(tree)
    assert not violations, f"module-level assay.review imports in cli.py: {violations}"


def test_review_static_files_are_tracked_and_not_ignored() -> None:
    static_files = sorted(path for path in (REVIEW / "static").rglob("*") if path.is_file())
    assert static_files, "src/assay/review/static must contain committed output"
    for path in static_files:
        relative = path.relative_to(ROOT)
        tracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", str(relative)],
            cwd=ROOT,
            capture_output=True,
            check=False,
            text=True,
        )
        assert tracked.returncode == 0, f"{relative} is not tracked"
        ignored = subprocess.run(
            ["git", "check-ignore", "-q", str(relative)], cwd=ROOT, check=False
        )
        assert ignored.returncode != 0, f"{relative} is ignored"


def _installed_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment["PYTHONNOUSERSITE"] = "1"
    return environment


def test_core_wheel_discovers_and_exports_outside_checkout_without_server_extra(
    installed_wheel: InstalledWheel,
) -> None:
    installed_wheel.outside.mkdir()
    destination = installed_wheel.outside / "review.html"
    program = """
import sys
from pathlib import Path
from assay.review.export import export_review
from assay.review.index import build_index
from assay.store import ObjectStore

store = ObjectStore(sys.argv[1])
root_ref = sys.argv[2]
assert any(run.run_key == root_ref for run in build_index(store).runs)
export_review(store, root_ref, Path(sys.argv[3]))
"""
    result = _run(
        [
            installed_wheel.python,
            "-c",
            program,
            installed_wheel.fixture.bundle.root,
            installed_wheel.fixture.manifest_ref,
            destination,
        ],
        cwd=installed_wheel.outside,
        env=_installed_environment(),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert destination.is_file()
    assert "assay-review-data" in destination.read_text(encoding="utf-8")

    missing_extra = _run(
        [installed_wheel.assay, "review", "serve", installed_wheel.fixture.bundle.root],
        cwd=installed_wheel.outside,
        env=_installed_environment(),
    )
    assert missing_extra.returncode == 1
    assert "install assay[review] to use the review server" in missing_extra.stdout
    assert "missing fastapi" in missing_extra.stdout


def test_review_extra_serves_packaged_assets_outside_checkout(
    installed_wheel: InstalledWheel,
) -> None:
    uv = shutil.which("uv")
    assert uv is not None
    install = _run(
        [
            uv,
            "pip",
            "install",
            "--python",
            installed_wheel.python,
            f"{installed_wheel.wheel}[review]",
        ],
        cwd=installed_wheel.outside,
        env={**_installed_environment(), "UV_OFFLINE": "1"},
    )
    assert install.returncode == 0, install.stdout + install.stderr

    program = """
import asyncio
import sys
import httpx
from assay.review.server import create_app

async def main():
    app = create_app(sys.argv[1])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost"
    ) as client:
        responses = [await client.get(path) for path in ("/", "/app.js", "/app.css")]
    assert all(response.status_code == 200 for response in responses)
    assert "Assay review" in responses[0].text
    assert "Runs and reports" in responses[1].text
    assert ".cell-grid" in responses[2].text

asyncio.run(main())
"""
    served = _run(
        [installed_wheel.python, "-c", program, installed_wheel.fixture.bundle.root],
        cwd=installed_wheel.outside,
        env=_installed_environment(),
    )
    assert served.returncode == 0, served.stdout + served.stderr
