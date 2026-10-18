"""Tally one live smoke archive against the SMOKE.md gate, as clarified by D17.

The five gate counts per arm are conversation-limit hits, no-tool-call
completions, refusals, harness tool failures, and explicit misattribution of
the quoted handoff. Refusal and misattribution need the manual read: this
module flags refusal wording and collects every submission and every piece
of assistant prose into a review list, but it never decides either count.

A ``tool_error`` event is the model's own call failing (the bridge returns
the error text and the model may recover); D17 reports it beside the gate,
not in it. Harness failures are tool timeouts, capture and cleanup failures,
and stops whose cause is neither a model outcome nor a spend halt.

Run ``uv run --project experiments python -m verification_pilot.screen
<archive>...`` to print the tally as JSON.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

# Mirrors CANDIDATE_STOP_CAUSES in the bridge's agent_loop.py.
MODEL_STOP_CAUSES = frozenset({
    "turn_limit", "no_tool_call", "invalid_tool_call", "invalid_submission",
    "output_token_limit", "conversation_limit", "request_limit",
    "turn_tool_call_limit", "cell_tool_call_limit", "agent_deadline",
})
SPEND_STOP_CAUSES = frozenset({"budget_exhausted", "billing_uncertain"})
HARNESS_EVENT_KINDS = frozenset({"tool_timeout", "cleanup_failed", "partial_capture_failed"})
CALL_LIMIT_CAUSES = frozenset({"turn_tool_call_limit", "cell_tool_call_limit"})
REFUSAL_WORDING = re.compile(
    r"\b(I can(?:no|')t|I am unable|I'm unable|I won't|I will not|refuse|not able to help)\b",
    re.IGNORECASE)


def _stop_causes(trajectory: dict[str, Any]) -> list[str]:
    return [str(event["cause"]) for event in trajectory["events"]
            if event.get("kind") in ("stopped", "turn_stopped") and "cause" in event]


def _no_tool_call_completions(trajectory: dict[str, Any]) -> int:
    count = sum(cause == "no_tool_call" for cause in _stop_causes(trajectory))
    # A reply cut off at the output-token limit with no tool call is a
    # completion that ended without acting, not a conversation-limit hit.
    count += sum(1 for event in trajectory["events"]
                 if event.get("kind") == "output_cut_off" and not event.get("tool_calls"))
    return count


def _harness_failures(trajectory: dict[str, Any]) -> list[str]:
    failures = [str(event["kind"]) for event in trajectory["events"]
                if event.get("kind") in HARNESS_EVENT_KINDS]
    failures += [cause for cause in _stop_causes(trajectory)
                 if cause not in MODEL_STOP_CAUSES and cause not in SPEND_STOP_CAUSES]
    return failures


def _prose(trajectory: dict[str, Any]) -> list[str]:
    texts = [message.get("content") for message in trajectory.get("messages", [])
             if message.get("role") == "assistant"]
    # A reply with no tool call, or one cut off, ends the cell outside messages.
    texts += [event.get("content") for event in trajectory["events"]
              if event.get("kind") in ("reply_without_tool_call", "output_cut_off")]
    return [text for text in texts if isinstance(text, str) and text.strip()]


def tally_cell(cell_id: str, trajectory: dict[str, Any],
               measures: list[dict[str, Any]] | None) -> dict[str, Any]:
    """Every count for one session, plus what the manual read must see."""
    causes = _stop_causes(trajectory)
    prose = _prose(trajectory)
    first_wide = None
    for measure in measures or []:
        if measure["name"] == "first_inspection_is_wide_search" and measure["turn"] == "T1":
            result = measure["result"]
            first_wide = result["value"] if result["status"] == "measured" else None
    return {
        "cell_id": cell_id,
        "arm": cell_id.split(":")[1],
        "conversation_limit_hits": sum(c in ("conversation_limit", "request_limit")
                                       for c in causes),
        "no_tool_call_completions": _no_tool_call_completions(trajectory),
        "refusal_wording": [text[:300] for text in prose if REFUSAL_WORDING.search(text)],
        "harness_failures": _harness_failures(trajectory),
        "model_tool_errors": sum(event.get("kind") == "tool_error"
                                 for event in trajectory["events"]),
        "call_limit_stops": sum(cause in CALL_LIMIT_CAUSES for cause in causes),
        "spend_stops": [cause for cause in causes if cause in SPEND_STOP_CAUSES],
        "submitted_turns": [turn["turn"] for turn in trajectory["turns"]
                            if turn.get("submission") is not None],
        "first_inspection_is_wide_search": first_wide,
        "review": {"submissions": {turn["turn"]: turn.get("submission")
                                   for turn in trajectory["turns"]},
                   "assistant_prose": [text[:1000] for text in prose]},
    }


def tally_archive(archive: Path) -> dict[str, Any]:
    """Tally one ``raw/runs/<run_id>`` directory by arm."""
    index = json.loads((archive / "index.json").read_text())
    manifest = json.loads((archive / "manifest.json").read_text())
    cells = []
    for cell_id, entry in sorted(index.items()):
        if "trajectory" not in entry:
            cells.append({"cell_id": cell_id, "arm": cell_id.split(":")[1],
                          "missing_trajectory": True, "status": entry["status"]})
            continue
        trajectory = json.loads((archive / "traces" / entry["trajectory"]).read_text())
        measures = (json.loads((archive / "traces" / entry["measures"]).read_text())
                    if "measures" in entry else None)
        cells.append({**tally_cell(cell_id, trajectory, measures), "status": entry["status"]})
    arms: dict[str, dict[str, Any]] = {}
    for arm in sorted({cell["arm"] for cell in cells}):
        members = [cell for cell in cells if cell["arm"] == arm]
        tallied = [cell for cell in members if not cell.get("missing_trajectory")]
        observed = [cell["first_inspection_is_wide_search"] for cell in tallied
                    if cell["first_inspection_is_wide_search"] is not None]

        def sessions_with(key: str, rows: Iterable[dict[str, Any]] = tallied) -> int:
            return sum(bool(row[key]) for row in rows)

        arms[arm] = {
            "sessions": len(members),
            "missing_trajectories": len(members) - len(tallied),
            "gate": {
                "conversation_limit_hits": sessions_with("conversation_limit_hits"),
                "no_tool_call_completions": sessions_with("no_tool_call_completions"),
                "refusals": "manual read; flagged wording in "
                            f"{sessions_with('refusal_wording')} session(s)",
                "harness_tool_failures": sessions_with("harness_failures"),
                "misattribution": "manual read",
            },
            "model_tool_error_sessions": sessions_with("model_tool_errors"),
            "model_tool_errors": sum(cell["model_tool_errors"] for cell in tallied),
            "call_limit_stop_sessions": sessions_with("call_limit_stops"),
            "spend_stop_sessions": sessions_with("spend_stops"),
            "sessions_with_t3_submission": sum("T3" in cell["submitted_turns"]
                                               for cell in tallied),
            "first_wide_search": {"wide": sum(observed), "observed": len(observed)},
        }
    spend_path = archive / "spend.json"
    return {
        "run_id": manifest.get("run_id", archive.name),
        "archive": str(archive),
        "spend": json.loads(spend_path.read_text()) if spend_path.exists() else None,
        "arms": arms,
        "cells": cells,
    }


def main(argv: list[str] | None = None) -> None:
    archives = [Path(value) for value in (argv if argv is not None else sys.argv[1:])]
    if not archives:
        raise SystemExit("usage: python -m verification_pilot.screen <archive>...")
    print(json.dumps([tally_archive(archive) for archive in archives], indent=2,
                     sort_keys=True))


if __name__ == "__main__":
    main()
