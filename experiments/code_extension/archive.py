"""Durable, content-addressed evidence for one ce-v1 attempt.

The writer is deliberately independent of dispatch. A caller opens a row at
durable dispatch and settles it from the core run manifest when available.
"""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from assay.canonical import canonical_json, digest_bytes
from assay.models import CellCoordinate, ExecutionOutcome, RunManifest
from assay.store import ObjectStore
from code_extension.dispatch import cell_idempotency_key
from code_extension.fixtures import ExtensionScenarioSidecar
from code_extension.protocol import (
    ORDERED_TOOL_SCHEMAS_SHA256,
    PROTOCOL_ID,
    PROTOCOL_VERSION,
    SUBMISSION_SCHEMA_SHA256,
    SYSTEM_PROMPT_SHA256,
)

DEFAULT_ARCHIVE_ROOT = Path(__file__).resolve().parent / "evidence" / "runs"
ARCHIVE_SCHEMA: Literal["assay-ce-attempt-archive/0.1.0"] = (
    "assay-ce-attempt-archive/0.1.0"
)
_SECRET_HEADER = re.compile(rb"(?i)(authorization|x-api-key|api[_-]key)\s*[:=]\s*[^\r\n,}\"]+")
_BEARER = re.compile(rb"(?i)bearer\s+[a-z0-9._~+/-]+")
_BASIC = re.compile(rb"(?i)\bbasic\s+[a-z0-9+/=]+")
_API_KEY = re.compile(rb"\b(?:sk-[a-zA-Z0-9_-]{8,}|gh[opurs]_[a-zA-Z0-9_]{8,})\b")
_SENSITIVE_KEYS = frozenset({
    "authorization", "x-api-key", "api_key", "api-key", "token", "access_token",
    "refresh_token", "session_token", "secret", "client_secret", "password",
    "credential", "credentials", "private_key",
})


class _Wire(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class CandidateEvidence(_Wire):
    patch_ref: str | None
    final_tree_digest: str | None
    baseline_tree_digest: str | None
    result_ref: str | None
    recoverable_workspace_ref: str | None


class PriceEvidence(_Wire):
    known_cost_usd: float | None
    unknown_cost: bool
    price_source: str | None
    price_date: str | None


class AttemptArchiveRecord(_Wire):
    schema_version: Literal["assay-ce-attempt-archive/0.1.0"]
    study_id: str
    protocol_id: str
    protocol_version: str
    cohort_id: str
    run_id: str
    cell_id: str
    scenario_id: str
    arm_id: str
    worker_repeat: int
    session_id: str
    idempotency_key: str
    schedule_seed: int | None
    schedule_order: int | None
    plan_ref: str
    snapshot_ref: str | None
    authorization_ref: str | None
    manifest_ref: str | None
    execution_ref: str | None
    code_revision: str
    dirty_source_digest: str | None
    fixture_ref: str | None
    configuration_ref: str
    prompt_ref: str | None
    request_ref: str | None
    prompt_digest: str | None
    system_prompt_digest: str
    tools_digest: str
    submission_digest: str
    scope_digest: str | None
    writable_scope: tuple[str, ...]
    protected_assets: dict[str, tuple[str, ...]] | None
    lockfile_digests: dict[str, str]
    image_digest: str | None
    grader_identity: str | None
    requested_model: str | None
    requested_profile: str | None
    actual_model: str | None
    actual_provider: str | None
    routing_digest: str | None
    requested_sampling: dict[str, float] | None
    provider_reported_sampling: dict[str, float] | None
    effective_bounds: dict[str, Any]
    started_at: str
    completed_at: str | None
    request_trace_ref: str | None
    response_trace_ref: str | None
    tool_trace_ref: str | None
    trajectory_ref: str | None
    worker_trace_ref: str | None
    request_ids: tuple[str, ...] | None
    errors: tuple[str, ...]
    token_usage: dict[str, int | None] | None
    price: PriceEvidence
    candidate: CandidateEvidence
    completion_status: str
    completion_cause: str | None
    evaluator_output_refs: tuple[str, ...]


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _source_revision() -> tuple[str, str | None]:
    root = Path(__file__).resolve().parents[2]
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True,
                          check=True).stdout.decode().strip()
    diff = subprocess.run(["git", "diff", "--binary", "HEAD"], cwd=root,
                          capture_output=True, check=True).stdout
    listed = subprocess.run(["git", "ls-files", "--others", "--exclude-standard", "-z"],
                            cwd=root, capture_output=True, check=True).stdout
    untracked = []
    for raw in listed.split(b"\0"):
        if not raw:
            continue
        name = raw.decode("utf-8")
        if set(Path(name).parts) & {"evidence", "results", "receipts"}:
            continue
        untracked.append(raw + b"\0" + digest_bytes((root / name).read_bytes()).encode())
    dirty = diff + b"\n" + b"\n".join(sorted(untracked))
    return head, digest_bytes(dirty) if diff or untracked else None


def _safe_bytes(data: bytes, secrets: tuple[bytes, ...]) -> bytes:
    try:
        parsed = json.loads(data)
    except (UnicodeDecodeError, ValueError):
        parsed = None
    if parsed is not None:
        def clean(value: Any) -> Any:
            if isinstance(value, dict):
                return {
                    ("redacted_header" if key.lower() in _SENSITIVE_KEYS else key): (
                        "[REDACTED]" if key.lower() in _SENSITIVE_KEYS else clean(item)
                    )
                    for key, item in value.items()
                }
            if isinstance(value, list):
                return [clean(item) for item in value]
            if isinstance(value, str):
                return _safe_text(value.encode(), secrets).decode("utf-8", errors="replace")
            return value
        return canonical_json(clean(parsed))
    return _safe_text(data, secrets)


def _safe_text(data: bytes, secrets: tuple[bytes, ...]) -> bytes:
    for secret in secrets:
        if secret:
            data = data.replace(secret, b"[REDACTED]")
    data = _SECRET_HEADER.sub(b"[REDACTED-HEADER]", data)
    data = _BEARER.sub(b"[REDACTED-BEARER]", data)
    data = _BASIC.sub(b"[REDACTED-BASIC]", data)
    return _API_KEY.sub(b"[REDACTED-API-KEY]", data)


def _atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".archive-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


class AttemptArchive:
    """One run directory; each index update is atomic and every blob immutable."""

    def __init__(self, run_id: str, root: Path = DEFAULT_ARCHIVE_ROOT,
                 *, secrets: tuple[str, ...] = ()) -> None:
        if not run_id or "/" in run_id or run_id in {".", ".."}:
            raise ValueError("invalid archive run id")
        if root == DEFAULT_ARCHIVE_ROOT and root.resolve().is_relative_to(
            Path(tempfile.gettempdir()).resolve()
        ):
            raise ValueError("default archive root must be durable storage outside OS temp")
        self.directory = root / run_id
        self.directory.mkdir(parents=True, exist_ok=False)
        (self.directory / "traces").mkdir()
        self.objects = ObjectStore(self.directory)
        self.secrets = tuple(value.encode() for value in secrets if value)
        self._index: dict[str, str] = {}
        self._write_index()

    @classmethod
    def open_existing(cls, run_id: str, root: Path = DEFAULT_ARCHIVE_ROOT,
                      *, secrets: tuple[str, ...] = ()) -> AttemptArchive:
        """Resume a partial run without replacing any already published object."""
        directory = root / run_id
        index = json.loads((directory / "index.json").read_bytes())
        if not isinstance(index, dict) or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in index.items()
        ):
            raise ValueError("invalid archive index")
        archive = object.__new__(cls)
        archive.directory = directory
        archive.objects = ObjectStore(directory)
        archive.secrets = tuple(value.encode() for value in secrets if value)
        archive._index = index
        for cell_id in index:
            archive.read(cell_id)
        return archive

    def _publish(self, data: bytes) -> str:
        return str(self.objects.publish_bytes(_safe_bytes(data, self.secrets)))

    def _publish_verbatim(self, data: bytes) -> str:
        """Retain an object another document names, without redacting it.

        Redaction rewrites a digest, and these objects are referred to by digest
        from the plan and the run manifest, so a redacted copy is unreachable.
        They are committed operator artifacts and accounting records rather than
        model-facing content: the snapshot, for one, carries the study's own
        forbidden-substring list, whose keys include the word 'credential'.
        """
        return str(self.objects.publish_bytes(data))

    def _record(self, record: AttemptArchiveRecord) -> str:
        data = _safe_bytes(canonical_json(record.model_dump(mode="json")), self.secrets)
        ref = self._publish(data)
        self._index[record.cell_id] = ref
        self._write_index()
        return ref

    def _write_index(self) -> None:
        _atomic(self.directory / "index.json", canonical_json(self._index))

    def read(self, cell_id: str) -> AttemptArchiveRecord:
        return AttemptArchiveRecord.model_validate_json(
            self.objects.read_bytes(self._index[cell_id])
        )

    def fail_attempt(self, cell_id: str, *, cause: str,
                     trace: bytes | None = None,
                     workspace_patch: bytes | None = None) -> AttemptArchiveRecord:
        """Persist an infrastructure failure even without a core manifest."""
        record = self.read(cell_id)
        values = record.model_dump(mode="python")
        trace_ref = self._publish(trace) if trace is not None else None
        candidate_redacted = (
            workspace_patch is not None and
            _safe_bytes(workspace_patch, self.secrets) != workspace_patch
        )
        patch_ref = self._publish(workspace_patch) if (
            workspace_patch is not None and not candidate_redacted
        ) else None
        if trace is not None:
            _atomic(self.directory / "traces" / f"{cell_id}-worker.json",
                    _safe_bytes(trace, self.secrets))
        values["worker_trace_ref"] = trace_ref
        values["candidate"] = CandidateEvidence(
            patch_ref=patch_ref, final_tree_digest=None, baseline_tree_digest=None,
            result_ref=None, recoverable_workspace_ref=patch_ref,
        )
        values["errors"] = (*record.errors, cause, *(
            ("CandidateRedacted: candidate patch contained a credential",)
            if candidate_redacted else ()
        ), *(
            ("CandidateUnavailable: no patch or recoverable workspace",)
            if patch_ref is None else ()
        ))
        values["completion_status"] = "failed"
        values["completion_cause"] = cause
        values["completed_at"] = _now()
        failed = AttemptArchiveRecord.model_validate(values)
        self._record(failed)
        return failed

    def begin_attempt(
        self, *, coordinate: CellCoordinate, plan_ref: str, snapshot_ref: str | None,
        authorization_ref: str | None, configuration: dict[str, Any],
        sidecar: ExtensionScenarioSidecar | None, source: ObjectStore,
        fixture_ref: str | None = None,
        schedule_seed: int | None = None, schedule_order: int | None = None,
        grader_identity: str | None = None, routing_digest: str | None = None,
        cohort_id: str = "extension_worker_and_archive",
    ) -> AttemptArchiveRecord:
        revision, dirty = _source_revision()
        scope = tuple(sidecar.writable_implementation_scope) if sidecar else tuple(
            configuration["writable_prefixes"]
        )
        protected = (
            {key: tuple(value) for key, value in sidecar.protected_assets.model_dump().items()}
            if sidecar else None
        )
        route = configuration.get("model_route") or {}
        for ref in (plan_ref, snapshot_ref, authorization_ref, fixture_ref):
            if ref is not None and self._publish_verbatim(source.read_bytes(ref)) != ref:
                raise ValueError("an authorization input does not match its digest")
        prompt = configuration.get("arm_prompt")
        record = AttemptArchiveRecord(
            schema_version=ARCHIVE_SCHEMA, study_id="code_extension", protocol_id=PROTOCOL_ID,
            protocol_version=PROTOCOL_VERSION, cohort_id=cohort_id,
            run_id=self.directory.name, cell_id=coordinate.id,
            scenario_id=coordinate.subject_id, arm_id=coordinate.arm_id,
            worker_repeat=coordinate.worker_repeat, session_id=uuid.uuid4().hex,
            idempotency_key=cell_idempotency_key(self.directory.name, coordinate),
            schedule_seed=schedule_seed,
            schedule_order=schedule_order, plan_ref=plan_ref, snapshot_ref=snapshot_ref,
            authorization_ref=authorization_ref, manifest_ref=None, execution_ref=None,
            code_revision=revision, dirty_source_digest=dirty, fixture_ref=fixture_ref,
            configuration_ref=self._publish(canonical_json(configuration)),
            prompt_ref=self._publish(str(prompt).encode()) if prompt is not None else None,
            request_ref=None, prompt_digest=digest_bytes(
                str(prompt).encode()
            ) if prompt is not None else None,
            system_prompt_digest=str(configuration.get("system_prompt_sha256")
                                     or SYSTEM_PROMPT_SHA256),
            tools_digest=str(configuration.get("tools_sha256")
                             or ORDERED_TOOL_SCHEMAS_SHA256),
            submission_digest=SUBMISSION_SCHEMA_SHA256,
            scope_digest=digest_bytes(canonical_json({
                "scope": list(scope),
                "protected_assets": {key: list(value) for key, value in protected.items()}
                if protected else None,
            })),
            writable_scope=scope, protected_assets=protected,
            lockfile_digests=dict(sidecar.provenance.dependency_lock_digests)
            if sidecar else {}, image_digest=configuration.get("image_digest"),
            grader_identity=grader_identity, requested_model=route.get("model"),
            requested_profile=configuration.get("model_profile"), actual_model=None,
            actual_provider=None, routing_digest=routing_digest,
            requested_sampling=configuration.get("requested_sampling"),
            provider_reported_sampling=configuration.get("provider_reported_sampling"),
            effective_bounds={**configuration.get("bounds", {}), **{
                key: configuration.get(key) for key in (
                    "timeout_s", "model_context_limit_tokens", "request_timeout_s",
                    "per_cell_tool_call_ceiling", "per_cell_tool_call_ceiling_reason",
                )}}, started_at=_now(), completed_at=None, request_trace_ref=None,
            response_trace_ref=None, tool_trace_ref=None, trajectory_ref=None,
            worker_trace_ref=None, request_ids=None, errors=(), token_usage=None,
            price=PriceEvidence(known_cost_usd=None, unknown_cost=True,
                                price_source=None, price_date=None),
            candidate=CandidateEvidence(patch_ref=None, final_tree_digest=None,
                                        baseline_tree_digest=None, result_ref=None,
                                        recoverable_workspace_ref=None),
            completion_status="dispatched", completion_cause=None,
            evaluator_output_refs=(),
        )
        self._record(record)
        return record

    def _copy_evaluation(self, source: ObjectStore, ref: str) -> str:
        """Retain the evaluator record and the detail and grader output it names."""
        evidence = json.loads(source.read_bytes(ref))
        payload = evidence.get("payload", {})
        replacements: dict[str, str] = {}
        for detail_ref in payload.get("detail_refs", []):
            detail = json.loads(source.read_bytes(detail_ref))
            grader_ref = detail.get("evaluator_record_ref")
            if grader_ref is not None:
                copied_grader = self._publish(source.read_bytes(grader_ref))
                detail["evaluator_record_ref"] = copied_grader
            replacements[detail_ref] = self._publish(canonical_json(detail))
        payload["detail_refs"] = [
            replacements[ref] for ref in payload.get("detail_refs", [])
        ]
        if "source_references" in evidence:
            evidence["source_references"] = [
                replacements.get(source_ref, source_ref)
                for source_ref in evidence["source_references"]
            ]
        return self._publish(canonical_json(evidence))

    def _copy_operating(self, source: ObjectStore, ref: str) -> None:
        """Retain the operating record and the accounting provenance it names.

        The ledger reads both to fill an attempt's accounting, so an archive
        that omits them cannot be reported on even though it holds the manifest
        that names them.
        """
        raw = source.read_bytes(ref)
        self._publish_verbatim(raw)
        for provenance in json.loads(raw).get("source_references", []):
            self._publish_verbatim(source.read_bytes(provenance))

    def settle_attempt(self, cell_id: str, *, source: ObjectStore,
                       manifest_ref: str | None = None,
                       interruption: str | None = None) -> AttemptArchiveRecord:
        """Retain all available evidence, including a failed or interrupted cell."""
        record = self.read(cell_id)
        values = record.model_dump(mode="python")
        manifest: RunManifest | None = None
        outcome: ExecutionOutcome | None = None
        if manifest_ref is not None:
            manifest_bytes = source.read_bytes(manifest_ref)
            manifest = RunManifest.model_validate_json(manifest_bytes)
            _atomic(self.directory / "manifest.json", _safe_bytes(manifest_bytes, self.secrets))
            values["manifest_ref"] = self._publish(manifest_bytes)
            execution_ref = manifest.execution_records.get(cell_id)
            if execution_ref is not None:
                values["execution_ref"] = self._publish(source.read_bytes(execution_ref))
                outcome = ExecutionOutcome.model_validate_json(source.read_bytes(execution_ref))
            values["evaluator_output_refs"] = tuple(
                self._copy_evaluation(source, ref) for key, ref in
                manifest.evaluation_records.items() if key.startswith(cell_id + ":")
            )
            operating_ref = manifest.operating_records.get(f"worker:{cell_id}")
            if operating_ref is not None:
                self._copy_operating(source, operating_ref)
        trace_ref = outcome.trace_ref if outcome else (
            manifest.interruption_ref if manifest else None
        )
        trace: dict[str, Any] = {}
        if trace_ref is not None:
            raw_trace = source.read_bytes(trace_ref)
            values["worker_trace_ref"] = self._publish(raw_trace)
            _atomic(self.directory / "traces" / f"{cell_id}-worker.json",
                    _safe_bytes(raw_trace, self.secrets))
            trace = json.loads(raw_trace)
        output = json.loads(source.read_bytes(outcome.output_ref)) if (
            outcome and outcome.output_ref
        ) else {}
        artifact_refs = trace.get("artifact_refs", {})

        def artifact(ref: str | None) -> tuple[str | None, bytes | None]:
            if ref is None:
                return None, None
            envelope = json.loads(source.read_bytes(ref))
            raw = base64.b64decode(envelope["content_base64"], validate=True)
            return self._publish(raw), raw

        patch_ref, patch = artifact(output.get("patch_ref") or
                                    artifact_refs.get("candidate.patch") or
                                    artifact_refs.get("stopped/candidate.patch"))
        candidate_redacted = patch is not None and patch_ref != digest_bytes(patch)
        if candidate_redacted:
            patch_ref = None
            patch = None
        result_ref, result_bytes = artifact(output.get("result_ref") or
                                            artifact_refs.get("result.json"))
        trajectory_ref, trajectory_bytes = artifact(output.get("raw_trajectory_ref") or
                                                  artifact_refs.get("trajectory.json") or
                                                  artifact_refs.get("stopped/trajectory.json"))
        result = json.loads(result_bytes) if result_bytes else {}
        trajectory = json.loads(trajectory_bytes) if trajectory_bytes else {}
        if trajectory_bytes is not None:
            _atomic(self.directory / "traces" / f"{cell_id}-trajectory.json",
                    _safe_bytes(trajectory_bytes, self.secrets))
        turns = trajectory.get("turns", [])
        values["trajectory_ref"] = trajectory_ref
        values["request_trace_ref"] = self._publish(canonical_json(
            trajectory.get("messages", []))) if trajectory_bytes else None
        values["response_trace_ref"] = self._publish(canonical_json(turns)) if turns else None
        values["tool_trace_ref"] = self._publish(canonical_json([
            call for turn in turns for call in turn.get("tool_calls", [])
        ])) if turns else None
        requests = [event for event in trajectory.get("events", [])
                    if event.get("kind") == "model_request"]
        ids = [str(value) for event in requests for value in (
            event.get("observations", {}).get("smithers_job_id"),
            event.get("generation_id"),
        ) if value]
        ids.extend(str(turn["request_id"]) for turn in turns if turn.get("request_id"))
        values["request_ids"] = tuple(ids) if ids else None
        usage = trajectory.get("actual_usage")
        values["token_usage"] = {key: usage.get(key) for key in (
            "prompt_tokens", "completion_tokens", "requests", "tool_calls",
        )} if usage else None
        cost = usage.get("cost_usd") if usage else None
        values["price"] = PriceEvidence(
            known_cost_usd=cost, unknown_cost=cost is None,
            price_source=None, price_date=None,
        )
        values["actual_model"] = (result.get("actual_model") or next((
            event.get("observations", {}).get("worker_model") for event in requests
            if event.get("observations", {}).get("worker_model")
        ), None))
        values["actual_provider"] = result.get("actual_provider")
        transcript = output.get("transcript_ref")
        values["request_ref"] = self._publish(source.read_bytes(transcript)) if transcript else None
        values["candidate"] = CandidateEvidence(
            patch_ref=patch_ref, final_tree_digest=result.get("tree_digest"),
            baseline_tree_digest=result.get("baseline_tree_digest"), result_ref=result_ref,
            recoverable_workspace_ref=patch_ref if patch is not None else None,
        )
        errors = list(record.errors)
        if outcome and outcome.error_type:
            errors.append(f"{outcome.error_type}: {outcome.error_message}")
        if interruption:
            errors.append(interruption)
        if candidate_redacted:
            errors.append("CandidateRedacted: candidate patch contained a credential")
        unavailable = patch is None
        if unavailable:
            errors.append("CandidateUnavailable: no patch or recoverable workspace")
        values["errors"] = tuple(errors)
        stop = next((event.get("cause") for event in reversed(trajectory.get("events", []))
                     if event.get("kind") == "stopped"), None)
        values["completion_status"] = (
            "succeeded" if outcome and outcome.status == "succeeded" and not unavailable else
            "interrupted" if interruption else "failed"
        )
        values["completion_cause"] = stop or interruption or (
            outcome.error_type if outcome else "CandidateUnavailable"
        )
        values["completed_at"] = _now()
        settled = AttemptArchiveRecord.model_validate(values)
        self._record(settled)
        return settled
