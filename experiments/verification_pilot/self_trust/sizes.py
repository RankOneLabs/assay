"""Recount the four size and framing claims from fixture trees and committed PR data.

This tool never opens a run archive's index or invokes the PR collector. Run
``uv run python -m verification_pilot.self_trust.sizes`` from ``experiments/``.
The Argon 6/4 split comes from each archive's framing_version label in the
publication manifest. Archived per-cell own/teammate condition corroborates
the label but does not derive it.
"""

from __future__ import annotations

import argparse
import difflib
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from verification_pilot.self_trust import fixtures, refactor
from verification_pilot.self_trust.ledger import PUBLICATION_MANIFEST

PR_SIZES = Path(__file__).resolve().parents[1] / "raw" / "self_trust" / "oakridge-pr-sizes.json"


def plain_diff(before: dict[str, str], after: dict[str, str]) -> int:
    total = 0
    for path in before.keys() | after.keys():
        lines = difflib.unified_diff(before.get(path, "").splitlines(keepends=True),
                                     after.get(path, "").splitlines(keepends=True), n=0)
        total += sum(line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
                     for line in lines)
    return total


def git_numstat(before: dict[str, str], after: dict[str, str]) -> int:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        for name, tree in (("before", before), ("after", after)):
            for relative, content in tree.items():
                path = root / name / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
        result = subprocess.run(
            ["git", "diff", "--no-index", "--no-renames", "--numstat",
             str(root / "before"), str(root / "after")],
            capture_output=True, text=True, check=False,
        )
        if result.returncode not in (0, 1):
            raise RuntimeError(result.stderr)
        return sum(int(parts[0]) + int(parts[1]) for line in result.stdout.splitlines()
                   if len(parts := line.split("\t")) >= 2 and parts[0].isdigit()
                   and parts[1].isdigit())


def percentile(rows: list[dict[str, Any]], lines: int) -> float:
    return float(round(100 * sum(row["code_lines"] < lines for row in rows) / len(rows), 1))


def recount(pr_sizes: Path = PR_SIZES,
            manifest_path: Path = PUBLICATION_MANIFEST) -> list[dict[str, Any]]:
    data = json.loads(pr_sizes.read_text(encoding="utf-8"))
    rows = data["rows"]
    cohort = [row for row in rows if row["cohort"]]
    before, after = refactor.start_tree(), refactor.subject_tree(None)
    move = plain_diff(before, after)
    publication = json.loads(manifest_path.read_text(encoding="utf-8"))
    framing = {"earlier": 0, "published": 0}
    for archive, cells in publication["size_and_framing"]["argon_693_sample"].items():
        run = publication["runs"][archive]
        if not set(cells) <= set(run["ran_cells"]):
            raise ValueError(f"framing sample contains a cell that did not run: {archive}")
        framing[run["framing_version"]] += len(cells)
    forge = {}
    for change in (fixtures.FORGE_MOVE, fixtures.FORGE_REWRITE):
        forge[change.name] = plain_diff(change.start_tree(), change.subject_tree(None))
    return [
        {"row": "move_lines", "plain_diff": move,
         "git_numstat": git_numstat(before, after)},
        {"row": "pr_cohort", "all_prs": len(rows), "cohort_prs": len(cohort),
         "full_rewrite_all_percentile": percentile(rows, 2782),
         "full_rewrite_cohort_percentile": percentile(cohort, 2782),
         "move_420_all_percentile": percentile(rows, move),
         "move_420_cohort_percentile": percentile(cohort, move),
         "published_436_all_percentile": percentile(rows, 436),
         "published_436_cohort_percentile": percentile(cohort, 436)},
        {"row": "reconciler_pair", "counting_convention": "moved file = deleted plus added",
         "forge_move_lines": forge["forge-move"],
         "forge_rewrite_lines": forge["forge-rewrite"]},
        {"row": "argon_framing", "earlier": framing["earlier"],
         "published": framing["published"], "total": sum(framing.values())},
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", type=Path, default=Path("/tmp/self-trust-report/sizes.json"))
    args = parser.parse_args()
    rows = recount()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(rows, indent=2))


if __name__ == "__main__":
    main()
