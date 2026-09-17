from __future__ import annotations

import builtins
import json
import socket
import subprocess
from pathlib import Path

import pytest

from assay.canonical import canonical_json, digest_bytes
from assay.investigations.pier_experiment import (
    EXPECTED_BRIDGE_LOCK_DIGEST,
    EXPECTED_DOCKER_VERSION,
    EXPECTED_MINI_SWE_AGENT_REVISION,
    EXPECTED_PIER_REVISION,
    PIER_BRIDGE_IMAGE_DIGEST,
    PierExperimentFailed,
    PierExperimentPrepared,
    prepare_pier_smoke,
)
from assay.runtime_inventory import (
    QualificationInventory,
    QualificationRejected,
    load_qualification_inventory,
    runtime_binding_from_inventory,
)
from assay.store import ObjectStore


def _inventory_value(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": "assay-pier-qualification/0.1.0",
        "bridge": {
            "pier_revision": "0.3.1",
            "mini_swe_agent_revision": "a83fcae82d2a08f0ee0c688f9d137b3566c097f8",
            "lock_digest": "sha256:" + "1" * 64,
            "bridge_image_digest": "sha256:" + "2" * 64,
        },
        "measured": {
            "docker_version": "27.3.1",
            "network_none_verified": True,
            "uid": 1000,
            "gid": 1000,
        },
        "qualified_at": "2026-09-11T00:00:00Z",
        "outcome": "succeeded",
    }
    value.update(overrides)
    return value


def _publish_inventory(store: ObjectStore, value: dict[str, object]) -> str:
    return str(store.publish_json(value))


def test_load_qualification_inventory_accepts_a_valid_recorded_inventory(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path / ".assay")
    ref = _publish_inventory(store, _inventory_value())
    result = load_qualification_inventory(store, inventory_ref=ref)
    assert isinstance(result, QualificationInventory)
    assert result.bridge.lock_digest == "sha256:" + "1" * 64


def test_load_qualification_inventory_fails_closed_on_missing_object(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path / ".assay")
    result = load_qualification_inventory(store, inventory_ref="sha256:" + "9" * 64)
    assert isinstance(result, QualificationRejected)


def test_load_qualification_inventory_fails_closed_on_incomplete_shape(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path / ".assay")
    value = _inventory_value()
    del value["measured"]  # type: ignore[arg-type]
    ref = _publish_inventory(store, value)
    result = load_qualification_inventory(store, inventory_ref=ref)
    assert isinstance(result, QualificationRejected)


def test_load_qualification_inventory_fails_closed_on_stale_network_claim(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path / ".assay")
    value = _inventory_value()
    value["measured"] = {**value["measured"], "network_none_verified": False}  # type: ignore[dict-item]
    ref = _publish_inventory(store, value)
    result = load_qualification_inventory(store, inventory_ref=ref)
    assert isinstance(result, QualificationRejected)


def test_load_qualification_inventory_fails_closed_on_mismatched_digest(tmp_path: Path) -> None:
    """A caller quoting a wrong ref for otherwise-valid bytes must not silently accept it."""
    store = ObjectStore(tmp_path / ".assay")
    _publish_inventory(store, _inventory_value())
    other_ref = str(store.publish_json({"unrelated": True}))
    result = load_qualification_inventory(store, inventory_ref=other_ref)
    assert isinstance(result, QualificationRejected)


def test_load_qualification_inventory_fails_closed_on_noncanonical_bytes(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path / ".assay")
    raw = canonical_json(_inventory_value())
    padded = raw + b" "
    ref = digest_bytes(padded)
    store.objects.mkdir(parents=True, exist_ok=True)
    (store.objects / ref.removeprefix("sha256:")).write_bytes(padded)
    result = load_qualification_inventory(store, inventory_ref=ref)
    assert isinstance(result, QualificationRejected)


def test_runtime_binding_from_inventory_projects_bridge_lock(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path / ".assay")
    ref = _publish_inventory(store, _inventory_value())
    inventory = load_qualification_inventory(store, inventory_ref=ref)
    assert isinstance(inventory, QualificationInventory)
    binding = runtime_binding_from_inventory(
        inventory,
        configuration_ref="sha256:" + "3" * 64,
        package_digest="sha256:" + "4" * 64,
    )
    assert binding.runtime_version == inventory.bridge.lock_digest
    assert binding.image_digest == inventory.bridge.bridge_image_digest
    assert binding.configuration_ref == "sha256:" + "3" * 64
    assert binding.package_digest == "sha256:" + "4" * 64


def test_prepare_never_opens_a_socket(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def _forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("preparation must never open a network socket")

    monkeypatch.setattr(socket, "socket", _forbidden)
    store = ObjectStore(tmp_path / ".assay")
    ref = _publish_inventory(store, _inventory_value())
    result = load_qualification_inventory(store, inventory_ref=ref)
    assert isinstance(result, QualificationInventory)


def test_prepare_never_spawns_a_subprocess(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def _forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("preparation must never launch a subprocess (e.g. docker)")

    monkeypatch.setattr(subprocess, "Popen", _forbidden)
    monkeypatch.setattr(subprocess, "run", _forbidden)
    store = ObjectStore(tmp_path / ".assay")
    ref = _publish_inventory(store, _inventory_value())
    result = load_qualification_inventory(store, inventory_ref=ref)
    assert isinstance(result, QualificationInventory)
    binding = runtime_binding_from_inventory(
        result, configuration_ref="sha256:" + "3" * 64, package_digest="sha256:" + "4" * 64
    )
    assert binding.runtime_id == "pier"


def _qualified_inventory_value(**overrides: object) -> dict[str, object]:
    """A qualification matching every EXPECTED_* constant pier_experiment pins."""
    value: dict[str, object] = {
        "schema_version": "assay-pier-qualification/0.1.0",
        "bridge": {
            "pier_revision": EXPECTED_PIER_REVISION,
            "mini_swe_agent_revision": EXPECTED_MINI_SWE_AGENT_REVISION,
            "lock_digest": EXPECTED_BRIDGE_LOCK_DIGEST,
            "bridge_image_digest": PIER_BRIDGE_IMAGE_DIGEST,
        },
        "measured": {
            "docker_version": EXPECTED_DOCKER_VERSION,
            "network_none_verified": True,
            "uid": 1000,
            "gid": 1000,
        },
        "qualified_at": "2026-09-11T00:00:00Z",
        "outcome": "succeeded",
    }
    value.update(overrides)
    return value


def test_prepare_pier_smoke_flows_a_correct_inventory_through_to_the_runtime_binding(
    tmp_path: Path,
) -> None:
    store = ObjectStore(tmp_path / ".assay")
    ref = str(store.publish_json(_qualified_inventory_value()))
    result = prepare_pier_smoke(store, inventory_ref=ref)
    assert isinstance(result, PierExperimentPrepared)
    plan = json.loads(store.read_bytes(result.plan_ref))
    assert plan["runtime"]["version"] == EXPECTED_BRIDGE_LOCK_DIGEST


def test_prepare_pier_smoke_rejects_a_stale_inventory(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path / ".assay")
    stale = _qualified_inventory_value(qualified_at="not-a-timestamp")
    ref = str(store.publish_json(stale))
    result = prepare_pier_smoke(store, inventory_ref=ref)
    assert isinstance(result, PierExperimentFailed)
    assert "qualified_at" in result.message


def test_prepare_pier_smoke_rejects_a_future_dated_inventory(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path / ".assay")
    future = _qualified_inventory_value(qualified_at="2999-01-01T00:00:00Z")
    ref = str(store.publish_json(future))
    result = prepare_pier_smoke(store, inventory_ref=ref)
    assert isinstance(result, PierExperimentFailed)
    assert "future" in result.message


@pytest.mark.parametrize(
    "overrides",
    [
        {"bridge": {"pier_revision": "9.9.9"}},
        {"bridge": {"mini_swe_agent_revision": "0" * 40}},
        {"bridge": {"lock_digest": "sha256:" + "1" * 64}},
        {"bridge": {"bridge_image_digest": "sha256:" + "1" * 64}},
        {"measured": {"docker_version": "1.0.0"}},
        {"measured": {"uid": 2000}},
        {"measured": {"gid": 2000}},
    ],
)
def test_prepare_pier_smoke_rejects_a_mismatched_identity(
    tmp_path: Path, overrides: dict[str, object]
) -> None:
    store = ObjectStore(tmp_path / ".assay")
    base = _qualified_inventory_value()
    for key, patch in overrides.items():
        base[key] = {**base[key], **patch}  # type: ignore[dict-item]
    ref = str(store.publish_json(base))
    result = prepare_pier_smoke(store, inventory_ref=ref)
    assert isinstance(result, PierExperimentFailed)


def test_prepare_pier_smoke_rejects_a_structurally_invalid_inventory(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path / ".assay")
    value = _qualified_inventory_value()
    del value["measured"]
    ref = str(store.publish_json(value))
    result = prepare_pier_smoke(store, inventory_ref=ref)
    assert isinstance(result, PierExperimentFailed)
    assert "qualification rejected" in result.message.lower()


def test_prepare_never_imports_httpx_client_construction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Preparation must not construct an HTTP client of any kind."""
    real_import = builtins.__import__

    def _guarded_import(name: str, *args: object, **kwargs: object) -> object:
        if name in {"httpx", "requests", "docker"}:
            raise AssertionError(f"preparation must never import {name}")
        return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(builtins, "__import__", _guarded_import)
    store = ObjectStore(tmp_path / ".assay")
    ref = _publish_inventory(store, _inventory_value())
    result = load_qualification_inventory(store, inventory_ref=ref)
    assert isinstance(result, QualificationInventory)
