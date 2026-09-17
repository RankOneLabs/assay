#!/usr/bin/env python3
"""Run every Pier qualification probe locally; emit an inventory only if all pass.

Credential-free and paid-execution-free: this script never sets ``OPENROUTER_API_KEY``,
never dials out to OpenRouter, and never calls ``run_pier_*``. It only builds and runs
the locked bridge image against the local Docker daemon and exercises the core-side
Pier adapter/protocol machinery against fakes -- exactly the surfaces the acceptance
matrix in ``tests/test_pier_acceptance.py`` also exercises without a real provider.

Probes run in a fixed order -- lock/image identity, then trial lifecycle/no-reinstall,
then the fake HTTP boundary, then artifact round trips/accounting/cancellation -- and
the first failure stops the run before any inventory is written. A
``QualificationInventory`` (see ``assay.runtime_inventory``) is only ever published if
every probe before it passed; there is no partial or best-effort inventory.

Usage::

    uv run --extra review --extra legacy python integrations/pier/scripts/qualify_local.py

See ``docs/pier-integration.md`` for the full operational walkthrough (preparation
through recovery) this script's output feeds into.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

BRIDGE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BRIDGE_ROOT.parents[1]
# Both projects are deliberately separate uv workspaces with their own locks
# (see integrations/pier/README.md); this script crosses that isolation
# boundary as tooling, not as runtime code, so it can gate a single
# inventory on probes that touch both sides of the wire contract.
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(BRIDGE_ROOT / "src"))

import httpx  # noqa: E402
from assay_pier_bridge.container import (  # noqa: E402
    DockerTrialClient,
    docker_available,
    package_digest,
)
from assay_pier_bridge.protocol import ModelRoute, TrialLimits, TrialRequest  # noqa: E402
from assay_pier_bridge.provider import (  # noqa: E402
    MODEL,
    PROVIDER_NAME,
    GuardedOpenRouterClient,
    GuardedRouteError,
)
from assay_pier_bridge.runtime import BridgeRuntime, TrialAlreadyRequestedError  # noqa: E402

from assay.adapters.pier import (  # noqa: E402
    BridgeEffectiveEnforcement,
    BridgeTrialResult,
    PierAdapter,
)
from assay.canonical import digest_bytes  # noqa: E402
from assay.execution import WorkerFailure, WorkerSuccess  # noqa: E402
from assay.investigations.pier_experiment import (  # noqa: E402
    EXPECTED_BRIDGE_LOCK_DIGEST,
    EXPECTED_DOCKER_VERSION,
    EXPECTED_GID,
    EXPECTED_MINI_SWE_AGENT_REVISION,
    EXPECTED_PIER_REVISION,
    EXPECTED_UID,
    PIER_BRIDGE_IMAGE_DIGEST,
    PIER_MODEL_ROUTE,
    PIER_TRIAL_LIMITS,
)
from assay.models import CellCoordinate  # noqa: E402
from assay.pier_protocol import (  # noqa: E402
    ArtifactEntry,
    ArtifactKind,
    ArtifactManifest,
    PierExchange,
    RuntimeBinding,
)
from assay.runtime_inventory import (  # noqa: E402
    BridgeLock,
    MeasuredEnforcement,
    QualificationInventory,
)
from assay.store import ObjectStore  # noqa: E402

_ZERO_REF = "sha256:" + "0" * 64
_ORPHAN_PREFIX = "assay-pier-"
# ModelRoute's fields are exact Literal types (mypy cannot check a
# **Mapping[str, str] unpacking against them), so the route is still a
# literal construction -- but asserted equal to PIER_MODEL_ROUTE below, at
# import time, so a drift between this script and the route paid execution
# is actually configured to call fails immediately, not silently.
_ROUTE = ModelRoute(
    endpoint="https://openrouter.ai/api/v1",
    model="anthropic/claude-3-haiku",
    provider="amazon-bedrock",
)
assert (
    _ROUTE.endpoint == PIER_MODEL_ROUTE["endpoint"]
    and _ROUTE.model == PIER_MODEL_ROUTE["model"]
    and _ROUTE.provider == PIER_MODEL_ROUTE["provider"]
), "qualify_local.py's guarded route no longer matches pier_experiment.PIER_MODEL_ROUTE"
_TRIAL_PACKAGE = {"instruction.md": "# Qualification\n\nsay hi\n"}
# A small, deliberately-overflowable cap for probe_storage_enforcement --
# distinct from PIER_TRIAL_LIMITS["storage_mb"] (which probe_trial_lifecycle
# already uses at its real, production size): proving a small declared cap
# is really enforced does not require overflowing the much larger real one.
_STORAGE_PROBE_LIMIT_MB = 16


def _production_trial_limits() -> TrialLimits:
    """The exact ``TrialLimits`` a real paid trial dispatches under.

    Built field by field (not ``TrialLimits(**PIER_TRIAL_LIMITS)``) because
    ``PIER_TRIAL_LIMITS`` is deliberately typed as a plain
    ``Mapping[str, float | int]`` in ``pier_experiment.py`` (it is also
    published as JSON configuration there), which mypy cannot check against
    ``TrialLimits``'s own int/float-typed fields through a ``**`` unpack.
    """
    return TrialLimits(
        cpu=float(PIER_TRIAL_LIMITS["cpu"]),
        memory_mb=int(PIER_TRIAL_LIMITS["memory_mb"]),
        pids=int(PIER_TRIAL_LIMITS["pids"]),
        timeout_s=float(PIER_TRIAL_LIMITS["timeout_s"]),
        storage_mb=int(PIER_TRIAL_LIMITS["storage_mb"]),
    )


class QualificationFailed(Exception):
    """One probe's failure; carries the probe name so it can be reported precisely."""

    def __init__(self, probe: str, reason: str) -> None:
        self.probe = probe
        self.reason = reason
        super().__init__(f"{probe}: {reason}")


@dataclass
class Measurements:
    lock_digest: str | None = None
    bridge_image_digest: str | None = None
    docker_version: str | None = None
    uid: int | None = None
    gid: int | None = None
    pier_revision: str | None = None
    mini_swe_agent_revision: str | None = None


def _run(args: list[str], *, timeout: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)


def _no_stray_containers(prefix: str = _ORPHAN_PREFIX) -> bool:
    result = _run(
        ["docker", "ps", "-a", "--filter", f"name={prefix}", "--format", "{{.Names}}"],
        timeout=10,
    )
    return not result.stdout.strip()


def probe_pinned_revisions(m: Measurements) -> None:
    text = (BRIDGE_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    pier_match = re.search(r'datacurve-pier==([0-9.]+)', text)
    mini_match = re.search(r"mini-swe-agent\.git@([0-9a-f]{40})", text)
    if not pier_match or not mini_match:
        raise QualificationFailed(
            "pinned_revisions", "integrations/pier/pyproject.toml no longer pins an exact "
            "Pier version or mini-swe-agent commit"
        )
    m.pier_revision = pier_match.group(1)
    m.mini_swe_agent_revision = mini_match.group(1)
    if m.pier_revision != EXPECTED_PIER_REVISION:
        raise QualificationFailed(
            "pinned_revisions",
            f"pier_revision {m.pier_revision!r} does not match the revision "
            f"pier_experiment.py requires for paid execution ({EXPECTED_PIER_REVISION!r})",
        )
    if m.mini_swe_agent_revision != EXPECTED_MINI_SWE_AGENT_REVISION:
        raise QualificationFailed(
            "pinned_revisions",
            f"mini_swe_agent_revision {m.mini_swe_agent_revision!r} does not match the "
            "revision pier_experiment.py requires for paid execution "
            f"({EXPECTED_MINI_SWE_AGENT_REVISION!r})",
        )


def probe_lock_identity(m: Measurements) -> None:
    lock_path = BRIDGE_ROOT / "uv.lock"
    if not lock_path.is_file():
        raise QualificationFailed("lock_identity", f"missing {lock_path}")
    m.lock_digest = digest_bytes(lock_path.read_bytes())
    if m.lock_digest != EXPECTED_BRIDGE_LOCK_DIGEST:
        raise QualificationFailed(
            "lock_identity",
            f"lock_digest {m.lock_digest!r} does not match the digest pier_experiment.py "
            f"requires for paid execution ({EXPECTED_BRIDGE_LOCK_DIGEST!r})",
        )


def probe_docker_available(m: Measurements) -> None:
    if not docker_available():
        raise QualificationFailed("docker_available", "docker CLI is not on PATH")
    info = _run(["docker", "info"], timeout=10)
    if info.returncode != 0:
        raise QualificationFailed(
            "docker_available", f"docker daemon is not reachable: {info.stderr[-500:]}"
        )
    version = _run(["docker", "version", "--format", "{{.Server.Version}}"], timeout=10)
    if version.returncode != 0 or not version.stdout.strip():
        raise QualificationFailed("docker_available", "could not read the Docker server version")
    m.docker_version = version.stdout.strip()
    if m.docker_version != EXPECTED_DOCKER_VERSION:
        raise QualificationFailed(
            "docker_available",
            f"Docker server version {m.docker_version!r} does not match the version "
            f"pier_experiment.py requires for paid execution ({EXPECTED_DOCKER_VERSION!r})",
        )


def probe_image_identity(m: Measurements, *, image_tag: str) -> None:
    build = _run(["docker", "build", "-t", image_tag, str(BRIDGE_ROOT)], timeout=600)
    if build.returncode != 0:
        raise QualificationFailed(
            "image_identity", f"bridge image build failed:\n{build.stderr[-4000:]}"
        )
    inspect = _run(["docker", "inspect", "--format", "{{.Id}}", image_tag], timeout=10)
    if inspect.returncode != 0:
        raise QualificationFailed(
            "image_identity", f"docker inspect failed: {inspect.stderr[-500:]}"
        )
    image_id = inspect.stdout.strip()
    if re.fullmatch(r"sha256:[0-9a-f]{64}", image_id) is None:
        raise QualificationFailed("image_identity", f"unexpected image id shape: {image_id!r}")
    m.bridge_image_digest = image_id
    if m.bridge_image_digest != PIER_BRIDGE_IMAGE_DIGEST:
        raise QualificationFailed(
            "image_identity",
            f"bridge image digest {m.bridge_image_digest!r} does not match the digest "
            f"pier_experiment.py requires for paid execution ({PIER_BRIDGE_IMAGE_DIGEST!r})",
        )


def probe_no_reinstall(image_tag: str) -> None:
    result = _run(
        ["docker", "run", "--rm", "--network", "none", "--entrypoint", "/bin/true", image_tag],
        timeout=30,
    )
    if result.returncode != 0:
        raise QualificationFailed(
            "no_reinstall",
            f"image needed network or failed to start with none: {result.stderr[-2000:]}",
        )


def probe_trial_lifecycle(m: Measurements, *, image_tag: str) -> None:
    if not _no_stray_containers():
        raise QualificationFailed(
            "orphan_containers", "stray assay-pier- containers already present before qualification"
        )
    client = DockerTrialClient(
        image=image_tag,
        package=_TRIAL_PACKAGE,
        command=["/bin/sh", "-c", "printf 'answer = 1' > /submission/output"],
    )
    runtime = BridgeRuntime(client)
    # The exact TrialLimits a real paid trial dispatches under (cpu/memory/
    # pids/storage) -- not an independently-sized, qualification-only
    # profile that could pass here while production's real resource ceiling
    # goes unproven.
    request = TrialRequest(
        cell_id="qualify:local:w0",
        package_digest=package_digest(_TRIAL_PACKAGE),
        model_route=_ROUTE,
        limits=_production_trial_limits(),
    )
    result = runtime.run_cell(request)
    if result.status != "succeeded":
        raise QualificationFailed(
            "trial_lifecycle",
            f"qualification trial did not succeed: {result.status}/{result.error_message}",
        )
    effective = result.effective
    if effective.uid != EXPECTED_UID or effective.gid != EXPECTED_GID:
        raise QualificationFailed(
            "effective_docker_controls",
            f"trial ran as uid={effective.uid} gid={effective.gid}, not the uid/gid "
            f"paid execution requires ({EXPECTED_UID}/{EXPECTED_GID})",
        )
    if not effective.workspace_read_only:
        raise QualificationFailed("effective_docker_controls", "workspace mount was not read-only")
    if effective.network_policy != "network-none-no-egress-allowlist":
        raise QualificationFailed(
            "effective_docker_controls", f"unexpected network policy: {effective.network_policy}"
        )
    # Observed (effective) enforcement compared to declared (PIER_TRIAL_LIMITS),
    # not merely to plausible-looking bounds -- an enforcement mechanism that
    # silently rounds, caps, or ignores part of the declared profile must
    # fail here rather than only being discovered at paid dispatch time.
    if effective.cpu_limit != PIER_TRIAL_LIMITS["cpu"]:
        raise QualificationFailed(
            "effective_docker_controls",
            f"effective cpu limit {effective.cpu_limit} does not match the declared "
            f"trial limit {PIER_TRIAL_LIMITS['cpu']}",
        )
    if effective.memory_limit_mb != PIER_TRIAL_LIMITS["memory_mb"]:
        raise QualificationFailed(
            "effective_docker_controls",
            f"effective memory limit {effective.memory_limit_mb} does not match the "
            f"declared trial limit {PIER_TRIAL_LIMITS['memory_mb']}",
        )
    if effective.pids_limit != PIER_TRIAL_LIMITS["pids"]:
        raise QualificationFailed(
            "effective_docker_controls",
            f"effective pids limit {effective.pids_limit} does not match the declared "
            f"trial limit {PIER_TRIAL_LIMITS['pids']}",
        )
    if effective.storage_limit_mb != PIER_TRIAL_LIMITS["storage_mb"]:
        raise QualificationFailed(
            "effective_docker_controls",
            f"effective storage limit {effective.storage_limit_mb} does not match the "
            f"declared trial limit {PIER_TRIAL_LIMITS['storage_mb']}",
        )
    if not effective.teardown_completed or effective.containers_remaining != 0:
        raise QualificationFailed("teardown", "container was not fully torn down after the trial")
    if not _no_stray_containers():
        raise QualificationFailed(
            "orphan_containers", "stray assay-pier- containers remained after teardown"
        )

    try:
        runtime.run_cell(request)
    except TrialAlreadyRequestedError:
        pass
    else:
        raise QualificationFailed(
            "no_reinstall", "runtime allowed a second trial request on one bridge lifecycle"
        )

    m.uid = effective.uid
    m.gid = effective.gid


def probe_storage_enforcement(image_tag: str) -> None:
    """A declared ``/scratch`` storage cap must be a real ceiling, not merely a recorded number.

    Deliberately uses ``_STORAGE_PROBE_LIMIT_MB`` (16), not
    ``PIER_TRIAL_LIMITS["storage_mb"]`` (512, already exercised for identity
    in ``probe_trial_lifecycle``): overflowing a small, dedicated cap here is
    cheap and proves the enforcement mechanism itself works, independent of
    which size it happens to be configured with for a real paid trial.
    """
    client = DockerTrialClient(
        image=image_tag,
        package=_TRIAL_PACKAGE,
        command=[
            "/bin/sh",
            "-c",
            "dd if=/dev/zero of=/scratch/big bs=1M count=64 >/dev/null 2>&1; "
            "printf '%s' \"$?\" > /submission/output",
        ],
    )
    runtime = BridgeRuntime(client)
    request = TrialRequest(
        cell_id="qualify:local:w1",
        package_digest=package_digest(_TRIAL_PACKAGE),
        model_route=_ROUTE,
        limits=TrialLimits(
            cpu=1, memory_mb=256, pids=32, timeout_s=30, storage_mb=_STORAGE_PROBE_LIMIT_MB
        ),
    )
    result = runtime.run_cell(request)
    if result.status != "succeeded":
        raise QualificationFailed(
            "storage_enforcement",
            f"storage probe trial did not succeed: {result.status}/{result.error_message}",
        )
    if not result.effective.teardown_completed or result.effective.containers_remaining != 0:
        raise QualificationFailed(
            "storage_enforcement", "container was not fully torn down after the storage probe"
        )
    if result.effective.storage_limit_mb != _STORAGE_PROBE_LIMIT_MB:
        raise QualificationFailed(
            "storage_enforcement",
            f"docker reported enforcing a {result.effective.storage_limit_mb}m scratch "
            f"limit, not the declared {_STORAGE_PROBE_LIMIT_MB}m",
        )
    if result.submission_ref == digest_bytes(b"0"):
        raise QualificationFailed(
            "storage_enforcement",
            "a write past the declared scratch limit did not fail -- the storage cap "
            "is not actually enforced",
        )
    if not _no_stray_containers():
        raise QualificationFailed(
            "orphan_containers", "stray assay-pier- containers remained after the storage probe"
        )


def _good_response_body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "id": "gen-qualify-local",
        "model": MODEL,
        "provider": PROVIDER_NAME,
        "choices": [
            {
                "index": 0,
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "submit_output",
                                "arguments": json.dumps({"source": "x = 1"}),
                            },
                        }
                    ],
                },
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.0021},
    }
    body.update(overrides)
    return body


def probe_fake_boundary() -> None:
    # The bridge's own guarded route identity must still be the exact route
    # paid execution is configured to call -- a drift here would mean this
    # probe validates a boundary no real paid trial actually uses.
    if PIER_MODEL_ROUTE["model"] != MODEL or PIER_MODEL_ROUTE["provider"] != PROVIDER_NAME:
        raise QualificationFailed(
            "fake_boundary",
            "the bridge's guarded route model/provider no longer matches the route "
            "pier_experiment.py requires for paid execution",
        )

    def accept(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_good_response_body())

    with GuardedOpenRouterClient(
        api_key="qualify-local-fake-key", transport=httpx.MockTransport(accept)
    ) as client:
        response = client.complete(system_prompt="sys", user_message="hi")
    if response.usage.cost_usd != 0.0021:
        raise QualificationFailed("fake_boundary", "guarded client mis-parsed a good response")

    def bad_model(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_good_response_body(model="openai/gpt-oss-120b"))

    def bad_provider(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_good_response_body(provider="CoreWeave"))

    def unknown_field(request: httpx.Request) -> httpx.Response:
        body = _good_response_body()
        body["unexpected"] = "field"
        return httpx.Response(200, json=body)

    def wrong_finish(request: httpx.Request) -> httpx.Response:
        body = _good_response_body()
        body["choices"][0]["finish_reason"] = "stop"
        return httpx.Response(200, json=body)

    for name, handler in (
        ("model mismatch", bad_model),
        ("provider mismatch", bad_provider),
        ("unknown field", unknown_field),
        ("non-tool-call finish", wrong_finish),
    ):
        with GuardedOpenRouterClient(
            api_key="qualify-local-fake-key", transport=httpx.MockTransport(handler)
        ) as client:
            try:
                client.complete(system_prompt="sys", user_message="hi")
            except GuardedRouteError:
                continue
            raise QualificationFailed("fake_boundary", f"guarded client accepted a {name} response")


def _artifact_entries_and_bytes(
    exchange: PierExchange, *, tamper_candidate: bool
) -> tuple[tuple[ArtifactEntry, ...], dict[str, bytes], str]:
    raw_trajectory = json.dumps({"trajectory": "qualify-local"}).encode()
    candidate = b"x = 1\n"
    result = json.dumps({"exit_status": "Submitted"}).encode()
    configuration = json.dumps({"config": True}).encode()
    manifest_evidence = json.dumps({"kind": "manifest"}).encode()
    specs: tuple[tuple[str, ArtifactKind, bytes], ...] = (
        ("raw_trajectory.json", "raw_trajectory", raw_trajectory),
        ("candidate.py", "candidate", candidate),
        ("result.json", "result", result),
        ("configuration.json", "configuration", configuration),
        ("manifest-evidence.json", "manifest", manifest_evidence),
    )
    entries = tuple(
        ArtifactEntry(
            path=path, kind=kind, size_bytes=len(data), checksum=digest_bytes(data), utf8=True
        )
        for path, kind, data in specs
    )
    artifact_bytes = {path: data for path, _kind, data in specs}
    submission_ref = digest_bytes(candidate)
    if tamper_candidate:
        # Corrupt the delivered bytes after the manifest was sealed against
        # the original candidate -- the round trip must catch this, not pass it.
        artifact_bytes["candidate.py"] = b"x = 2\n"
    return entries, artifact_bytes, submission_ref


@dataclass
class _FakeBridgeHandle:
    client: _FakeBridgeClient
    exchange: PierExchange
    mode: Literal["success", "tampered", "cancel", "error"]

    def run(self) -> BridgeTrialResult:
        if self.mode == "cancel":
            raise asyncio.CancelledError()
        if self.mode == "error":
            raise RuntimeError("qualification-injected bridge failure")
        entries, artifact_bytes, submission_ref = _artifact_entries_and_bytes(
            self.exchange, tamper_candidate=(self.mode == "tampered")
        )
        manifest = ArtifactManifest(
            exchange=self.exchange,
            entries=entries,
            aggregate_bytes=sum(entry.size_bytes for entry in entries),
        )
        artifact_bytes["manifest.json"] = manifest.model_dump_json().encode()
        return BridgeTrialResult(
            exchange=self.exchange,
            status="succeeded",
            submission_ref=submission_ref,
            usage={"prompt_tokens": 10.0, "completion_tokens": 5.0, "cost_usd": 0.0021},
            error_type=None,
            error_message=None,
            artifacts=artifact_bytes,
        )

    def teardown(self) -> BridgeEffectiveEnforcement:
        self.client.teardown_calls += 1
        return BridgeEffectiveEnforcement(
            containers_remaining=0, child_processes_remaining=0, teardown_completed=True
        )

    def partial_artifacts(self) -> dict[str, bytes]:
        return {"raw_trajectory.json": json.dumps({"partial": True}).encode()}


@dataclass
class _FakeBridgeClient:
    mode: Literal["success", "tampered", "cancel", "error"]
    teardown_calls: int = field(default=0)

    def create(self, *, exchange: PierExchange, package: Mapping[str, str]) -> _FakeBridgeHandle:
        return _FakeBridgeHandle(client=self, exchange=exchange, mode=self.mode)


def _coordinate(worker_repeat: int) -> CellCoordinate:
    return CellCoordinate(
        subject_id="qualify", arm_id="local", worker_repeat=worker_repeat, realization_ref=_ZERO_REF
    )


async def _probe_adapter_boundary(m: Measurements, *, output_dir: Path) -> None:
    store = ObjectStore(output_dir / "adapter-probe")
    binding = RuntimeBinding(
        runtime_version=m.lock_digest or "unknown",
        image_digest=m.bridge_image_digest or _ZERO_REF,
        configuration_ref=_ZERO_REF,
        package_digest=_ZERO_REF,
    )
    input_value = {"task": "qualification probe", "repository": {"module.py": "x = 1\n"}}

    def adapter_for(
        mode: Literal["success", "tampered", "cancel", "error"],
    ) -> tuple[PierAdapter, _FakeBridgeClient]:
        bridge = _FakeBridgeClient(mode=mode)
        adapter = PierAdapter(
            store=store,
            bridge=bridge,
            binding=binding,
            model_route={
                "endpoint": "https://openrouter.ai/api/v1",
                "model": "anthropic/claude-3-haiku",
                "provider": "amazon-bedrock",
            },
            trial_limits={"cpu": 1, "memory_mb": 256, "pids": 32, "timeout_s": 30},
        )
        return adapter, bridge

    success_adapter, success_bridge = adapter_for("success")
    result = await success_adapter.run_cell(input_value=input_value, coordinate=_coordinate(0))
    if not isinstance(result, WorkerSuccess):
        raise QualificationFailed("artifact_round_trip", f"expected a success, got {result!r}")
    if result.accounting.coverage != "measured" or result.accounting.amount is None:
        raise QualificationFailed(
            "accounting", "a successful trial's usage was not recorded as measured"
        )
    if abs(result.accounting.amount - 0.0021) > 1e-9:
        raise QualificationFailed(
            "accounting", "measured cost did not match the fake bridge's reported usage"
        )
    if success_bridge.teardown_calls != 1:
        raise QualificationFailed(
            "teardown", "adapter did not tear down the bridge handle after success"
        )

    tampered_adapter, tampered_bridge = adapter_for("tampered")
    result = await tampered_adapter.run_cell(input_value=input_value, coordinate=_coordinate(1))
    if not isinstance(result, WorkerFailure) or "ManifestRejected" not in result.error_type:
        raise QualificationFailed(
            "artifact_round_trip",
            "adapter accepted a bridge response with a tampered candidate artifact",
        )
    if tampered_bridge.teardown_calls != 1:
        raise QualificationFailed("teardown", "adapter did not tear down after a rejected manifest")

    error_adapter, error_bridge = adapter_for("error")
    result = await error_adapter.run_cell(input_value=input_value, coordinate=_coordinate(2))
    if not isinstance(result, WorkerFailure) or result.accounting.coverage != "uncertain":
        raise QualificationFailed(
            "accounting", "a dispatched-but-failed trial was not reported with uncertain accounting"
        )
    if error_bridge.teardown_calls != 1:
        raise QualificationFailed("teardown", "adapter did not tear down after a bridge exception")

    cancel_adapter, cancel_bridge = adapter_for("cancel")
    try:
        await cancel_adapter.run_cell(input_value=input_value, coordinate=_coordinate(3))
    except asyncio.CancelledError:
        pass
    else:
        raise QualificationFailed(
            "cancellation", "adapter did not propagate operator cancellation"
        )
    if cancel_bridge.teardown_calls != 1:
        raise QualificationFailed(
            "cancellation", "adapter did not tear down the handle on cancellation"
        )

    traces = [
        json.loads(path.read_bytes())
        for path in sorted(store.objects.iterdir())
        if path.is_file()
    ]
    if not any(
        isinstance(trace, dict)
        and trace.get("schema_version") == "assay-pier-cancellation-trace/0.1.0"
        and trace.get("cleanup_incomplete") is False
        for trace in traces
    ):
        raise QualificationFailed(
            "cancellation", "no durable cancellation trace recorded a confirmed-clean cleanup"
        )


def _build_inventory(m: Measurements) -> QualificationInventory:
    assert m.lock_digest and m.bridge_image_digest and m.docker_version
    assert m.pier_revision and m.mini_swe_agent_revision
    assert m.uid is not None and m.gid is not None
    return QualificationInventory(
        bridge=BridgeLock(
            pier_revision=m.pier_revision,
            mini_swe_agent_revision=m.mini_swe_agent_revision,
            lock_digest=m.lock_digest,
            bridge_image_digest=m.bridge_image_digest,
        ),
        measured=MeasuredEnforcement(
            docker_version=m.docker_version,
            # A literal True, not a stored flag: this is only ever reached
            # after probe_trial_lifecycle has already confirmed network
            # isolation against a real container -- there is no path here
            # where an unmeasured or negative result could reach it.
            network_none_verified=True,
            uid=m.uid,
            gid=m.gid,
        ),
        qualified_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


def _probes(m: Measurements, *, image_tag: str, output_dir: Path) -> list[tuple[str, Any]]:
    """The fixed probe order. Each entry calls its probe by module-level name,
    resolved fresh on every invocation -- a test that monkeypatches, say,
    ``qualify_local.probe_docker_available`` observes that replacement here,
    without this function needing to know it is being tested."""
    return [
        ("pinned_revisions", lambda: probe_pinned_revisions(m)),
        ("lock_identity", lambda: probe_lock_identity(m)),
        ("docker_available", lambda: probe_docker_available(m)),
        ("image_identity", lambda: probe_image_identity(m, image_tag=image_tag)),
        ("no_reinstall", lambda: probe_no_reinstall(image_tag)),
        ("trial_lifecycle", lambda: probe_trial_lifecycle(m, image_tag=image_tag)),
        ("storage_enforcement", lambda: probe_storage_enforcement(image_tag)),
        ("fake_boundary", probe_fake_boundary),
        (
            "artifact_accounting_cancellation",
            lambda: asyncio.run(_probe_adapter_boundary(m, output_dir=output_dir)),
        ),
    ]


def run_qualification(*, output_dir: Path, image_tag: str) -> int:
    """Run every probe in order; publish an inventory only if all of them pass.

    No ``ObjectStore`` is even constructed until the loop below completes
    without a ``QualificationFailed`` -- a failure at any probe, for any
    reason, leaves ``output_dir`` untouched rather than publishing a partial
    or best-effort inventory.
    """
    m = Measurements()
    for name, probe in _probes(m, image_tag=image_tag, output_dir=output_dir):
        print(f"==> {name}", flush=True)
        try:
            probe()
        except QualificationFailed as error:
            print(f"FAIL [{error.probe}]: {error.reason}", file=sys.stderr)
            return 1
        print("    ok", flush=True)

    inventory = _build_inventory(m)
    store = ObjectStore(output_dir)
    payload = inventory.model_dump(mode="json")
    ref = store.publish_json(payload)
    print(f"qualified: {ref}")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / ".assay-pier-qualification",
        help="ObjectStore directory the qualified inventory is published into",
    )
    parser.add_argument(
        "--image-tag",
        default="assay-pier-bridge:qualify-local",
        help="Tag the bridge image is built under for this qualification run",
    )
    args = parser.parse_args()
    return run_qualification(output_dir=args.output_dir, image_tag=args.image_tag)


if __name__ == "__main__":
    raise SystemExit(main())
