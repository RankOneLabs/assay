"""Pinned Smithers inference client for one authorized workflow cell.

Smithers 9e305b6 echoes the alias and machine in JobResponse, but does not
expose the backend tag there. We pin the tag from its routing file and reject
any change to that file before accepting a completed job.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import httpx
import yaml
from jig.core.errors import JigLLMError
from jig.core.types import CompletionParams, LLMResponse, Usage
from jig.llm.dispatch import DispatchClient, _parse_tool_calls

from assay.adapters.consistency import DescribedClient
from assay.canonical import canonical_json, digest_bytes
from assay.execution import WorkerFailure


def _routing_identity(path: Path, alias: str, machine: str) -> tuple[str, str]:
    """Mirror Router.resolve_backend_tag and validate its Level-1 pair."""
    raw = path.read_bytes()
    config = yaml.safe_load(raw)
    if not isinstance(config, dict):
        raise ValueError("invalid Smithers routing configuration")
    machines = config.get("machines")
    models = config.get("models")
    if not isinstance(machines, dict) or not isinstance(models, dict):
        raise ValueError("invalid Smithers routing configuration")
    model = models.get(alias)
    machine_config = machines.get(machine)
    if not isinstance(model, dict) or not isinstance(machine_config, dict):
        raise ValueError("unknown Smithers model or machine")
    if machine not in model.get("machines", []):
        raise ValueError("Smithers model is unavailable on the authorized machine")
    backend = machine_config.get("backend", "ollama")
    tags = model.get("backend_tags", {})
    if not isinstance(tags, dict):
        raise ValueError("invalid Smithers backend tags")
    tag = tags.get(backend)
    if tag is None and backend == "ollama":
        tag = model.get("ollama_tag")
    if not isinstance(tag, str) or not tag:
        raise ValueError("Smithers alias has no tag for the machine backend")
    return digest_bytes(raw), tag


@dataclasses.dataclass(frozen=True)
class SmithersFactory:
    model: str
    machine: str
    routing_config: Path
    dispatch_url: str
    requester: str = "assay-workflow-edit"
    timeout_seconds: Literal[900] = 900
    poll_interval: float = 0.5

    def __post_init__(self) -> None:
        if self.timeout_seconds != 900:
            raise ValueError("Smithers workflow cells have a 900-second acceptance budget")

    def configuration(self) -> dict[str, Any]:
        digest, tag = _routing_identity(self.routing_config, self.model, self.machine)
        return {
            "model": self.model,
            "machine": self.machine,
            "resolved_backend_tag": tag,
            "routing_config_digest": digest,
            "endpoint": self.dispatch_url.rstrip("/"),
            "requester": self.requester,
            "timeout_seconds": self.timeout_seconds,
            "poll_interval": self.poll_interval,
            "revision": "assay-smithers-9e305b6-v1",
            "billing": "unavailable",
            "hidden_retries": 0,
        }

    def create(self, *, idempotency_key: str) -> SmithersClient:
        if not idempotency_key or len(idempotency_key) > 255:
            raise ValueError("a nonempty Smithers idempotency key is required")
        return SmithersClient(self, idempotency_key, self.configuration())


class SmithersRequestError(RuntimeError):
    def __init__(self, failure: WorkerFailure) -> None:
        self.failure = failure
        super().__init__(failure.message)


class SmithersClient(DispatchClient, DescribedClient):
    """One completion job; retrying its POST uses the same semantic request."""

    def __init__(
        self, factory: SmithersFactory, idempotency_key: str, configuration: dict[str, Any]
    ) -> None:
        super().__init__(
            model=factory.model,
            machine=factory.machine,
            dispatch_url=factory.dispatch_url,
            requester=factory.requester,
            timeout_seconds=factory.timeout_seconds,
            poll_interval=factory.poll_interval,
        )
        self._factory = factory
        self._idempotency_key = idempotency_key
        self._configuration = canonical_json(configuration)
        self._diagnostics: dict[str, Any] = {}

    def configuration(self) -> dict[str, Any]:
        value: dict[str, Any] = json.loads(self._configuration)
        return value

    def diagnostics(self) -> dict[str, Any]:
        return dict(self._diagnostics)

    async def complete_result(self, params: CompletionParams) -> LLMResponse | WorkerFailure:
        try:
            payload = self._build_payload(params)
            submission = {
                "task_type": "inference",
                "payload": payload,
                "requester": self._factory.requester,
                "model": self._factory.model,
                "machine": self._factory.machine,
                "timeout_seconds": self._factory.timeout_seconds,
                "max_retries": 0,
                "idempotency_key": self._idempotency_key,
            }
            response: httpx.Response | None = None
            for attempt in range(2):
                try:
                    response = await self._http.post(f"{self._dispatch_url}/jobs", json=submission)
                    break
                except httpx.TransportError:
                    if attempt == 1:
                        return WorkerFailure("SmithersTransportError", "Smithers submission failed")
            assert response is not None
            if response.status_code == 409:
                return WorkerFailure(
                    "IdempotencyConflictError", "Smithers rejected a changed keyed request"
                )
            response.raise_for_status()
            submitted = response.json()
            job_id = submitted.get("job_id")
            if not isinstance(job_id, str) or not job_id:
                return WorkerFailure("InvalidResponse", "Smithers omitted the job ID")
            while True:
                response = await self._http.get(f"{self._dispatch_url}/jobs/{job_id}")
                response.raise_for_status()
                job = response.json()
                if job.get("job_id") != job_id:
                    return WorkerFailure("IdentityMismatch", "Smithers changed the job ID")
                failure = self._identity_failure(job)
                if failure is not None:
                    return failure
                timing = self._timing(job)
                if isinstance(timing, WorkerFailure):
                    return timing
                if timing is not None:
                    self._diagnostics = timing
                    if timing["time_from_acceptance_seconds"] > self._factory.timeout_seconds:
                        return WorkerFailure(
                            "AcceptanceDeadlineExceeded", "worker acceptance budget expired"
                        )
                status = job.get("status")
                if status == "complete":
                    return self._completion(job, timing)
                if status in ("failed", "cancelled"):
                    return WorkerFailure("SmithersJobFailed", str(job.get("error") or status))
                if status not in ("queued", "waking_machine", "dispatched", "running"):
                    return WorkerFailure(
                        "InvalidResponse", "Smithers returned an unknown job status"
                    )
                await self._sleep()
        except (
            httpx.HTTPError, JigLLMError, ValueError, TypeError, KeyError, AttributeError
        ) as error:
            return WorkerFailure(type(error).__name__, f"Smithers response failed: {error}")

    async def _sleep(self) -> None:
        import asyncio

        await asyncio.sleep(self._factory.poll_interval)

    def _identity_failure(self, job: dict[str, Any]) -> WorkerFailure | None:
        if job.get("machine") != self._factory.machine:
            return WorkerFailure("MachineIdentityMismatch", "Smithers job machine changed")
        if job.get("model") != self._factory.model:
            return WorkerFailure("ModelIdentityMismatch", "Smithers job alias changed")
        try:
            digest, tag = _routing_identity(
                self._factory.routing_config, self._factory.model, self._factory.machine
            )
        except (OSError, ValueError, yaml.YAMLError):
            return WorkerFailure("ResolvedTagIdentityMismatch", "Smithers routing is unavailable")
        authorized = self.configuration()
        if (
            digest != authorized["routing_config_digest"]
            or tag != authorized["resolved_backend_tag"]
        ):
            return WorkerFailure("ResolvedTagIdentityMismatch", "Smithers resolved tag changed")
        if "resolved_backend_tag" in job and job["resolved_backend_tag"] != tag:
            return WorkerFailure("ResolvedTagIdentityMismatch", "Smithers job tag differs")
        result = job.get("result")
        if isinstance(result, dict) and "model" in result and result["model"] != tag:
            return WorkerFailure("ResolvedTagIdentityMismatch", "Smithers result model differs")
        return None

    def _timing(self, job: dict[str, Any]) -> dict[str, float] | WorkerFailure | None:
        created = datetime.fromisoformat(job["created_at"])
        started_raw = job.get("started_at")
        if started_raw is None:
            return None
        started = datetime.fromisoformat(started_raw)
        completed_raw = job.get("completed_at")
        completed = datetime.fromisoformat(completed_raw) if completed_raw else datetime.now(UTC)
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
        if started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
        if completed.tzinfo is None:
            completed = completed.replace(tzinfo=UTC)
        queue = (started - created).total_seconds()
        run = (completed - started).total_seconds()
        if queue < 0 or run < 0:
            return WorkerFailure("InvalidJobTiming", "Smithers job timestamps are inconsistent")
        return {"queue_latency_seconds": queue, "time_from_acceptance_seconds": run}

    def _completion(
        self, job: dict[str, Any], timing: dict[str, float] | None
    ) -> LLMResponse | WorkerFailure:
        if timing is None or job.get("completed_at") is None:
            return WorkerFailure("InvalidJobTiming", "completed Smithers job lacks timestamps")
        result = job.get("result")
        if not isinstance(result, dict) or not isinstance(result.get("content"), str):
            return WorkerFailure("InvalidResponse", "Smithers completion lacks content")
        usage = result.get("usage")
        usage = usage if isinstance(usage, dict) else {}
        return LLMResponse(
            content=result["content"],
            tool_calls=_parse_tool_calls(result.get("tool_calls")),
            usage=Usage(
                input_tokens=int(usage.get("input_tokens", 0)),
                output_tokens=int(usage.get("output_tokens", 0)),
            ),
            latency_ms=timing["time_from_acceptance_seconds"] * 1000,
            model=self.configuration()["resolved_backend_tag"],
        )

    async def complete(self, params: CompletionParams) -> LLMResponse:
        result = await self.complete_result(params)
        if isinstance(result, WorkerFailure):
            raise SmithersRequestError(result)
        return result
