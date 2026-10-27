"""Rebuild published self-trust session tables from committed archives and manifest.

Run ``uv run python -m verification_pilot.self_trust.report --out /tmp/self-trust-report``
from ``experiments/``. ``tables.csv`` and ``tables.json`` include an overall row
and expected-behavior-source strata for every manifest table. No object store
or model calls are used.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

from verification_pilot.self_trust.ledger import PUBLICATION_MANIFEST, RUNS, ledger
from verification_pilot.self_trust.settings import did_not_complete, excluded_cause
from verification_pilot.self_trust.wilson import wilson


def summarize(table: dict[str, Any], rows: list[dict[str, Any]],
              publication: dict[str, Any], source: str) -> dict[str, Any]:
    chosen = [r for r in rows if source == "all" or r["expected_behavior_source"] == source]
    ran = [r for r in chosen if r["terminal_status"] != "not_run"]
    excluded = [r for r in ran if excluded_cause(r.get("terminal_cause"))]
    counted = [r for r in ran if not excluded_cause(r.get("terminal_cause"))]
    restored = sum(r.get("remnant_fixed") is True for r in counted)
    nonrestored = [r for r in counted if r.get("remnant_fixed") is not True]
    models = {r["model"] for r in chosen}
    bounds = {str(r.get("max_turns") or "unknown") for r in ran}
    framing = {publication["runs"][r["run_id"]]["framing_version"] for r in chosen}
    def verdict(row: dict[str, Any]) -> str:
        if row.get("last_verdict"):
            return str(row["last_verdict"])
        if row["terminal_status"] in ("agent_limit", "timeout"):
            return "limit"
        return "no verdict"

    completed_normally = sum(r["terminal_status"] == "completed_valid" for r in counted)
    return {
        "table_id": table["id"],
        "location": table["location"],
        "expected_behavior_source": source,
        "protocol_version": table["protocol_version"],
        "step_bound_label": ",".join(sorted(bounds)) if bounds else "no runs",
        "framing_version_label": ",".join(sorted(framing)),
        "model_label": ",".join(sorted(table["model_mapping"][m] for m in models)),
        "planned": len(chosen),
        "ran": len(ran),
        "excluded_by_cause": dict(sorted(
            Counter(str(r["terminal_cause"]) for r in excluded).items())),
        "completed_normally": completed_normally,
        "counted": len(counted),
        "restored": restored,
        "wilson95": wilson(restored, len(counted)),
        "did_not_complete": sum(
            did_not_complete(r["terminal_status"], r.get("terminal_cause"))
            or r["terminal_status"] in ("agent_limit", "completed_no_verdict",
                                        "completed_invalid_output")
            for r in counted
        ),
        "judged_misses": sum(r["terminal_status"] == "completed_valid"
                             and r.get("remnant_fixed") is not True for r in counted),
        "interpretation": ("did not complete the protocol" if counted and not completed_normally
                           else ""),
        "nonrestored": len(nonrestored),
        "nonrestored_verdict_counts": dict(sorted(
            Counter(verdict(r) for r in nonrestored).items())),
        "nonrestored_last_verdict_complete": sum(
            r.get("last_verdict") == "complete" for r in nonrestored
        ),
        "nonrestored_false_assurance_final": sum(
            r.get("false_assurance_final") is True for r in nonrestored
        ),
        "status_counts": dict(sorted(Counter(r["terminal_status"] for r in chosen).items())),
        "archives": table["archives"],
    }


def build(manifest_path: Path = PUBLICATION_MANIFEST, runs: Path = RUNS) -> list[dict[str, Any]]:
    publication = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows = ledger(manifest_path, runs)
    by_key = {(r["run_id"], r["cell_id"]): r for r in rows}
    output: list[dict[str, Any]] = []
    for table in publication["tables"]:
        archives = set(table["archives"])
        if archives != set(table["cells"]):
            raise ValueError(f"{table['id']}: archives and cells disagree")
        versions = {publication["runs"][archive]["protocol_version"] for archive in archives}
        if versions != {table["protocol_version"]}:
            raise ValueError(f"{table['id']}: mixed or mismatched protocol versions: {versions}")
        chosen = [by_key[(archive, cell)] for archive, cells in table["cells"].items()
                  for cell in cells]
        if any(r["protocol_version"] != table["protocol_version"] for r in chosen):
            raise ValueError(f"{table['id']}: mixed protocol versions in selected cells")
        output.append(summarize(table, chosen, publication, "all"))
        for source in sorted({r["expected_behavior_source"] for r in chosen}):
            output.append(summarize(table, chosen, publication, source))
    return output


def write(rows: list[dict[str, Any]], out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "tables.json").write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    with (out / "tables.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows({k: json.dumps(v, sort_keys=True) if isinstance(v, (dict, list)) else v
                          for k, v in row.items()} for row in rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--manifest", type=Path, default=PUBLICATION_MANIFEST)
    parser.add_argument("--out", type=Path, default=Path("/tmp/self-trust-report"))
    args = parser.parse_args()
    rows = build(args.manifest)
    write(rows, args.out)
    print(f"{len(rows)} rows from {len({r['table_id'] for r in rows})} tables -> {args.out}")


if __name__ == "__main__":
    main()
