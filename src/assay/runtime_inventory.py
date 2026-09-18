"""Purely local Pier runtime qualification inventory.

Preparation for the Pier vertical slice is a read of already-recorded,
already-qualified bytes -- never a live check. This module must never create
an HTTP client, make a network request, launch Docker, install a dependency,
or perform any other mutable inspection of the machine it runs on; every
test in ``tests/test_pier_prepare.py`` exists to catch a regression of that
rule, not to trust a comment.

A stale, incomplete, or mismatched inventory fails closed: callers get a
typed ``QualificationRejected`` value, never an exception escaping past this
module's boundary.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

from pydantic import Field

from assay.canonical import canonical_json, digest_bytes
from assay.models import NonEmpty, Sha256Ref, WireModel
from assay.pier_protocol import RuntimeBinding
from assay.store import ObjectStore


class BridgeLock(WireModel):
    """Runtime identity inputs pinned at bridge sync time.

    Mirrors ``integrations/pier/src/assay_pier_bridge/protocol.py``'s
    ``BridgeIdentity`` without importing it -- the bridge project is
    deliberately isolated from this one.
    """

    pier_revision: NonEmpty
    mini_swe_agent_revision: NonEmpty
    lock_digest: Sha256Ref
    bridge_image_digest: Sha256Ref


class MeasuredEnforcement(WireModel):
    """What a completed qualification run actually observed the sandbox do.

    ``network_none_verified`` must be an explicit, measured ``True`` -- a
    qualification that never checked network isolation cannot claim it.
    """

    docker_version: NonEmpty
    network_none_verified: Literal[True]
    uid: int = Field(ge=1, strict=True)
    gid: int = Field(ge=1, strict=True)


class QualificationInventory(WireModel):
    """A single successful qualification run, recorded once, read many times."""

    schema_version: Literal["assay-pier-qualification/0.1.0"] = "assay-pier-qualification/0.1.0"
    bridge: BridgeLock
    measured: MeasuredEnforcement
    qualified_at: NonEmpty
    outcome: Literal["succeeded"] = "succeeded"


@dataclass(frozen=True, slots=True)
class QualificationRejected:
    reason: str


type QualificationResult = QualificationInventory | QualificationRejected


def load_qualification_inventory(store: ObjectStore, *, inventory_ref: str) -> QualificationResult:
    """Read and verify a recorded qualification; never touches the network or Docker.

    Any failure -- an unreadable object, non-canonical bytes, a digest that
    does not match ``inventory_ref``, or a shape that fails the closed
    ``QualificationInventory`` model -- fails closed as a typed rejection.
    """
    try:
        raw = store.read_bytes(inventory_ref)
        value = json.loads(raw)
        if canonical_json(value) != raw:
            return QualificationRejected("qualification inventory is not canonical JSON")
        if digest_bytes(raw) != inventory_ref:
            return QualificationRejected("qualification inventory digest mismatch")
        return QualificationInventory.model_validate(value)
    except Exception as error:
        return QualificationRejected(f"{type(error).__name__}: {error}")


def runtime_binding_from_inventory(
    inventory: QualificationInventory, *, configuration_ref: str, package_digest: str
) -> RuntimeBinding:
    """Project a qualified inventory onto the ``RuntimeBinding`` a cell's exchange is bound to.

    ``runtime_version`` is the bridge lock digest -- the durable identity
    input the bridge's own README names, not the (non-reproducible) image ID.
    """
    return RuntimeBinding(
        runtime_version=inventory.bridge.lock_digest,
        image_digest=inventory.bridge.bridge_image_digest,
        configuration_ref=configuration_ref,
        package_digest=package_digest,
    )


__all__ = [
    "BridgeLock",
    "MeasuredEnforcement",
    "QualificationInventory",
    "QualificationRejected",
    "QualificationResult",
    "load_qualification_inventory",
    "runtime_binding_from_inventory",
]
