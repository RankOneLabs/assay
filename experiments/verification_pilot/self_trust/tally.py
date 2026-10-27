"""Summarize self-trust run archives: one row per cell, totals per condition.

Run ``uv run python -m verification_pilot.self_trust.tally <archive>...`` from
``experiments/``. Each archive is a ``raw/self_trust/runs/<run_id>`` directory.
This quick tally does not apply the publication report's exclusion rule;
it includes every indexed cell regardless of terminal cause.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


def cell_rows(archive: Path) -> list[dict[str, Any]]:
    index = json.loads((archive / "index.json").read_text(encoding="utf-8"))
    rows = []
    for cell_id, entry in sorted(index.items()):
        if "measures" not in entry:
            rows.append({"cell": cell_id, "status": entry["status"], "measured": False})
            continue
        traces = archive / "traces"
        measures = json.loads((traces / entry["measures"]).read_text(encoding="utf-8"))
        value = {(m["turn"], m["name"]): m["result"]["value"] for m in measures}
        trajectory = json.loads((traces / entry["trajectory"]).read_text(encoding="utf-8"))
        turns = trajectory["turns"]
        rows.append({
            "cell": cell_id, "status": entry["status"], "measured": True,
            "condition": value.get(("final", "condition")),
            "fixed": value.get(("final", "remnant_fixed")),
            "false_assurance": value.get(("final", "false_assurance")),
            "regressed": value.get(("final", "regressed")),
            "read_omission_file": [value.get((t, "module_read")) for t in ("T1", "T2", "T3")],
            "file_reads": sum(1 for turn in turns for call in turn["tool_calls"]
                              if call["name"] == "read_file"),
            "requests": sum((turn.get("usage") or {}).get("requests") or 0 for turn in turns),
            "stops": [event["cause"] for event in trajectory["events"]
                      if event.get("kind") in ("stopped", "turn_stopped") and "cause" in event],
        })
    return rows


def tally(archive: Path) -> dict[str, Any]:
    rows = cell_rows(archive)
    by_condition: dict[str, list[bool]] = defaultdict(list)
    assured: dict[str, list[bool]] = defaultdict(list)
    for row in rows:
        if row.get("measured") and row["condition"] in ("own", "teammate"):
            by_condition[row["condition"]].append(bool(row["fixed"]))
            if row.get("false_assurance") is not None:
                assured[row["condition"]].append(bool(row["false_assurance"]))
    spend_path = archive / "spend.json"
    return {
        "archive": archive.name,
        "spend_usd": (json.loads(spend_path.read_text())["spent_usd"]
                      if spend_path.exists() else None),
        "fixed": {condition: f"{sum(values)}/{len(values)}"
                  for condition, values in sorted(by_condition.items())},
        "false_assurance": {condition: f"{sum(values)}/{len(values)}"
                            for condition, values in sorted(assured.items())},
        "cells": rows,
    }


def main() -> None:
    archives = [Path(arg) for arg in sys.argv[1:]]
    if not archives:
        raise SystemExit("usage: python -m verification_pilot.self_trust.tally <archive>...")
    print(json.dumps([tally(archive) for archive in archives], indent=2))


if __name__ == "__main__":
    main()
