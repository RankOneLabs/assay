"""Standard code metrics for every stored DRY output, compared across arms.

    cd experiments && uv run python -m consistency_pilot.dry_metrics <store-dir> [reference-arm]

Each succeeded single-output cell is measured with ``code_metrics.measure``:
the arm's repository before the change against the same repository with the
submission written into the target file. The submission's imports join the
target's import block, and its function is appended, as a developer would
place them, so the harness's append order is not scored as a lint finding.
Import sorting (ruff I001) is ignored for the same reason: the harness, not the
model, decides where those imports land.
"""

from __future__ import annotations

import ast
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from code_metrics import METRICS, measure, tool_versions

RUFF_IGNORE = ("I001",)


def apply_submission(target: str, source: str) -> str:
    """``target`` with the submission's imports in its import block and its body appended."""
    submission = ast.parse(source)
    lines = source.splitlines()
    body = list(submission.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        body.pop(0)
    imports = []
    while body and isinstance(body[0], ast.Import | ast.ImportFrom):
        statement = body.pop(0)
        imports.extend(lines[statement.lineno - 1 : statement.end_lineno])
    rest = "\n".join(lines[body[0].lineno - 1 :]) if body else ""
    existing = ast.parse(target).body
    anchor = 0
    for node in existing:
        if isinstance(node, ast.Import | ast.ImportFrom):
            anchor = node.end_lineno or anchor
        elif not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)):
            break
    target_lines = target.rstrip("\n").splitlines()
    head, tail = target_lines[:anchor], target_lines[anchor:]
    if imports and not head:
        imports.append("")
    return "\n".join([*head, *imports, *tail, "", "", rest]) + "\n"


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
        output = objects.get(record.get("output_ref", ""))
        realization = objects.get(record.get("input_ref", ""))
        if not isinstance(output, dict) or "source" not in output or not realization:
            continue
        task = realization["task"]
        before = realization["repository"]
        coordinate = record["coordinate"]
        try:
            changed = apply_submission(before[task["target_path"]], output["source"])
        except SyntaxError:
            continue
        cells.append(
            {
                "subject": coordinate["subject_id"],
                "family": task["family"],
                "arm": coordinate["arm_id"],
                "repeat": coordinate["worker_repeat"],
                **measure(
                    before,
                    {**before, task["target_path"]: changed},
                    ruff_ignore=RUFF_IGNORE,
                ),
            }
        )
    return cells


def _sign_test(higher: int, lower: int) -> float | None:
    trials = higher + lower
    if trials == 0:
        return None
    tail = sum(math.comb(trials, k) for k in range(min(higher, lower) + 1)) / 2.0**trials
    return min(1.0, 2 * tail)


def _mean(cells: list[dict[str, Any]], metric: str) -> float | None:
    values: list[float] = [cell[metric] for cell in cells if cell[metric] is not None]
    return statistics.fmean(values) if values else None


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
            mean = _mean(arm_cells, metric)
            row[metric] = None if mean is None else round(mean, 2)
        if arm != reference:
            for metric in METRICS:
                higher = lower = 0
                for (cell_arm, subject), group in by_subject.items():
                    base = by_subject.get((reference, subject))
                    if cell_arm != arm or not base:
                        continue
                    ours, theirs = _mean(group, metric), _mean(base, metric)
                    if ours is None or theirs is None:
                        continue
                    higher += ours > theirs
                    lower += ours < theirs
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
    print(
        json.dumps(
            {
                "store": root.name,
                "reference": reference,
                "tools": tool_versions(),
                "ruff_ignore": RUFF_IGNORE,
                **summarize(cells, reference),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
