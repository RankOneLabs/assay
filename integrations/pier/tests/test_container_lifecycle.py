"""Real-container probes: success, failure, timeout, cancellation, teardown.

Skipped entirely if the ``docker`` CLI or daemon is unreachable from this
environment. Where it runs, every assertion is against a real container
started from the locked bridge image — not a fake — so a passing run is
direct evidence of the mount, uid, resource-limit, and teardown guarantees
in ``protocol.py``.
"""

from __future__ import annotations

import hashlib
import subprocess
import threading
import time
from pathlib import Path

import pytest
from assay_pier_bridge.container import DockerTrialClient, docker_available, package_digest
from assay_pier_bridge.protocol import ModelRoute, TrialLimits, TrialRequest
from assay_pier_bridge.runtime import BridgeRuntime

IMAGE_TAG = "assay-pier-bridge:test-lifecycle"
BRIDGE_ROOT = Path(__file__).parents[1]

ROUTE = ModelRoute(
    endpoint="https://openrouter.ai/api/v1",
    model="anthropic/claude-3-haiku",
    provider="amazon-bedrock",
)
PACKAGE = {"instruction.md": "# Task\n\nsay hi\n"}


def _request(*, timeout_s: float = 20, storage_mb: int = 64) -> TrialRequest:
    return TrialRequest(
        cell_id="s1:a1:w0",
        package_digest=package_digest(PACKAGE),
        model_route=ROUTE,
        limits=TrialLimits(
            cpu=1, memory_mb=256, pids=32, timeout_s=timeout_s, storage_mb=storage_mb
        ),
    )


@pytest.fixture(scope="module")
def image() -> str:
    if not docker_available():
        pytest.skip("docker CLI is not available in this environment")
    daemon_check = subprocess.run(
        ["docker", "info"], capture_output=True, text=True, timeout=10, check=False
    )
    if daemon_check.returncode != 0:
        pytest.skip(f"docker daemon is not reachable: {daemon_check.stderr[-500:]}")
    result = subprocess.run(
        ["docker", "build", "-t", IMAGE_TAG, str(BRIDGE_ROOT)],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, f"bridge image build failed:\n{result.stderr[-4000:]}"
    return IMAGE_TAG


def _no_stray_containers(prefix: str = "assay-pier-") -> bool:
    result = subprocess.run(
        ["docker", "ps", "-a", "--filter", f"name={prefix}", "--format", "{{.Names}}"],
        capture_output=True,
        text=True,
        check=False,
    )
    return not result.stdout.strip()


def test_success_leaves_a_read_only_mount_and_zero_containers(image: str) -> None:
    client = DockerTrialClient(
        image=image,
        package=PACKAGE,
        command=["/bin/sh", "-c", "printf 'answer = 1' > /submission/output"],
    )
    runtime = BridgeRuntime(client)

    result = runtime.run_cell(_request())

    assert result.status == "succeeded"
    assert result.submission_ref is not None
    assert result.effective.workspace_read_only is True
    assert result.effective.uid == 1000
    assert result.effective.storage_limit_mb == 64
    assert result.effective.containers_remaining == 0
    assert result.effective.child_processes_remaining == 0
    assert result.effective.teardown_completed is True
    assert _no_stray_containers()


def test_scratch_storage_limit_is_really_enforced_not_merely_declared(image: str) -> None:
    """A declared ``storage_mb`` that a trial could silently exceed would be
    worse than no limit at all -- a caller reading ``storage_limit_mb`` off
    the result needs it to mean a real ``/scratch`` cannot grow past it."""
    client = DockerTrialClient(
        image=image,
        package=PACKAGE,
        command=[
            "/bin/sh",
            "-c",
            "dd if=/dev/zero of=/scratch/big bs=1M count=64 >/dev/null 2>&1; "
            "printf '%s' \"$?\" > /submission/output",
        ],
    )
    runtime = BridgeRuntime(client)

    result = runtime.run_cell(_request(storage_mb=16))

    assert result.status == "succeeded"
    assert result.effective.storage_limit_mb == 16
    submission = result.submission_ref
    assert submission is not None
    # dd's own exit code (nonzero) is the trial's submission content -- a
    # write past the declared 16 MiB tmpfs must fail with ENOSPC, not
    # silently succeed past the ceiling this result claims was enforced.
    assert submission != f"sha256:{hashlib.sha256(b'0').hexdigest()}"
    assert _no_stray_containers()


def test_nonzero_exit_is_reported_as_failed_and_tears_down(image: str) -> None:
    client = DockerTrialClient(
        image=image, package=PACKAGE, command=["/bin/sh", "-c", "exit 7"]
    )
    runtime = BridgeRuntime(client)

    result = runtime.run_cell(_request())

    assert result.status == "failed"
    assert result.submission_ref is None
    assert result.effective.containers_remaining == 0
    assert result.effective.teardown_completed is True
    assert _no_stray_containers()


def test_a_deadline_breach_is_reported_as_timeout_and_tears_down(image: str) -> None:
    client = DockerTrialClient(
        image=image, package=PACKAGE, command=["/bin/sh", "-c", "sleep 30"]
    )
    runtime = BridgeRuntime(client)

    result = runtime.run_cell(_request(timeout_s=2))

    assert result.status == "timeout"
    assert result.effective.containers_remaining == 0
    assert result.effective.teardown_completed is True
    assert _no_stray_containers()


def test_operator_cancellation_stops_the_container_and_tears_down(image: str) -> None:
    client = DockerTrialClient(
        image=image, package=PACKAGE, command=["/bin/sh", "-c", "sleep 30"]
    )
    handle = client.create(_request())

    def _cancel_soon() -> None:
        time.sleep(1.0)
        handle.cancel()

    threading.Thread(target=_cancel_soon, daemon=True).start()

    class _PrecreatedClient:
        def create(self, request: TrialRequest) -> object:
            return handle

    runtime = BridgeRuntime(_PrecreatedClient())  # type: ignore[arg-type]
    result = runtime.run_cell(_request())

    assert result.status == "cancelled"
    assert result.effective.containers_remaining == 0
    assert result.effective.teardown_completed is True
    assert _no_stray_containers()
