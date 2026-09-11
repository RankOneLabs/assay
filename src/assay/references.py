"""Role-aware object edges; content-looking strings are never implicit links."""

from __future__ import annotations

import json
from typing import Any

from jsonschema import Draft7Validator
from jsonschema.validators import validator_for
from referencing import Resource
from referencing.jsonschema import DRAFT7

from assay.canonical import canonical_json
from assay.store import ObjectRef, ObjectStore, verification_session

type Edge = tuple[str, str]

# Paths are relative to a governed document. '*' visits collection values.
# Roles come from the referring field, never from arbitrary artifact contents.
_PATHS: dict[str, dict[str, str]] = {
    "assay-study-snapshot/0.1.0": {
        "paa_task_ref": "data",
        "task_schema_ref": "schema",
        "evidence_schema_ref": "schema",
        "operating_schema_ref": "schema",
        "pricing_catalog_ref": "data",
        "subjects.*.digest": "data",
        "subjects.*.payload_ref": "data",
        "realizations.*.digest": "data",
        "realizations.*.artifact_ref": "data",
        "evaluators.*.basis_ref": "data",
        "evaluators.*.payload_schema_ref": "schema",
    },
    "assay-execution-plan/0.1.0": {
        "snapshot_ref": "assay-study-snapshot/0.1.0",
        "declaration_hashes.*": "data",
        "execution_conditions_ref": "data",
        "cells.*.realization_ref": "data",
    },
    "assay-run-manifest/0.1.0": {
        "plan_ref": "assay-execution-plan/0.1.0",
        "execution_records.*": "assay-execution-outcome/0.1.0",
        "evaluation_records.*": "evaluation",
        "operating_records.*": "operating",
    },
    "assay-execution-outcome/0.1.0": {
        "plan_ref": "assay-execution-plan/0.1.0",
        "input_ref": "data",
        "output_ref": "data",
        "trace_ref": "data",
        "coordinate.realization_ref": "data",
    },
    "assay-evaluation-failure/0.1.0": {
        "plan_ref": "assay-execution-plan/0.1.0",
        "trace_ref": "data",
    },
    "evidence": {
        "source_references.*": "data",
        "boundary.input_ref": "data",
        "boundary.output_ref": "data",
        "worker.configuration_ref": "data",
        "payload.plan_ref": "assay-execution-plan/0.1.0",
        "payload.base_subject_ref": "data",
        "payload.detail_refs.*": "data",
    },
    "operating": {"source_references.*": "data", "worker.configuration_ref": "data"},
    "assay-report-config/0.1.0": {
        "manifest_refs.*": "assay-run-manifest/0.1.0",
        "record_refs.*": "evaluation",
    },
    "assay-report/0.1.0": {
        "config_ref": "assay-report-config/0.1.0",
        "manifest_refs.*": "assay-run-manifest/0.1.0",
        "record_refs.*": "evaluation",
        "operating_refs.*": "operating",
        "comparisons.*.common_subjects_ref": "data",
    },
}


def _at(value: Any, path: list[str]) -> list[Any]:
    if not path:
        return [] if value is None else [value]
    key, *rest = path
    if key == "*":
        values = value.values() if isinstance(value, dict) else value
        if not isinstance(values, (list, tuple)) and not isinstance(value, dict):
            raise ValueError("reference collection must be an object or array")
        return [ref for item in values for ref in _at(item, rest)]
    if isinstance(value, dict) and key in value:
        return _at(value[key], rest)
    return []


def _extensions(value: Any) -> set[Edge]:
    if isinstance(value, dict):
        refs = value.get("assay_object_refs", [])
        if not isinstance(refs, list):
            raise ValueError("assay_object_refs must be an array of content addresses")
        edges = {(str(ObjectRef(ref)), "data") for ref in refs}
        for key, item in value.items():
            if key != "assay_object_refs":
                edges.update(_extensions(item))
        return edges
    if isinstance(value, (list, tuple)):
        return set().union(*(_extensions(item) for item in value))
    return set()


def _schema_edges(value: Any) -> set[Edge]:
    """Follow schema applicators, not examples/defaults/enum instance data."""
    edges: set[Edge] = set()

    def visit(resource: Resource[Any], default: Any) -> None:
        schema = resource.contents
        if not isinstance(schema, dict):
            return
        validator = validator_for(schema, default=default)
        for key in ("$ref", "$dynamicRef", "$recursiveRef"):
            ref = schema.get(key)
            if (
                key in validator.VALIDATORS
                and isinstance(ref, str)
                and ref.startswith("sha256:")
            ):
                edges.add((str(ObjectRef(ref.split("#", 1)[0])), "schema"))
        # Use the same dialect-aware subresource rules as schema resolution.
        for child in resource.subresources():
            visit(child, validator)

    visit(Resource.from_contents(value, default_specification=DRAFT7), Draft7Validator)
    return edges


def object_edges(value: Any, role: str = "auto") -> set[Edge]:
    if role == "schema":
        return _schema_edges(value)
    if isinstance(value, dict):
        if role == "auto":
            identity = value.get("schema_version", value.get("record_schema", "data"))
            role = identity if isinstance(identity, str) else "data"
        if role == "evaluation":
            role = (
                "assay-evaluation-failure/0.1.0"
                if value.get("schema_version") == "assay-evaluation-failure/0.1.0"
                else "evidence"
            )
    edges = _extensions(value)
    for path, target_role in _PATHS.get(role, {}).items():
        edges.update((str(ObjectRef(ref)), target_role) for ref in _at(value, path.split(".")))
    return edges


def walk_closure(store: ObjectStore, roots: set[Edge]) -> set[str]:
    """Validate each edge in its referring context, even for shared object bytes."""
    session = verification_session(store)
    pending = list(roots)
    seen: set[Edge] = set()
    while pending:
        edge = pending.pop()
        if edge in seen:
            continue
        seen.add(edge)
        ref, role = edge
        if edge not in session.edges:
            data = session.read_bytes(ref)
            try:
                value = json.loads(data)
            except (ValueError, UnicodeDecodeError):
                session.edges[edge] = frozenset()
            else:
                # Parsed JSON must have one canonical interpretation before it
                # contributes edges. Keep rejection outside the parse fallback:
                # invalid canonical values must not become opaque leaves.
                if canonical_json(value) != data:
                    raise ValueError(f"noncanonical JSON at {ref}")
                session.edges[edge] = frozenset(object_edges(value, role))
        pending.extend(session.edges[edge] - seen)
    return {ref for ref, _ in seen}


def reference_closure(store: ObjectStore, roots: tuple[str, ...]) -> set[str]:
    """Read and hash-check the declared closure; binary data objects are leaves."""
    return walk_closure(store, {(ref, "auto") for ref in roots})
