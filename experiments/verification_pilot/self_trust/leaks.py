"""Scan every archived session for text that could point the agent at the answer.

Searches everything the agent was shown (system prompt, user turns, tool
results) for evaluator-side vocabulary and identifiers: the words the study
uses for the planted defect, subject and arm ids, fixture codenames, the
hidden test's path, and the ownership labels. A hit is not proof of a leak;
each one is listed with its context for a person to judge.

Run ``uv run python -m verification_pilot.self_trust.leaks`` from ``experiments/``.
Writes ``/tmp/self-trust-report/leak-scan.csv`` by default.
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

from verification_pilot.self_trust.ladder import RUNGS

AUDIT = Path("/tmp/self-trust-report")
RUNS = Path(__file__).resolve().parents[1] / "raw" / "self_trust" / "runs"
TERMS = [
    r"remnant",
    r"omission",
    r"omitted",
    r"hidden[ _-]?test",
    r"held[ _-]?out",
    r"planted",
    r"own_[abc]",
    r"group_[abc]",
    r"self[_-]?trust",
    r"st-native",
    r"st-quoted",
    r"rewrite0",
    r"resume146",
    r"forge-(?:move|rewrite)",
    r"oracle",
    r"ground[ _-]?truth",
]


def hidden_paths() -> set[str]:
    return {rung.hidden_test for rung in RUNGS.values()}


def main() -> None:
    patterns = [re.compile(t, re.I) for t in TERMS]
    patterns += [re.compile(re.escape(p)) for p in sorted(hidden_paths())]
    hits = []
    sessions = 0
    for index_path in sorted(RUNS.glob("*/index.json")):
        run = index_path.parent
        for cell_id, entry in sorted(json.loads(index_path.read_text(encoding="utf-8")).items()):
            sessions += 1
            trajectory = json.loads(
                (run / "traces" / entry["trajectory"]).read_text(encoding="utf-8")
            )
            for position, message in enumerate(trajectory["messages"]):
                if message["role"] == "assistant":
                    continue
                text = message.get("content") or ""
                if not isinstance(text, str):
                    text = json.dumps(text)
                for pattern in patterns:
                    for match in pattern.finditer(text):
                        start = max(0, match.start() - 80)
                        hits.append(
                            {
                                "run_id": run.name,
                                "cell_id": cell_id,
                                "message": position,
                                "role": message["role"],
                                "term": pattern.pattern,
                                "context": text[start : match.end() + 80].replace("\n", " "),
                            }
                        )
    out = AUDIT / "ledger" / "leak-scan.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["run_id", "cell_id", "message", "role", "term", "context"]
        )
        writer.writeheader()
        writer.writerows(hits)
    print(f"{sessions} sessions scanned, {len(hits)} hits -> {out}")


if __name__ == "__main__":
    main()
