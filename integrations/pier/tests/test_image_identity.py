from __future__ import annotations

import subprocess

import pytest
from assay_pier_bridge.identity import (
    ImageDigestMismatchError,
    ImageInspectionError,
    bind_bridge_identity,
)

_DIGEST = "sha256:" + "a" * 64


def _manifest(**overrides: object) -> dict[str, object]:
    manifest: dict[str, object] = {
        "pier_revision": "0.3.1",
        "mini_swe_agent_revision": "a83fcae",
        "lock_digest": "sha256:" + "b" * 64,
    }
    manifest.update(overrides)
    return manifest


def test_identity_binds_inspected_digest(monkeypatch: pytest.MonkeyPatch) -> None:
    def inspect(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert args == ["docker", "image", "inspect", "--format", "{{.Id}}", "bridge:test"]
        assert kwargs["timeout"] == 10
        return subprocess.CompletedProcess(args, 0, stdout=f"{_DIGEST}\n", stderr="")

    monkeypatch.setattr(subprocess, "run", inspect)
    identity = bind_bridge_identity(_manifest(), "bridge:test")
    assert identity.bridge_image_digest == _DIGEST
    assert bind_bridge_identity(_manifest(bridge_image_digest=_DIGEST), "bridge:test") == identity


def test_identity_rejects_stale_manifest_digest(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda args, **kwargs: subprocess.CompletedProcess(args, 0, stdout=_DIGEST, stderr=""),
    )
    with pytest.raises(ImageDigestMismatchError, match="bridge_image_digest"):
        bind_bridge_identity(_manifest(bridge_image_digest="sha256:" + "c" * 64), "bridge:test")


def test_identity_requires_successful_inspection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda args, **kwargs: subprocess.CompletedProcess(args, 1, stdout="", stderr="not found"),
    )
    with pytest.raises(ImageInspectionError, match="cannot read a sha256 image digest"):
        bind_bridge_identity(_manifest(bridge_image_digest=_DIGEST), "missing:test")
