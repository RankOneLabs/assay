"""Deliberate failures on the real path, each expected to come back typed.

Scripted turns replace the model so every probe is deterministic and costs no
inference; the package, bridge, Docker sandbox, capture, sealing, settlement
and evaluator are the production ones. The Smithers probes do dispatch real
jobs, each a single short completion on the pinned machine.
"""

from __future__ import annotations

import json
import time
import urllib.request
from collections.abc import Callable
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import yaml

from assay.execution import AdmissionLedger, WorkerFailure, WorkerSuccess
from assay.models import CellCoordinate, EvaluationCoordinate, ExecutionCeiling
from workflow_edit.arms import MESS_00
from workflow_edit.bridge import ModelTurn, TurnCompletion
from workflow_edit.fixture import SMOKE_EDIT_SUBJECT_ID, load_fixture
from workflow_edit.qualify import (
    SMITHERS,
    Qualification,
    cell_record,
    prepare,
    run,
)


def scripted(
    *commands: tuple[str, dict[str, str]], pause_before_submit_s: float = 0.0
) -> Callable[[str], TurnCompletion]:
    """One tool call per turn, then ``submit_output`` once the script runs out.

    ``pause_before_submit_s`` stands in for a model's think time before its
    final turn, so a process left running can act after the last tool result.
    """

    def for_cell(cell_key: str) -> TurnCompletion:
        def turn(
            *,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
            max_tokens: int,
            turn: int,
            deadline: float | None,
        ) -> ModelTurn:
            if turn > len(commands):
                time.sleep(pause_before_submit_s)
            name, arguments = (
                commands[turn - 1] if turn <= len(commands) else ("submit_output", {"summary": "s"})
            )
            return ModelTurn(
                message={"role": "assistant", "content": None, "tool_calls": [{
                    "id": f"probe-{turn}", "type": "function",
                    "function": {"name": name, "arguments": json.dumps(arguments)},
                }]},
                finish_reason="tool_calls", prompt_tokens=0, completion_tokens=0, cost_usd=None,
            )

        return turn

    return for_cell


def command(text: str) -> tuple[str, dict[str, str]]:
    return ("run_command", {"command": text})


_FILL_MEMORY = "const a = []; for (;;) a.push(Buffer.alloc(1 << 24, 1))"

# probe name -> (scripted turns, expected settled outcome cause, cell budget seconds)
REJECTION_PROBES: dict[str, tuple[tuple[tuple[str, dict[str, str]], ...], str, float]] = {
    "empty_patch": ((), "candidate", 900.0),
    "storage_exhausted": (
        # /cache is quota-backed but never captured, so free space is the only
        # signal; a full /workspace is first an oversized captured tree.
        (command("head -c 400M /dev/zero > /cache/fill; df -k /cache"),),
        "storage_exhausted", 900.0,
    ),
    "memory_recovered": (
        # Filled buffers: untouched typed arrays hit bun's own allocation
        # limit (a RangeError) long before the cgroup sees the memory. The
        # kill lands inside the tool call, whose result the model sees, so the
        # submission stands.
        (command(f"bun -e '{_FILL_MEMORY}'"),),
        "candidate", 900.0,
    ),
    "memory_limit": (
        # A background loop keeps the cgroup at its ceiling, so the final
        # check counts OOM kills after the last tool result.
        (command(f"nohup sh -c \"while :; do bun -e '{_FILL_MEMORY}'; done\" >/dev/null 2>&1 &"),),
        "memory_limit", 900.0,
    ),
    "escaping_symlink": ((command("ln -s /etc/passwd src/link.ts"),), "escaping_symlink", 900.0),
    "binary_payload": ((command("printf 'a\\000b' > src/blob.ts"),), "binary_payload", 900.0),
    "oversized_artifact": (
        (command("head -c 9000000 /dev/urandom | base64 -w0 > src/big.ts"),),
        "oversized_artifact", 900.0,
    ),
    "out_of_scope_edit": (
        (("write_file", {"path": "notes.txt", "content": "scratch"}),),
        "out_of_scope_edit", 900.0,
    ),
    "tampering": (
        (("write_file", {"path": "package.json", "content": "{}\n"}),),
        "tampering", 900.0,
    ),
    "tool_timeout_recovered": ((command("sleep 600"),), "candidate", 900.0),
    "agent_deadline": ((command("sleep 600"),), "agent_deadline", 30.0),
}
# Think time before the scripted submission, for probes that need one.
SUBMIT_PAUSE_S = {"memory_limit": 10.0}


async def rejection_probe(
    q: Qualification, name: str, turns: tuple[tuple[str, dict[str, str]], ...], budget: float
) -> dict[str, Any]:
    fixture = load_fixture()
    probe = replace(
        q, completion_for=scripted(*turns, pause_before_submit_s=SUBMIT_PAUSE_S.get(name, 0.0)),
        run_label=f"{q.run_label}-{name}",
        cell_timeout_s=budget,
    )
    prepared = prepare(probe, repeats=1, ceiling=ExecutionCeiling(
        max_cells=1, max_wall_time_seconds=3600, max_fleet_occupancy=1))
    adapter = prepared.worker.adapter
    coordinate = CellCoordinate(
        subject_id=SMOKE_EDIT_SUBJECT_ID, arm_id=MESS_00, worker_repeat=0,
        realization_ref=prepared.snapshot.realizations[0].artifact_ref,
    )
    # The realization the worker is given is also the evaluator's baseline.
    realization = {"task": fixture.task, "repository": fixture.repository}
    started = time.monotonic()
    result = await adapter.run_cell(input_value=realization, coordinate=coordinate)
    record = cell_record(q.store, result, started_at="", seconds=time.monotonic() - started)
    record.pop("trajectory")
    record["retained_artifacts"] = sorted(record.pop("artifact_refs"))
    patch = record.pop("patch")
    record["patch_bytes"] = None if patch is None else len(patch.encode())
    if isinstance(result, WorkerSuccess):
        verdict = await prepared.evaluator.evaluate(
            input_value=realization, output=result.output,
            coordinate=EvaluationCoordinate(
                cell_id=coordinate.id, evaluator_id="correctness", evaluator_repeat=0),
        )
        record["evaluation"] = prepared.evaluator.records.get(coordinate.id)
        record["evaluation_type"] = type(verdict).__name__
    return record


class _DropFirstPost(httpx.AsyncBaseTransport):
    """Deliver the first submission, then lose its response on the way back."""

    def __init__(self) -> None:
        self._inner = httpx.AsyncHTTPTransport(retries=0)
        self.posts = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await self._inner.handle_async_request(request)
        if request.method == "POST":
            self.posts += 1
            if self.posts == 1:
                await response.aread()
                raise httpx.ReadError(
                    "response dropped after the server committed", request=request
                )
        return response

    async def aclose(self) -> None:
        await self._inner.aclose()


def _jobs_for(requester: str) -> list[dict[str, Any]]:
    with urllib.request.urlopen(f"{SMITHERS}/jobs?limit=200", timeout=30) as response:
        jobs = json.loads(response.read())["jobs"]
    return [job for job in jobs if job.get("requester") == requester]


PING = {
    "messages": [{"role": "user", "content": "Reply with the single word: ready"}],
    "max_tokens": 8,
    "temperature": 0.0,
}


async def idempotency_probe(q: Qualification) -> dict[str, Any]:
    requester = f"assay-wf13-idempotency-{int(time.time())}"
    factory = replace(q.factory(), requester=requester)
    client = factory.create(idempotency_key=f"{q.run_label}:idempotency")
    transport = _DropFirstPost()
    client._http = httpx.AsyncClient(transport=transport, timeout=30)
    try:
        completion = await client.complete_payload(PING)
    finally:
        await client.aclose()
    jobs = _jobs_for(requester)
    return {
        "posts": transport.posts,
        "result": type(completion).__name__,
        "job_id": getattr(completion, "job_id", None),
        "jobs_listed_for_requester": [job["job_id"] for job in jobs],
        "completions": sum(job["status"] == "complete" for job in jobs),
        "worker_model": getattr(completion, "worker_model", None),
    }


async def attestation_probe(q: Qualification, scratch: Path) -> dict[str, Any]:
    """Authorize a tag the worker will not run; its own attestation must refuse it."""
    routing = yaml.safe_load(q.routing_config.read_text())
    routing["models"]["qwen-coder-32b"]["backend_tags"]["vllm"] += "-not-served"
    altered = scratch / "routing_config.altered.yaml"
    altered.write_text(yaml.safe_dump(routing))
    client = q.factory(altered).create(idempotency_key=f"{q.run_label}:attestation")
    try:
        completion = await client.complete_payload(PING)
    finally:
        await client.aclose()
    return {
        "authorized_tag": client.configuration()["resolved_backend_tag"],
        "result": type(completion).__name__,
        "error_type": completion.error_type if isinstance(completion, WorkerFailure) else None,
        "message": completion.message if isinstance(completion, WorkerFailure) else None,
    }


async def ceiling_probe(q: Qualification) -> dict[str, Any]:
    probe = replace(q, completion_for=scripted(), run_label=f"{q.run_label}-ceiling")
    prepared = prepare(probe, repeats=2, ceiling=ExecutionCeiling(
        max_cells=1, max_wall_time_seconds=3600, max_fleet_occupancy=1))
    evidence = await run(prepared, q.store)
    return {
        "run": evidence["run"],
        "cells_dispatched": sorted(evidence["cells"]),
    }


def budget_probe() -> dict[str, Any]:
    """The monetary kind on the same ledger; the local route itself is unpriced."""
    ledger = AdmissionLedger(
        max_requests=10, max_spend_usd=Decimal("1.00"), request_cost_bound_usd=Decimal("0.60")
    )
    first, second = ledger.reserve("request"), ledger.reserve("request")
    return {
        "first": None if first is None else first.code,
        "second": None if second is None else second.code,
        "requests_admitted": ledger.requests,
    }


async def run_probes(q: Qualification) -> dict[str, Any]:
    scratch = q.store.root.parent / "probe-scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    rejections = {}
    for name, (turns, expected, budget) in REJECTION_PROBES.items():
        record = await rejection_probe(q, name, turns, budget)
        record["expected"] = expected
        rejections[name] = record
    return {
        "label": q.run_label,
        "image": q.image,
        "rejections": rejections,
        "idempotency": await idempotency_probe(q),
        "attestation": await attestation_probe(q, scratch),
        "ceiling": await ceiling_probe(q),
        "budget": budget_probe(),
    }
