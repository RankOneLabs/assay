"""Size every merged Oakridge PR by code lines, to place the ladder's rungs.

Raw line counts overstate how much code a PR changes: Oakridge's largest PRs
are mostly docs, generated fixtures and lockfiles. A file counts as code when
it is source (``.ts``, ``.tsx``, ``.js``, ``.py``, ``.rs``, ``.go``, ``.sql``,
``.sh``) and not under a docs, examples or fixtures path. The rungs' own
diffs are all code and tests.

Run ``uv run python -m verification_pilot.self_trust.pr_sizes`` from
``experiments/`` with ``gh`` authenticated. The result is written to
``raw/self_trust/oakridge-pr-sizes.json``.
"""

from __future__ import annotations

import json
import re
import statistics
import subprocess
from pathlib import Path
from typing import Any

REPO = "RankOneLabs/oakridge"
RESULT = Path(__file__).resolve().parents[1] / "raw" / "self_trust" / "oakridge-pr-sizes.json"
RUNGS = {"S": 436, "L1": 1097, "L2": 2137, "L3": 2782}
_CODE = re.compile(r"\.(ts|tsx|js|jsx|mjs|cjs|py|rs|go|sql|sh)$")
_NOT_CODE = re.compile(r"(^|/)(docs?|examples|fixtures|__snapshots__)(/|$)")


def _gh(*args: str) -> str:
    return subprocess.run(["gh", *args], capture_output=True, text=True, check=True).stdout


def pr_sizes() -> list[dict[str, Any]]:
    prs = json.loads(_gh("pr", "list", "--repo", REPO, "--state", "merged", "--limit", "2000",
                         "--json", "number,headRefName,additions,deletions"))
    rows = []
    for pr in prs:
        listing = _gh("api", "--paginate", f"repos/{REPO}/pulls/{pr['number']}/files",
                      "--jq", ".[] | [.filename, .additions, .deletions] | @tsv")
        code = other = 0
        for line in listing.splitlines():
            name, added, removed = line.split("\t")
            lines = int(added) + int(removed)
            if _CODE.search(name) and not _NOT_CODE.search(name):
                code += lines
            else:
                other += lines
        rows.append({"number": pr["number"], "cohort": pr["headRefName"].startswith("cohort/"),
                     "code_lines": code, "other_lines": other,
                     "total_lines": pr["additions"] + pr["deletions"]})
    return rows


def summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def quantile(values: list[int], q: float) -> int:
        return sorted(values)[int(q * (len(values) - 1))]

    result = {}
    for label, group in (("cohort", [r for r in rows if r["cohort"]]), ("all", rows)):
        code = [r["code_lines"] for r in group]
        result[label] = {
            "prs": len(group), "code_median": statistics.median(code),
            "code_p75": quantile(code, 0.75), "code_p90": quantile(code, 0.9),
            "rung_percentiles": {name: round(sum(x < n for x in code) / len(code), 3)
                                 for name, n in RUNGS.items()},
        }
    return result


def main() -> None:
    rows = pr_sizes()
    result = {"repo": REPO, "rows": rows, "summary": summary(rows)}
    RESULT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result["summary"], indent=2))


if __name__ == "__main__":
    main()
