"""Objective code metrics for generated ``implement`` functions in a result store.

    cd experiments && uv run python -m consistency_pilot.code_metrics <store-dir> [reference-arm]

Every succeeded single-output cell is measured against the target file it was
written into. Metrics are computed from the source alone (plus ruff), never by
running it, so they cost nothing and can be recomputed on any stored run.
"""

from __future__ import annotations

import ast
import io
import json
import math
import statistics
import subprocess
import sys
import tempfile
import tokenize
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

METRICS = (
    "lines",
    "statements",
    "complexity",
    "nesting",
    "fan_out",
    "imports",
    "magic_numbers",
    "clone_similarity",
    "new_lint",
)
# Rules chosen for objective, style-neutral findings: errors, pyflakes
# (undefined and unused names), bugbear and simplifications.
LINT_RULES = "E9,F,B,SIM"
_BRANCHES = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.IfExp, ast.ExceptHandler, ast.match_case)
_BLOCKS = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith, ast.Try, ast.Match)


def _implement(tree: ast.Module) -> ast.FunctionDef:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "implement":
            return node
    raise ValueError("no implement function")


def _complexity(function: ast.FunctionDef) -> int:
    score = 1
    for node in ast.walk(function):
        if isinstance(node, _BRANCHES):
            score += 1
        elif isinstance(node, ast.BoolOp):
            score += len(node.values) - 1
        elif isinstance(node, ast.comprehension):
            score += len(node.ifs)
    return score


def _nesting(node: ast.AST, depth: int = 0) -> int:
    deepest = depth
    for child in ast.iter_child_nodes(node):
        inner = depth + 1 if isinstance(child, _BLOCKS) else depth
        deepest = max(deepest, _nesting(child, inner))
    return deepest


def _callee(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _tokens(source: str) -> list[str]:
    skipped = {tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT}
    try:
        return [
            token.string
            for token in tokenize.generate_tokens(io.StringIO(source).readline)
            if token.type not in skipped and token.string
        ]
    except (tokenize.TokenError, SyntaxError):
        return []


def _body_source(source: str, function: ast.FunctionDef) -> str:
    lines = source.splitlines()
    first = function.body[0].lineno - 1
    return "\n".join(lines[first : function.end_lineno])


def _clone_similarity(source: str, function: ast.FunctionDef, target_file: str) -> float:
    """Highest token similarity between the new body and any existing function body."""
    new = _tokens(_body_source(source, function))
    best = 0.0
    try:
        existing = ast.parse(target_file)
    except SyntaxError:
        return best
    for node in existing.body:
        if isinstance(node, ast.FunctionDef):
            other = _tokens(_body_source(target_file, node))
            if new and other:
                best = max(best, SequenceMatcher(None, new, other, autojunk=False).ratio())
    return round(best, 3)


def _lint_count(text: str) -> int:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "target.py"
        path.write_text(text)
        completed = subprocess.run(
            [
                "ruff",
                "check",
                "--isolated",
                "--select",
                LINT_RULES,
                "--output-format",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    return len(json.loads(completed.stdout or "[]"))


def function_metrics(source: str, target_file: str) -> dict[str, float]:
    """Metrics for one submission appended to ``target_file``."""
    tree = ast.parse(source)
    function = _implement(tree)
    lines = [
        line
        for line in source.splitlines()[function.lineno - 1 : function.end_lineno]
        if line.strip() and not line.strip().startswith("#")
    ]
    imported = sum(
        len(node.names) for node in ast.walk(tree) if isinstance(node, ast.Import | ast.ImportFrom)
    )
    magic = sum(
        1
        for node in ast.walk(function)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, int | float)
        and not isinstance(node.value, bool)
        and node.value not in (0, 1)
    )
    callees = {
        name
        for node in ast.walk(function)
        if isinstance(node, ast.Call) and (name := _callee(node.func)) is not None
    }
    combined = target_file.rstrip("\n") + "\n\n\n" + source
    return {
        "lines": len(lines),
        "statements": sum(isinstance(node, ast.stmt) for node in ast.walk(function)) - 1,
        "complexity": _complexity(function),
        "nesting": _nesting(function),
        "fan_out": len(callees),
        "imports": imported,
        "magic_numbers": magic,
        "clone_similarity": _clone_similarity(source, function, target_file),
        "new_lint": _lint_count(combined) - _lint_count(target_file),
    }


def _objects(root: Path) -> dict[str, Any]:
    objects: dict[str, Any] = {}
    for path in root.rglob("sha256/*"):
        try:
            objects["sha256:" + path.name] = json.loads(path.read_bytes())
        except (ValueError, UnicodeDecodeError):
            continue
    return objects


def store_cells(root: Path) -> list[dict[str, Any]]:
    """Measured cells: subject, arm, repeat and metrics for every single-source output."""
    objects = _objects(root)
    cells = []
    for record in objects.values():
        if not (
            isinstance(record, dict)
            and record.get("status") == "succeeded"
            and "coordinate" in record
            and "evaluator_id" not in record["coordinate"]
            and "worker_repeat" in record["coordinate"]
        ):
            continue
        output = objects.get(record.get("output_ref"))
        realization = objects.get(record.get("input_ref"))
        if not isinstance(output, dict) or "source" not in output or not realization:
            continue
        task = realization["task"]
        target_file = realization["repository"][task["target_path"]]
        coordinate = record["coordinate"]
        try:
            metrics = function_metrics(output["source"], target_file)
        except (SyntaxError, ValueError):
            continue
        cells.append(
            {
                "subject": coordinate["subject_id"],
                "family": task["family"],
                "arm": coordinate["arm_id"],
                "repeat": coordinate["worker_repeat"],
                **metrics,
            }
        )
    return cells


def _sign_test(higher: int, lower: int) -> float | None:
    trials = higher + lower
    if trials == 0:
        return None
    tail = sum(math.comb(trials, k) for k in range(min(higher, lower) + 1)) / 2**trials
    return min(1.0, 2 * tail)


def summarize(cells: list[dict[str, Any]], reference: str) -> dict[str, Any]:
    """Per-arm means, and per-subject paired comparisons against ``reference``."""
    by_subject: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for cell in cells:
        by_subject[(cell["arm"], cell["subject"])].append(cell)
    arms = sorted({cell["arm"] for cell in cells})
    summary: dict[str, Any] = {}
    for arm in arms:
        arm_cells = [cell for cell in cells if cell["arm"] == arm]
        row: dict[str, Any] = {"cells": len(arm_cells)}
        for metric in METRICS:
            row[metric] = round(statistics.fmean(cell[metric] for cell in arm_cells), 2)
        if arm != reference:
            for metric in METRICS:
                higher = lower = 0
                for (cell_arm, subject), group in by_subject.items():
                    base = by_subject.get((reference, subject))
                    if cell_arm != arm or not base:
                        continue
                    delta = statistics.fmean(c[metric] for c in group) - statistics.fmean(
                        c[metric] for c in base
                    )
                    higher += delta > 0
                    lower += delta < 0
                row[f"{metric}_vs_ref"] = {
                    "higher": higher,
                    "lower": lower,
                    "p": _sign_test(higher, lower),
                }
        summary[arm] = row
    return summary


def main(argv: list[str]) -> int:
    root = Path(argv[0])
    cells = store_cells(root)
    arms = sorted({cell["arm"] for cell in cells})
    reference = (
        argv[1] if len(argv) > 1 else ("inconsistent" if "inconsistent" in arms else arms[0])
    )
    print(json.dumps({"store": root.name, "reference": reference, **summarize(cells, reference)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
