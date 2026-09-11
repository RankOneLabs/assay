"""One pinned, offline-only JSON Schema policy for execution and verification."""

from __future__ import annotations

import json
from typing import Any

from jsonschema import FormatChecker
from jsonschema.validators import validator_for
from referencing import Registry, Resource
from referencing.exceptions import NoSuchResource
from referencing.jsonschema import DRAFT7

from assay.canonical import canonical_json
from assay.models import StudySnapshot
from assay.store import ObjectStore

# Canonical paa-contracts 0.3 artifacts. Never trust substituted normative schemas.
SUPPORTED_CONTRACTS = {
    "task_schema_ref": "sha256:f94bc8419ec304b32578af87fb6f4dcde5dee681980a661d24ec512e1c5a862d",
    "evidence_schema_ref": (
        "sha256:d5b2ffc21d6aa9529c65eb643d2fcff9090a63af904b6c40dfe1c12fe48a1784"
    ),
    "operating_schema_ref": (
        "sha256:131f4842243c50005b9af041308d5893e05b53ee7c3c38ef82bd706bf8657c23"
    ),
}


def _deny_remote(uri: str) -> Resource[Any]:
    raise NoSuchResource(uri)


def schema_validators(store: ObjectStore, snapshot: StudySnapshot) -> dict[str, Any]:
    """Register each canonical schema by both identity and content address."""
    if any(getattr(snapshot, field) != ref for field, ref in SUPPORTED_CONTRACTS.items()):
        raise ValueError("snapshot substitutes an unsupported normative PAA contract")
    refs = [snapshot.task_schema_ref, snapshot.evidence_schema_ref, snapshot.operating_schema_ref]
    refs.extend(item.payload_schema_ref for item in snapshot.evaluators)
    schemas: dict[str, Any] = {}
    identities: dict[str, str] = {}
    registry: Registry[Any] = Registry(retrieve=_deny_remote)  # type: ignore[call-arg]
    for ref in dict.fromkeys(refs):
        data = store.read_bytes(ref)
        schema = json.loads(data)
        if canonical_json(schema) != data:
            raise ValueError(f"noncanonical JSON at {ref}")
        validator_for(schema).check_schema(schema)
        schema_id = schema.get("$id")
        if not isinstance(schema_id, str):
            raise ValueError(f"schema at {ref} requires an $id")
        if schema_id in identities and identities[schema_id] != ref:
            raise ValueError(f"different schemas claim the same identity {schema_id}")
        identities[schema_id] = ref
        resource = Resource.from_contents(schema, default_specification=DRAFT7)
        registry = registry.with_resource(schema_id, resource).with_resource(ref, resource)
        schemas[ref] = schema
    return {
        ref: validator_for(schema)(schema, registry=registry, format_checker=FormatChecker())
        for ref, schema in schemas.items()
    }
