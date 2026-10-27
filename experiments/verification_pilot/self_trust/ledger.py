"""Build the attempt-level ledger: one row per planned session in every archive.

The ledger reads committed archives and ``raw/self_trust/publication-manifest.json``.
Historical st-v1 configurations and planned cells were recovered from the
frozen audit ledger and committed in that manifest. Measures are read directly
from the archive; only the protocol's exclusion predicate is imported.

Run ``uv run python -m verification_pilot.self_trust.ledger`` from ``experiments/``.
The result is written outside the tracked tree by default.

Terminal status is normalized from the stop cause and the last model request:

- ``completed_valid``: every turn ran and the session was not stopped.
- ``completed_no_verdict``: the agent ended a turn with prose and no tool call.
- ``completed_invalid_output``: it ended a turn with an empty reply.
- ``provider_error``: the provider returned an error, refused, failed its
  identity check, or the transport failed. A ``no_tool_call`` stop whose last
  request has ``finish_reason`` "error" lands here, not in the two above.
- ``budget_cut``: the run's dollar cap stopped the session.
- ``agent_limit``: a request, tool-call or output-token limit stopped it.
- ``timeout``: a wall-clock deadline stopped it (agent or Smithers job).
- ``not_run``: planned in the run's plan but absent from its index.
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
from pathlib import Path
from typing import Any

from verification_pilot.self_trust.settings import excluded_cause

PILOT = Path(__file__).resolve().parents[1]
RUNS = PILOT / "raw" / "self_trust" / "runs"
PUBLICATION_MANIFEST = PILOT / "raw" / "self_trust" / "publication-manifest.json"
OUT = Path("/tmp/self-trust-report/ledger.csv")

PROVIDER_CAUSES = {
    "provider_response",
    "provider_identity",
    "transport_failure",
    "billing_uncertain",
}
LIMIT_CAUSES = {"turn_limit", "turn_tool_call_limit", "cell_tool_call_limit", "output_token_limit"}
TIMEOUT_CAUSES = {"agent_deadline", "model_dispatch:AcceptanceDeadlineExceeded"}

FIELDS = [
    "run_id",
    "cell_id",
    "run_label",
    "archived_commit",
    "archived_at",
    "fixture",
    "subject_id",
    "share",
    "omission",
    "arm_id",
    "worker_repeat",
    "framing",
    "model",
    "provider",
    "endpoint",
    "backend",
    "temperature",
    "configuration_ref",
    "system_prompt_sha256",
    "turn_prompts_sha256",
    "tools_sha256",
    "subject_rendering",
    "realization_ref",
    "image_digest",
    "package_digest",
    "max_turns",
    "max_tool_calls_per_turn",
    "max_tool_calls_per_cell",
    "max_output_tokens",
    "timeout_s",
    "provider_retries",
    "attempts",
    "index_status",
    "stop_causes",
    "terminal_cause",
    "terminal_status",
    "turn_truncated",
    "turns_run",
    "last_finish_reason",
    "last_reply_empty",
    "bridge_cause",
    "verdict_t2",
    "verdict_t3",
    "last_verdict",
    "remnant_fixed",
    "regressed",
    "false_assurance",
    "false_assurance_final",
    "tsc_exit",
    "visible_exit",
    "hidden",
    "module_read_t1",
    "module_read_t2",
    "module_read_t3",
    "requests",
    "tokens_in",
    "tokens_out",
    "cost_usd",
    "model_seconds",
    "trajectory_ref",
    "measures_ref",
    "worker_ref",
]


def archived(run_dir: Path) -> tuple[str, str]:
    out = subprocess.run(
        ["git", "log", "--diff-filter=A", "--format=%H %cI", "--", str(run_dir / "index.json")],
        cwd=PILOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    return (out[-2], out[-1]) if out else ("", "")


def terminal(
    index_status: str,
    cause: str | None,
    last_request: dict[str, Any] | None,
    last_reply: dict[str, Any] | None,
) -> str:
    if cause is None:
        return "completed_valid" if index_status == "succeeded" else "unclassified"
    if cause == "no_tool_call":
        if last_request and last_request.get("finish_reason") == "error":
            return "provider_error"
        if last_reply is not None and not (last_reply.get("content") or "").strip():
            return "completed_invalid_output"
        return "completed_no_verdict"
    if cause == "budget_exhausted":
        return "budget_cut"
    if cause in PROVIDER_CAUSES or excluded_cause(cause):
        return "provider_error"
    if cause in LIMIT_CAUSES:
        return "agent_limit"
    if cause in TIMEOUT_CAUSES:
        return "timeout"
    return "unclassified"


def cell_row(
    run_dir: Path, cell_id: str, entry: dict[str, Any],
    configurations: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    traces = run_dir / "traces"
    trajectory = json.loads((traces / entry["trajectory"]).read_text(encoding="utf-8"))
    worker = json.loads((traces / entry["worker_trace"]).read_text(encoding="utf-8"))
    measures = json.loads((traces / entry["measures"]).read_text(encoding="utf-8"))
    value = {(m["turn"], m["name"]): m["result"]["value"] for m in measures}
    events = trajectory["events"]
    binding = worker.get("binding") or {}
    coordinate = worker.get("coordinate") or {}
    config_ref = binding.get("configuration_ref")
    config = entry.get("configuration") or configurations.get(str(config_ref), {})
    route = config.get("model_route") or config
    bounds = config.get("bounds") or config

    stops = [e for e in events if e["kind"] in ("stopped", "turn_stopped")]
    final_stop = next((e["cause"] for e in stops if e["kind"] == "stopped"), None)
    requests = [e for e in events if e["kind"] == "model_request"]
    replies = [e for e in events if e["kind"] == "reply_without_tool_call"]
    label = next(
        (
            e["cache"].split("/.assay-vp/")[1].split("/")[0]
            for e in events
            if e["kind"] == "sandbox_created" and "/.assay-vp/" in e.get("cache", "")
        ),
        "",
    )
    usage = [t.get("usage") or {} for t in trajectory["turns"]]
    subject = coordinate.get("subject_id", cell_id.split(":")[0])
    parts = subject.split("-")
    checks = value.get(("final", "checks")) or {}

    return {
        "run_id": run_dir.name,
        "cell_id": cell_id,
        "run_label": label,
        "fixture": "-".join(parts[:-2]),
        "subject_id": subject,
        "share": parts[-2],
        "omission": parts[-1],
        "arm_id": coordinate.get("arm_id"),
        "worker_repeat": coordinate.get("worker_repeat"),
        "framing": value.get(("final", "condition")),
        "model": route.get("model"),
        "provider": route.get("provider"),
        "endpoint": route.get("endpoint"),
        "backend": (config.get("turns") or {}).get("backend"),
        "temperature": config.get("temperature", "unset"),
        "configuration_ref": binding.get("configuration_ref"),
        "system_prompt_sha256": config.get("system_prompt_sha256"),
        "turn_prompts_sha256": config.get("turn_prompts_sha256"),
        "tools_sha256": config.get("tools_sha256"),
        "subject_rendering": config.get("subject_rendering"),
        "realization_ref": coordinate.get("realization_ref"),
        "image_digest": binding.get("image_digest"),
        "package_digest": binding.get("package_digest"),
        "max_turns": bounds.get("max_turns"),
        "max_tool_calls_per_turn": config.get("max_tool_calls_per_turn"),
        "max_tool_calls_per_cell": config.get("max_tool_calls_per_cell"),
        "max_output_tokens": bounds.get("max_output_tokens"),
        "timeout_s": config.get("timeout_s"),
        "provider_retries": config.get("provider_retries"),
        "attempts": config.get("attempts"),
        "index_status": entry["status"],
        "stop_causes": "|".join(f"{e['kind']}:{e['cause']}" for e in stops),
        "terminal_cause": ("provider_response" if final_stop == "no_tool_call"
                           and requests and requests[-1].get("finish_reason") == "error"
                           else final_stop),
        "terminal_status": terminal(
            entry["status"],
            final_stop,
            requests[-1] if requests else None,
            replies[-1] if replies and final_stop == "no_tool_call" else None,
        ),
        "turn_truncated": any(e["kind"] == "turn_stopped" for e in stops),
        "turns_run": len(trajectory["turns"]),
        "last_finish_reason": requests[-1].get("finish_reason") if requests else None,
        "last_reply_empty": (not (replies[-1].get("content") or "").strip()) if replies else None,
        "bridge_cause": (worker.get("bridge_outcome") or {}).get("cause"),
        "verdict_t2": value.get(("T2", "review_verdict")),
        "verdict_t3": value.get(("T3", "review_verdict")),
        "last_verdict": value.get(("T3", "review_verdict")) or value.get(("T2", "review_verdict")),
        "remnant_fixed": value.get(("final", "remnant_fixed")),
        "regressed": value.get(("final", "regressed")),
        "false_assurance": value.get(("final", "false_assurance")),
        "false_assurance_final": value.get(("final", "false_assurance_final"),
                                            value.get(("T3", "review_verdict")) == "complete"
                                            and value.get(("final", "remnant_fixed")) is False),
        "tsc_exit": checks.get("tsc"),
        "visible_exit": checks.get("visible"),
        "hidden": json.dumps(checks.get("hidden"), sort_keys=True) if checks else None,
        "module_read_t1": value.get(("T1", "module_read")),
        "module_read_t2": value.get(("T2", "module_read")),
        "module_read_t3": value.get(("T3", "module_read")),
        "requests": len(requests),
        "tokens_in": sum(e.get("prompt_tokens") or 0 for e in requests),
        "tokens_out": sum(e.get("completion_tokens") or 0 for e in requests),
        "cost_usd": round(sum(float(u.get("cost_usd") or 0) for u in usage), 6),
        "model_seconds": round(sum(e.get("seconds") or 0 for e in requests), 3),
        "trajectory_ref": f"{run_dir.name}/traces/{entry['trajectory']}",
        "measures_ref": f"{run_dir.name}/traces/{entry['measures']}",
        "worker_ref": f"{run_dir.name}/traces/{entry['worker_trace']}",
    }


def ledger(manifest_path: Path = PUBLICATION_MANIFEST, runs: Path = RUNS) -> list[dict[str, Any]]:
    publication = json.loads(manifest_path.read_text(encoding="utf-8"))
    configurations = publication["configurations"]
    rows: list[dict[str, Any]] = []
    for run_dir in sorted(p for p in runs.iterdir() if (p / "index.json").exists()):
        index = json.loads((run_dir / "index.json").read_text(encoding="utf-8"))
        run_meta = publication["runs"].get(run_dir.name)
        if run_meta is None:
            raise ValueError(f"archive {run_dir.name} absent from publication manifest")
        commit, when = archived(run_dir)
        run_rows = [
            cell_row(run_dir, cell_id, entry, configurations)
            for cell_id, entry in sorted(index.items())
        ]
        planned = set(run_meta["planned_cells"])
        if not set(index) <= planned:
            raise ValueError(f"unplanned cells in {run_dir.name}")
        for cell_id in sorted(planned - set(index)):
            subject = cell_id.split(":")[0]
            parts = subject.split("-")
            run_rows.append(
                {
                    "run_id": run_dir.name,
                    "cell_id": cell_id,
                    "fixture": "-".join(parts[:-2]),
                    "subject_id": subject,
                    "share": parts[-2],
                    "omission": parts[-1],
                    "arm_id": cell_id.split(":")[1],
                    "worker_repeat": int(cell_id.rsplit(":w", 1)[1]),
                    "index_status": "absent",
                    "terminal_status": "not_run",
                    "run_label": run_rows[0]["run_label"] if run_rows else "",
                }
            )
        for row in run_rows:
            row["archived_commit"], row["archived_at"] = commit, when
            row["plan_resolved"] = True
            row["model"] = row.get("model") or run_meta["model"]
            row["protocol_version"] = run_meta["protocol_version"]
            row["framing_version"] = run_meta["framing_version"]
            row["expected_behavior_source"] = (
                "new_fix" if row["fixture"] == "rewrite" and row["omission"] == "remnant_c"
                else "old_behavior"
            )
        rows.extend(run_rows)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--manifest", type=Path, default=PUBLICATION_MANIFEST)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    rows = ledger(args.manifest)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=FIELDS + ["plan_resolved", "protocol_version",
                                       "framing_version", "expected_behavior_source"],
            extrasaction="ignore"
        )
        writer.writeheader()
        writer.writerows(rows)
    print(f"{len(rows)} rows -> {args.out}")


if __name__ == "__main__":
    main()
