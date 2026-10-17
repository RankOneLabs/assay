"""Derive every SMOKE.md number from the committed wf-13 evidence.

Nothing here is supplied by hand: each figure is recomputed from the smoke,
probe, wake, pricing, and diagnosis evidence files written by ``workflow_edit.qualify``.
Failed cells are counted by typed cause, never filtered out.
"""

from __future__ import annotations

import argparse
import math
import statistics
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from workflow_edit.fixture import MAX_REPOSITORY_BYTES, MAX_REPOSITORY_FILES, load_fixture
from workflow_edit.qualify import CELL_TIMEOUT_S, read_evidence
from workflow_edit.settings import Part1AgentSettings

SMOKE_MD = Path(__file__).resolve().parent / "SMOKE.md"
# Turn events log the messages; every request also carried the fixed tool
# schemas. These are the bytes of the four-tool schema the wf-13 image ran
# (read_file, write_file, run_command, submit_output), not the current TOOLS:
# a later tool revision must never restate wf-13's request sizes.
TOOLS_BYTES = 1_120
TURNS = 20
# vLLM on mcbain serves the local model with --max-model-len 32768.
LOCAL_CONTEXT_TOKENS = 32_768


def quantile(values: Sequence[float], q: float) -> float:
    """Nearest-rank quantile; the published figure is always an observed value."""
    ordered = sorted(values)
    return ordered[max(0, math.ceil(q * len(ordered)) - 1)]


def _events(cell: Mapping[str, Any], kind: str) -> list[dict[str, Any]]:
    trajectory = cell.get("trajectory") or {}
    return [event for event in trajectory.get("events", []) if event.get("kind") == kind]


def stop_cause(cell: Mapping[str, Any]) -> str:
    """Settled outcome, refined by the loop's own stop reason where it has one."""
    outcome = cell["outcome"]
    if outcome["kind"] == "candidate":
        return "candidate"
    stopped = _events(cell, "stopped")
    loop = stopped[-1]["cause"] if stopped else None
    cause = outcome.get("cause") or outcome.get("error_type")
    return f"{cause}:{loop}" if loop and loop != cause else str(cause)


def cell_metrics(cells: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    turns = [event for cell in cells.values() for event in _events(cell, "model_request")]
    per_cell_turns = [len(_events(cell, "model_request")) for cell in cells.values()]
    seconds = [float(cell["seconds"]) for cell in cells.values()]
    peaks = [event for cell in cells.values() for event in _events(cell, "cgroup_peaks")]
    ratios = [
        (event["request_bytes"] + TOOLS_BYTES) / event["prompt_tokens"]
        for event in turns if event.get("prompt_tokens")
    ]
    decode = [
        event["completion_tokens"] / event["time_from_acceptance_seconds"]
        for event in turns
        if event.get("time_from_acceptance_seconds") and event["completion_tokens"] >= 256
    ]
    counts = Counter(stop_cause(cell) for cell in cells.values())
    tool_events = Counter(
        event["kind"]
        for cell in cells.values()
        for event in (cell.get("trajectory") or {}).get("events", [])
        if event["kind"] in (
            "tool_error", "tool_timeout", "tool_output_truncated", "conversation_truncated"
        )
    )
    prompt = [event["prompt_tokens"] for event in turns]
    completion = [event["completion_tokens"] for event in turns]
    return {
        "cells": len(cells),
        "outcomes": dict(sorted(counts.items())),
        "turns": len(turns),
        "turns_per_cell": {
            "min": min(per_cell_turns), "median": statistics.median(per_cell_turns),
            "max": max(per_cell_turns),
        },
        "prompt_tokens": {
            "median": statistics.median(prompt), "p95": quantile(prompt, 0.95), "max": max(prompt),
            "total": sum(prompt),
        },
        "completion_tokens": {
            "median": statistics.median(completion), "p95": quantile(completion, 0.95),
            "max": max(completion), "total": sum(completion),
        },
        "turns_at_output_cap": sum(event.get("finish_reason") == "length" for event in turns),
        "request_bytes_max": max(event["request_bytes"] for event in turns) + TOOLS_BYTES,
        "bytes_per_prompt_token": {"min": min(ratios), "median": statistics.median(ratios)},
        "decode_tokens_per_second_median": statistics.median(decode) if decode else None,
        "queue_seconds": {
            "median": statistics.median(e["queue_latency_seconds"] for e in turns),
            "max": max(e["queue_latency_seconds"] for e in turns),
        },
        "turn_seconds_from_acceptance": {
            "median": statistics.median(e["time_from_acceptance_seconds"] for e in turns),
            "max": max(e["time_from_acceptance_seconds"] for e in turns),
        },
        "cell_seconds": {
            "median": statistics.median(seconds), "p95": quantile(seconds, 0.95),
            "max": max(seconds),
        },
        "cells_at_deadline": sum(
            "agent_deadline" in stop_cause(cell) or "harness_deadline" in stop_cause(cell)
            for cell in cells.values()
        ),
        "tool_events": dict(sorted(tool_events.items())),
        "memory_peak_bytes_max": max((p["memory_peak_bytes"] for p in peaks), default=None),
        "pids_peak_max": max((p["pids_peak"] for p in peaks), default=None),
        "workspace_free_kb_min": min((p["workspace_free_kb"] for p in peaks), default=None),
        "oom_kills": sum(p.get("oom_kills", 0) for p in peaks),
        "peak_observations": len(peaks),
        "worker_models": sorted({e.get("worker_model") for e in turns if e.get("worker_model")}),
        "billing": sorted({e.get("billing") for e in turns}),
        "cell_coverage": dict(sorted(Counter(
            (cell.get("accounting") or {}).get("coverage", "missing") for cell in cells.values()
        ).items())),
    }


def correctness_metrics(
    cells: Mapping[str, Any], evaluations: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    verdicts = Counter(record["verdict"] for record in evaluations.values())
    groups: dict[str, Counter[str]] = {}
    for record in evaluations.values():
        for name, group in record["groups"].items():
            groups.setdefault(name, Counter())[group["status"]] += 1
    seconds = [record["seconds"] for record in evaluations.values()]
    return {
        "evaluated": len(evaluations),
        "dispatched": len(cells),
        "verdicts": dict(sorted(verdicts.items())),
        "correct_of_dispatched": verdicts.get("correct", 0),
        "groups": {name: dict(sorted(counter.items())) for name, counter in sorted(groups.items())},
        "empty_patches": sum(record["empty_patch"] for record in evaluations.values()),
        "evaluator_seconds_max": max(seconds) if seconds else None,
    }


def failure_diagnosis(diagnosis: Mapping[str, Any]) -> dict[str, Any]:
    """How many graded candidates each failing test or typecheck error accounts for."""
    tests: Counter[tuple[str, str]] = Counter()
    errors: Counter[str] = Counter()
    typecheck = 0
    for record in diagnosis["cells"].values():
        if "typecheck_errors" in record:
            typecheck += 1
            errors.update({f"{e['code']} {e['file']}" for e in record["typecheck_errors"]})
        for group, names in record.get("failing_tests", {}).items():
            tests.update((group, name) for name in names)
    return {
        "diagnosed": len(diagnosis["cells"]),
        "typecheck_failures": typecheck,
        "tests": sorted(tests.items(), key=lambda item: (-item[1], item[0])),
        "typecheck_errors": sorted(errors.items(), key=lambda item: (-item[1], item[0])),
    }


def hosted_worst_case(
    pricing: Mapping[str, Any], *, bytes_per_token_floor: float, settings: Part1AgentSettings
) -> dict[str, Any]:
    """A cell's worst case at each endpoint, computed from bounds without a paid call.

    The strict bound charges every request byte as a prompt token (no
    tokenizer packs less than one byte per token) and every turn the full
    output cap; the measured bound uses the smallest observed bytes-per-token.
    """
    strict_prompt = settings.max_request_bytes
    measured_prompt = math.ceil(settings.max_request_bytes / bytes_per_token_floor)
    output = settings.max_output_tokens
    rows = []
    for endpoint in pricing["endpoints"]:
        price = endpoint["pricing"]
        prompt_price, completion_price = float(price["prompt"]), float(price["completion"])

        def cell(prompt_tokens: int, p: float = prompt_price, c: float = completion_price) -> float:
            return TURNS * (prompt_tokens * p + output * c)

        rows.append({
            "provider": endpoint["provider_name"],
            "prompt_per_million": prompt_price * 1e6,
            "completion_per_million": completion_price * 1e6,
            "context_length": endpoint["context_length"],
            "max_completion_tokens": endpoint["max_completion_tokens"],
            "fits_context": endpoint["context_length"] >= strict_prompt + output,
            "strict_usd": cell(strict_prompt),
            "measured_usd": cell(measured_prompt),
        })
    return {
        "model": pricing["model"]["id"],
        "fetched_at": pricing["fetched_at"],
        "strict_prompt_tokens_per_turn": strict_prompt,
        "measured_prompt_tokens_per_turn": measured_prompt,
        "output_tokens_per_turn": output,
        "endpoints": sorted(rows, key=lambda row: row["strict_usd"]),
    }


def probe_rows(probes: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for name, record in probes["rejections"].items():
        outcome = record["outcome"]
        observed = outcome["kind"] if outcome["kind"] == "candidate" else outcome.get("cause")
        rows.append({
            "probe": name,
            "expected": record["expected"],
            "observed": observed,
            "matches": observed == record["expected"],
            "retained": record["retained_artifacts"],
            "evaluation": (record.get("evaluation") or {}).get("verdict"),
        })
    return rows


def _fmt(value: Any) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:,.3f}" if value < 100 else f"{value:,.0f}"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def _table(headers: Sequence[str], rows: Iterable[Sequence[Any]]) -> list[str]:
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join(_fmt(cell) for cell in row) + " |" for row in rows]
    return lines


def render() -> str:
    smoke, probes = read_evidence("smoke"), read_evidence("probes")
    wake, pricing = read_evidence("wake"), read_evidence("pricing")
    diagnosis = failure_diagnosis(read_evidence("diagnosis"))
    cells, run = smoke["cells"], smoke["run"]
    m = cell_metrics(cells)
    c = correctness_metrics(cells, smoke["evaluations"])
    settings = Part1AgentSettings()
    hosted = hosted_worst_case(
        pricing, bytes_per_token_floor=m["bytes_per_prompt_token"]["min"], settings=settings
    )
    fixture = load_fixture()
    package_bytes = sum(len(text.encode()) for text in fixture.repository.values())
    failures = {k: v for k, v in m["outcomes"].items() if k != "candidate"}
    lines = [
        "# Workflow edit smoke qualification (wf-13)",
        "",
        "Generated by `python -m workflow_edit.publish` from the committed evidence in",
        "`experiments/workflow_edit/evidence/wf13/`; every number below is recomputed",
        "from those files. The fixture (`fixtures/smoke-edit`) is a throwaway slice of",
        "oakridge-dbos at `f3b3ffca43e43672ff2f58ab797d65c7532aaed8` and is excluded from",
        "every Part 2 population.",
        "",
        "## Run",
        "",
        f"- Path: an authorized `assay-execution-plan/0.3.0` plan ({smoke['plan_ref']}) run "
        f"by `execute_plan`: `PierAdapter` packaging and settlement, the bridge repository "
        f"agent, every turn a keyed Smithers job on `mcbain` (`qwen-coder-32b`), and the "
        f"workflow correctness evaluator on each reconstructed patch.",
        f"- Result: `{run['result']}`, manifest `{run['manifest_ref']}`, status "
        f"`{run['status']}`, {len(run['missing_coordinates'])} missing coordinates.",
        f"- Image: `{smoke['image']}`; fixture identity `{smoke['fixture_identity']}`.",
        f"- Ceiling: {smoke['ceiling']['max_cells']} cells, "
        f"{smoke['ceiling']['max_wall_time_seconds']:,.0f} s wall, occupancy "
        f"{smoke['ceiling']['max_fleet_occupancy']}. Paid cells: 0. Per-turn billing: "
        f"{', '.join(m['billing'])} (Smithers prices no turn; local cost is unpriced, not "
        f"zero). Cell cost coverage: "
        + ", ".join(f"{n} {coverage}" for coverage, n in m["cell_coverage"].items()) + ".",
        f"- Worker-attested model on every turn: {', '.join(m['worker_models'])}.",
        "",
        "## Outcomes and failure rate",
        "",
        f"{m['cells']} cells dispatched. {m['outcomes'].get('candidate', 0)} settled as "
        f"candidates; {sum(failures.values())} ended in a typed failure "
        f"(failure rate {sum(failures.values()) / m['cells']:.0%}, denominator {m['cells']}).",
        "",
        *_table(("Settled outcome (cause:loop stop)", "Cells"), m["outcomes"].items()),
        "",
        f"Correctness, over all {c['dispatched']} dispatched cells: "
        f"{c['correct_of_dispatched']} correct. Of {c['evaluated']} evaluated candidates: "
        + ", ".join(f"{count} {name}" for name, count in c["verdicts"].items())
        + f"; {c['empty_patches']} empty patches graded as no-op candidates.",
        "",
        *_table(("Group", "Results"), (
            (name, ", ".join(f"{n} {status}" for status, n in counts.items()))
            for name, counts in c["groups"].items()
        )),
        "",
        f"Why graded candidates failed: the evaluator keeps no test output, so "
        f"`python -m workflow_edit.qualify diagnose` replays each failed group in the same "
        f"image and names the failing tests ({diagnosis['diagnosed']} candidates; "
        f"{diagnosis['typecheck_failures']} stopped at the typecheck). Verdicts above are "
        f"the evaluator's; this only names their causes.",
        "",
        *_table(("Group", "Failing test", "Candidates"), (
            (group, name, n) for (group, name), n in diagnosis["tests"]
        )),
        "",
        *_table(("Typecheck error", "Candidates"), diagnosis["typecheck_errors"]),
        "",
        "## Token envelope",
        "",
        *_table(("Measurement", "Value"), [
            ("Model turns", m["turns"]),
            ("Turns per cell (min / median / max)",
             f"{m['turns_per_cell']['min']} / {m['turns_per_cell']['median']} / "
             f"{m['turns_per_cell']['max']}"),
            ("Prompt tokens per turn (median / p95 / max)",
             f"{m['prompt_tokens']['median']:,} / {m['prompt_tokens']['p95']:,} / "
             f"{m['prompt_tokens']['max']:,}"),
            ("Completion tokens per turn (median / p95 / max)",
             f"{m['completion_tokens']['median']:,} / {m['completion_tokens']['p95']:,} / "
             f"{m['completion_tokens']['max']:,}"),
            ("Turns cut off at the output cap", m["turns_at_output_cap"]),
            ("Largest request (bytes of messages + tools)", m["request_bytes_max"]),
            ("Request bytes per prompt token (min / median)",
             f"{m['bytes_per_prompt_token']['min']:.2f} / "
             f"{m['bytes_per_prompt_token']['median']:.2f}"),
            ("Tool events", ", ".join(f"{k} {v}" for k, v in m["tool_events"].items()) or "none"),
            ("Prompt / completion tokens, all cells",
             f"{m['prompt_tokens']['total']:,} / {m['completion_tokens']['total']:,}"),
        ]),
        "",
        "## Time",
        "",
        *_table(("Measurement", "Value"), [
            ("Cell wall seconds (median / p95 / max)",
             f"{m['cell_seconds']['median']:.1f} / {m['cell_seconds']['p95']:.1f} / "
             f"{m['cell_seconds']['max']:.1f}"),
            ("Cell budget", f"{CELL_TIMEOUT_S:.0f} s from bridge entry"),
            ("Cells stopped by the budget", m["cells_at_deadline"]),
            ("Turn seconds from worker acceptance (median / max)",
             f"{m['turn_seconds_from_acceptance']['median']:.1f} / "
             f"{m['turn_seconds_from_acceptance']['max']:.1f}"),
            ("Queue seconds per turn (median / max)",
             f"{m['queue_seconds']['median']:.2f} / {m['queue_seconds']['max']:.2f}"),
            ("Decode rate, turns of 256+ tokens (median tokens/s)",
             m["decode_tokens_per_second_median"]),
            ("Cold wake of mcbain (Smithers wake to awake)",
             f"{wake['cold_wake_seconds']} s ({wake['status_before']} before)"
             if wake.get("cold_wake_seconds") is not None else
             f"not measured: mcbain was {wake['status_before']}"),
            ("Evaluator seconds per cell (max)", c["evaluator_seconds_max"]),
        ]),
        "",
        "## Footprint",
        "",
        *_table(("Measurement", "Value"), [
            ("Peak memory, any cell (cgroup memory.peak, bytes)", m["memory_peak_bytes_max"]),
            ("Peak PIDs, any cell (cgroup pids.peak)", m["pids_peak_max"]),
            ("Least free workspace tmpfs, any cell (KiB)", m["workspace_free_kb_min"]),
            ("OOM kills", m["oom_kills"]),
            ("Cells with a peak observation", m["peak_observations"]),
            ("Package", f"{len(fixture.repository)} files, {package_bytes:,} bytes, against "
                        f"authorized limits of {MAX_REPOSITORY_FILES} files and "
                        f"{MAX_REPOSITORY_BYTES:,} bytes"),
        ]),
        "",
        "## Hosted worst case",
        "",
        f"Computed for `{hosted['model']}` from the OpenRouter catalogue fetched "
        f"{hosted['fetched_at']}, with no paid call. Strict: every one of "
        f"{TURNS} turns sends a {hosted['strict_prompt_tokens_per_turn']:,}-token prompt "
        f"(one token per request byte) and returns {hosted['output_tokens_per_turn']:,} "
        f"tokens. Measured: the prompt is the request ceiling at the smallest observed "
        f"bytes per token ({hosted['measured_prompt_tokens_per_turn']:,} tokens). Account "
        "rate limits need a key and are not in the public catalogue.",
        "",
        *_table(
            ("Endpoint", "$/M prompt", "$/M completion", "Context", "Max completion",
             "Fits", "Strict $/cell", "Measured $/cell"),
            ((r["provider"], r["prompt_per_million"], r["completion_per_million"],
              r["context_length"], r["max_completion_tokens"], r["fits_context"],
              round(r["strict_usd"], 3), round(r["measured_usd"], 3))
             for r in hosted["endpoints"]),
        ),
        "",
        "## Typed rejections (scripted turns, real sandbox and settlement)",
        "",
        *_table(("Probe", "Expected", "Observed", "Match", "Evaluator"), (
            (r["probe"], r["expected"], r["observed"], r["matches"], r["evaluation"] or "-")
            for r in probe_rows(probes)
        )),
        "",
        "## Smithers and admission probes",
        "",
        f"- Dropped-response re-dispatch: {probes['idempotency']['posts']} POSTs, "
        f"{len(probes['idempotency']['jobs_listed_for_requester'])} job listed "
        f"(`{probes['idempotency']['job_id']}`), {probes['idempotency']['completions']} "
        "completion.",
        f"- Worker attestation: authorizing tag `{probes['attestation']['authorized_tag']}` "
        f"returned `{probes['attestation']['error_type']}`.",
        f"- Capacity ceiling: a 2-cell plan with `max_cells: 1` dispatched "
        f"{len(probes['ceiling']['cells_dispatched'])} cell and ended "
        f"`{probes['ceiling']['run']['status']}` with "
        f"{len(probes['ceiling']['run']['missing_coordinates'])} missing coordinates (the "
        "undispatched cell and its evaluation).",
        f"- Monetary ceiling (ledger probe): first reservation "
        f"`{probes['budget']['first'] or 'admitted'}`, second `{probes['budget']['second']}`.",
        "",
        "## Qualified bounds",
        "",
        *_table(("Bound", "Value", "Observed"), [
            ("max_output_tokens", settings.max_output_tokens, m["completion_tokens"]["max"]),
            ("max_request_bytes", settings.max_request_bytes, m["request_bytes_max"]),
            ("max_conversation_bytes", settings.max_conversation_bytes,
             f"{m['tool_events'].get('conversation_truncated', 0)} truncations"),
            ("max_tool_output_bytes", settings.max_tool_output_bytes,
             f"{m['tool_events'].get('tool_output_truncated', 0)} truncations"),
            ("max_storage_mb", settings.max_storage_mb,
             f"{m['workspace_free_kb_min']:,} KiB least free of the 256 MiB workspace "
             "(workspace + cache = 512 MiB)"),
            ("local context", LOCAL_CONTEXT_TOKENS,
             f"max prompt {m['prompt_tokens']['max']:,} + output cap "
             f"{settings.max_output_tokens:,}"),
        ]),
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=SMOKE_MD)
    args = parser.parse_args()
    args.output.write_text(render(), encoding="utf-8")


if __name__ == "__main__":
    main()
