from __future__ import annotations

import ast
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src" / "assay"
REVIEW = PACKAGE / "review"
CLI = PACKAGE / "cli.py"


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

        visit_AsyncFunctionDef = visit_FunctionDef

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
