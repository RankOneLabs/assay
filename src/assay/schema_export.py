"""Generate or check the explicit inventory of published Assay wire schemas."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from assay.code_metrics.models import (
    CodeMetricsComparison,
    CodeMetricsComparisonV2,
    CodeMetricsComparisonV4,
    CodeMetricsComparisonV5,
    CodeMetricsComparisonV6,
    CodeMetricsReport,
    CodeMetricsReportV2,
    CodeMetricsReportV3,
    CodeMetricsReportV4,
    CodeMetricsReportV5,
    DetailedCodeMetricsComparison,
)
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

CODE_METRICS_SCHEMA_MODELS: dict[str, dict[str, type[WireModel]]] = {
    "assay-code-metrics-report": {
        "assay-code-metrics-report-v0.1": CodeMetricsReport,
        "assay-code-metrics-report-v0.2": CodeMetricsReportV2,
        "assay-code-metrics-report-v0.3": CodeMetricsReportV3,
        "assay-code-metrics-report-v0.4": CodeMetricsReportV4,
        "assay-code-metrics-report-v0.5": CodeMetricsReportV5,
    },
    "assay-code-metrics-comparison": {
        "assay-code-metrics-comparison-v0.1": CodeMetricsComparison,
        "assay-code-metrics-comparison-v0.2": CodeMetricsComparisonV2,
        "assay-code-metrics-comparison-v0.3": DetailedCodeMetricsComparison,
        "assay-code-metrics-comparison-v0.4": CodeMetricsComparisonV4,
        "assay-code-metrics-comparison-v0.5": CodeMetricsComparisonV5,
        "assay-code-metrics-comparison-v0.6": CodeMetricsComparisonV6,
    },
}


def _schema_document(
    name: str, model: type[WireModel], *, require_version: bool = False
) -> dict[str, Any]:
    schema = model.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = f"https://assay.dev/schemas/{name}.schema.json"
    if require_version:
        # schema_version has a Pydantic default, so it is otherwise absent from
        # "required" -- but the root oneOf discriminates on it, and a payload
        # missing it must fail here rather than reach parse_execution_plan.
        required = schema.setdefault("required", [])
        if "schema_version" not in required:
            required.append("schema_version")
    return schema


def schema_documents() -> dict[str, bytes]:
    documents = {}
    for name, model in SCHEMA_MODELS.items():
        schema = _schema_document(name, model)
        documents[f"{name}.schema.json"] = (json.dumps(schema, indent=2) + "\n").encode()
    for name, model in PLAN_SCHEMA_MODELS.items():
        schema = _schema_document(name, model, require_version=True)
        documents[f"{name}.schema.json"] = (json.dumps(schema, indent=2) + "\n").encode()
    plan_union = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://assay.dev/schemas/assay-execution-plan.schema.json",
        "oneOf": [
            {"$ref": f"https://assay.dev/schemas/{name}.schema.json"} for name in PLAN_SCHEMA_MODELS
        ],
    }
    documents["assay-execution-plan.schema.json"] = (
        json.dumps(plan_union, indent=2) + "\n"
    ).encode()
    for root_name, versions in CODE_METRICS_SCHEMA_MODELS.items():
        for name, model in versions.items():
            schema = _schema_document(name, model, require_version=True)
            documents[f"{name}.schema.json"] = (json.dumps(schema, indent=2) + "\n").encode()
        root = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": f"https://assay.dev/schemas/{root_name}.schema.json",
            "oneOf": [
                {"$ref": f"https://assay.dev/schemas/{name}.schema.json"} for name in versions
            ],
        }
        documents[f"{root_name}.schema.json"] = (json.dumps(root, indent=2) + "\n").encode()
    return documents


def plan_schema_registry() -> Registry[Any]:
    """A registry the root ``assay-execution-plan.schema.json`` oneOf resolves against.

    The root document's ``$ref``s point at the pinned v0.1/v0.2 documents by their
    declared ``$id``; a validator loading only the root document cannot resolve those
    references without the sibling schemas registered offline first.
    """
    registry: Registry[Any] = Registry()
    for name, model in PLAN_SCHEMA_MODELS.items():
        schema = _schema_document(name, model, require_version=True)
        resource = Resource.from_contents(schema, default_specification=DRAFT202012)
        registry = registry.with_resource(schema["$id"], resource)
    return registry


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
