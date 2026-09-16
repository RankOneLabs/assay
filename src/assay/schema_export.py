"""Generate or check the explicit inventory of published Assay wire schemas."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from assay.models import (
    Arm,
    EvaluationFailure,
    ExecutionOutcome,
    ExecutionPlan,
    ExecutionPlanV2,
    ReportConfig,
    RunManifest,
    StudySnapshot,
    WireModel,
)

SCHEMA_MODELS: dict[str, type[WireModel]] = {
    "assay-arm-declaration": Arm,
    "assay-evaluation-failure": EvaluationFailure,
    "assay-execution-outcome": ExecutionOutcome,
    "assay-report-config": ReportConfig,
    "assay-run-manifest": RunManifest,
    "assay-study-snapshot": StudySnapshot,
}

# The execution plan is dual-versioned: each wire shape gets its own pinned
# schema document, and the unversioned name is a discriminator-selected oneOf
# over both, so existing consumers of "assay-execution-plan" keep resolving.
PLAN_SCHEMA_MODELS: dict[str, type[WireModel]] = {
    "assay-execution-plan-v0.1": ExecutionPlan,
    "assay-execution-plan-v0.2": ExecutionPlanV2,
}


def _schema_document(name: str, model: type[WireModel]) -> dict[str, Any]:
    schema = model.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = f"https://assay.dev/schemas/{name}.schema.json"
    return schema


def schema_documents() -> dict[str, bytes]:
    documents = {}
    for name, model in {**SCHEMA_MODELS, **PLAN_SCHEMA_MODELS}.items():
        schema = _schema_document(name, model)
        documents[f"{name}.schema.json"] = (json.dumps(schema, indent=2) + "\n").encode()
    plan_union = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://assay.dev/schemas/assay-execution-plan.schema.json",
        "oneOf": [
            {"$ref": f"https://assay.dev/schemas/{name}.schema.json"}
            for name in PLAN_SCHEMA_MODELS
        ],
    }
    documents["assay-execution-plan.schema.json"] = (
        json.dumps(plan_union, indent=2) + "\n"
    ).encode()
    return documents


def check_schemas(directory: Path) -> None:
    expected = schema_documents()
    actual = {path.name for path in directory.glob("*.schema.json")}
    if actual != expected.keys():
        raise ValueError(f"schema inventory differs: {sorted(actual ^ expected.keys())}")
    for name, data in expected.items():
        if (directory / name).read_bytes() != data:
            raise ValueError(f"generated schema differs: {name}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path("schemas"))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        try:
            check_schemas(args.directory)
        except ValueError as error:
            parser.exit(1, f"{error}\n")
    else:
        args.directory.mkdir(parents=True, exist_ok=True)
        for name, data in schema_documents().items():
            (args.directory / name).write_bytes(data)


if __name__ == "__main__":
    main()
