"""Real-container probes: success, failure, timeout, cancellation, teardown.

Skipped entirely if the ``docker`` CLI or daemon is unreachable from this
environment. Where it runs, every assertion is against a real container
started from the locked bridge image — not a fake — so a passing run is
direct evidence of the mount, uid, resource-limit, and teardown guarantees
in ``protocol.py``.
"""

from __future__ import annotations

import ipaddress
import json
import os
import socket
import socketserver
import subprocess
import threading
import time
from pathlib import Path
from typing import NoReturn

import pytest
from assay_pier_bridge.container import DockerTrialClient, docker_available, package_digest
from assay_pier_bridge.identity import digest_bytes
from assay_pier_bridge.protocol import ModelRoute, NetworkPolicy, TrialLimits, TrialRequest
from assay_pier_bridge.runtime import BridgeRuntime
from test_support import exchange_for

IMAGE_TAG = "assay-pier-bridge:test-lifecycle"
BRIDGE_ROOT = Path(__file__).parents[1]

ROUTE = ModelRoute(
    endpoint="https://openrouter.ai/api/v1",
    model="anthropic/claude-3-haiku",
    provider="amazon-bedrock",
)
PACKAGE = {"instruction.md": "# Task\n\nsay hi\n"}


def _request(
    *,
    timeout_s: float = 20,
    storage_mb: int = 64,
    network_policy: NetworkPolicy = "egress-openrouter-only",
    egress_host: str | None = None,
    egress_port: int | None = None,
) -> TrialRequest:
    return TrialRequest(
        cell_id="s1:a1:w0",
        package_digest=package_digest(PACKAGE),
        exchange=exchange_for("s1:a1:w0", package_digest(PACKAGE)),
        model_route=ROUTE,
        limits=TrialLimits(
            cpu=1, memory_mb=256, pids=32, timeout_s=timeout_s, storage_mb=storage_mb
        ),
        network_policy=network_policy,
        egress_host=egress_host,
        egress_port=egress_port,
    )


def _unsupported_host(reason: str) -> NoReturn:
    """Skip on a host that cannot run these trials, unless it is meant to.

    ``ASSAY_REQUIRE_DOCKER`` (set in CI) makes every such gap a failure, so a
    runner that loses Docker, sudo, or its LAN address goes red instead of
    quietly reporting a green suite that ran none of these tests.
    """
    if os.environ.get("ASSAY_REQUIRE_DOCKER"):
        pytest.fail(f"ASSAY_REQUIRE_DOCKER is set but {reason}")
    pytest.skip(reason)


@pytest.fixture(scope="module")
def image() -> str:
    if not docker_available():
        _unsupported_host("the docker CLI is not installed")
    # A daemon that errors or hangs is a fault, not a missing capability: fail
    # with its output rather than skip, which would report green.
    try:
        daemon_check = subprocess.run(
            ["docker", "info"], capture_output=True, text=True, timeout=30, check=False
        )
    except subprocess.TimeoutExpired:
        pytest.fail("`docker info` did not answer within 30 s")
    assert daemon_check.returncode == 0, (
        f"docker daemon is not reachable:\n{daemon_check.stderr[-2000:]}"
    )
    if os.geteuid() != 0:
        mount_check = subprocess.run(
            ["sudo", "-n", "true"], capture_output=True, text=True, timeout=10, check=False
        )
        if mount_check.returncode != 0:
            _unsupported_host(
                "the host lacks noninteractive loop-mount privileges for quota-backed trials"
            )
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


class _AnswerHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        self.request.sendall(b"allowed")


def _host_lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("192.0.2.1", 1))
            address = str(probe.getsockname()[0])
    except OSError as error:
        _unsupported_host(f"the host has no routable LAN address: {error}")
    private_lans = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
    if not any(ipaddress.IPv4Address(address) in ipaddress.ip_network(net) for net in private_lans):
        _unsupported_host(f"the host has no RFC1918 LAN address: {address}")
    return address


def test_lan_posture_reaches_only_the_allowlisted_host_and_port(image: str) -> None:
    host = _host_lan_ip()
    with (
        socketserver.ThreadingTCPServer(("0.0.0.0", 0), _AnswerHandler) as allowed_server,
        socketserver.ThreadingTCPServer(("0.0.0.0", 0), _AnswerHandler) as other_server,
    ):
        threading.Thread(target=allowed_server.serve_forever, daemon=True).start()
        threading.Thread(target=other_server.serve_forever, daemon=True).start()
        allowed_port = allowed_server.server_address[1]
        other_port = other_server.server_address[1]
        script = """
import json, socket, struct
host, allowed_port, other_port = __import__('sys').argv[1:]
with open('/proc/net/route', encoding='ascii') as routes:
    gateway = next(
        socket.inet_ntoa(struct.pack('<L', int(parts[2], 16)))
        for line in routes if (parts := line.split()) and parts[1] == '00000000'
    )
def reach(address, port):
    try:
        with socket.create_connection((address, int(port)), timeout=2) as peer:
            return peer.recv(32).decode('ascii')
    except OSError:
        return 'refused'
result = {
    'allowlisted': reach(host, allowed_port),
    'other_host': reach(gateway, allowed_port),
    'other_port': reach(host, other_port),
}
with open('/submission/output', 'w', encoding='utf-8') as output:
    json.dump(result, output)
"""
        client = DockerTrialClient(
            image=image,
            package=PACKAGE,
            command=["python", "-c", script, host, str(allowed_port), str(other_port)],
        )
        request = _request(
            network_policy="egress-lan-host-port", egress_host=host, egress_port=allowed_port
        )
        result = BridgeRuntime(client).run_cell(request)
    assert result.outcome.kind == "candidate", result.outcome
    assert json.loads(result.artifacts["output"]) == {
        "allowlisted": "allowed",
        "other_host": "refused",
        "other_port": "refused",
    }
    assert result.effective.network_policy == f"egress-lan-host-port:{host}:{allowed_port}"
    assert _no_stray_containers()


def test_workflow_toolchain_runs_offline_from_installed_tree(image: str) -> None:
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--entrypoint",
            "/bin/sh",
            image,
            "-c",
            "node --version && bun --version && tsc --version && "
            "test -f /opt/workflow_edit/node_modules/typescript/lib/typescript.js && "
            "! command -v npm",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["v22.21.1", "1.3.13", "Version 5.9.3"]


def test_success_leaves_a_read_only_mount_and_zero_containers(image: str) -> None:
    client = DockerTrialClient(
        image=image,
        package=PACKAGE,
        command=["/bin/sh", "-c", "printf 'answer = 1' > /submission/output"],
    )
    runtime = BridgeRuntime(client)

    result = runtime.run_cell(_request())

    assert result.outcome.kind == "candidate"
    assert result.outcome.patch_ref == digest_bytes(result.artifacts["candidate.patch"])
    assert result.effective.workspace_read_only is True
    assert result.effective.root_read_only is True
    assert result.effective.scratch_mount_kind == "bind"
    assert result.effective.scratch_quota_mb == 64
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
            "dd if=/dev/zero of=/scratch/big bs=1M count=64 >/dev/null; "
            'status=$?; printf \'%s\' "$status" > /submission/output; exit "$status"',
        ],
    )
    runtime = BridgeRuntime(client)

    result = runtime.run_cell(_request(storage_mb=16))

    assert result.outcome.kind == "candidate_failure"
    assert result.outcome.cause == "storage_exhausted"
    assert result.effective.storage_limit_mb == 16
    assert result.effective.memory_limit_mb == 256
    assert _no_stray_containers()


def test_memory_exhaustion_has_a_distinct_cause(image: str) -> None:
    client = DockerTrialClient(
        image=image,
        package=PACKAGE,
        command=[
            "/bin/sh",
            "-c",
            "exec python -c 'x = bytearray(512 * 1024 * 1024); "
            'x[::4096] = b"x" * (len(x) // 4096)\'',
        ],
    )
    result = BridgeRuntime(client).run_cell(_request())
    assert result.outcome.kind == "candidate_failure"
    assert result.outcome.cause == "memory_limit", result.outcome.detail
    assert result.effective.memory_limit_mb == 256
    assert result.effective.storage_limit_mb == 64
    assert _no_stray_containers()


def test_nonzero_exit_is_reported_as_failed_and_tears_down(image: str) -> None:
    client = DockerTrialClient(image=image, package=PACKAGE, command=["/bin/sh", "-c", "exit 7"])
    runtime = BridgeRuntime(client)

    result = runtime.run_cell(_request())

    assert result.outcome.kind == "candidate_failure"
    assert result.outcome.kind != "candidate"
    assert result.effective.containers_remaining == 0
    assert result.effective.teardown_completed is True
    assert _no_stray_containers()


def test_a_deadline_breach_is_reported_as_timeout_and_tears_down(image: str) -> None:
    client = DockerTrialClient(image=image, package=PACKAGE, command=["/bin/sh", "-c", "sleep 30"])
    runtime = BridgeRuntime(client)

    result = runtime.run_cell(_request(timeout_s=2))

    assert result.outcome.cause == "harness_deadline"
    assert result.effective.containers_remaining == 0
    assert result.effective.teardown_completed is True
    assert _no_stray_containers()


def test_operator_cancellation_stops_the_container_and_tears_down(image: str) -> None:
    client = DockerTrialClient(image=image, package=PACKAGE, command=["/bin/sh", "-c", "sleep 30"])
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

    assert result.outcome.cause == "cancelled"
    assert result.effective.containers_remaining == 0
    assert result.effective.teardown_completed is True
    assert _no_stray_containers()
