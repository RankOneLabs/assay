"""The standalone ce-v1 study sidecar and its rejection gates."""

from copy import deepcopy

import pytest
from code_extension.contract import ExtensionScenarioSidecar
from pydantic import ValidationError

from assay.canonical import canonical_json

SHA = "sha256:" + "a" * 64


def _record() -> dict[str, object]:
    return {
        "schema_version": "assay-extension-scenario-sidecar/0.1.0",
        "subject_id": "example",
        "writable_implementation_scope": ["src/"],
        "protected_assets": {
            "test_files": ["tests/visible/feature.test.ts", "tests/hidden/feature.test.ts"],
            "dependency_files": ["bun.lock"], "configuration_files": ["tsconfig.json"],
        },
        "public_requirements": ["The feature works"],
        "preexisting_behaviors": ["The baseline behavior stays intact"],
        "test_assertions": [
            {"assertion_id": "visible-1", "group_name": "visible", "visibility": "visible"},
            {"assertion_id": "hidden-1", "group_name": "hidden", "visibility": "hidden"},
        ],
        "requirements_to_tests": [
            {"assertion_id": "visible-1", "citation_kind": "public_requirement",
             "citation": "The feature works"},
            {"assertion_id": "hidden-1", "citation_kind": "preexisting_behavior",
             "citation": "The baseline behavior stays intact"},
        ],
        "patch_inventory": [
            {"arm_id": "baseline", "kind": "reference", "digest": SHA,
             "intent": "Implement the feature", "touched_paths": ["src/feature.ts"]},
            {"arm_id": "baseline", "kind": "incomplete", "digest": "sha256:" + "b" * 64,
             "intent": "Omit the edge case", "touched_paths": ["src/feature.ts"]},
        ],
        "evidence": {"leak_scan": SHA, "access_probe": SHA, "no_op": SHA,
                     "scripted_submission": SHA, "double_reproduction": SHA},
    }


def test_sidecar_canonical_round_trip() -> None:
    model = ExtensionScenarioSidecar.model_validate(_record())
    encoded = canonical_json(model.model_dump(mode="json"))
    decoded = ExtensionScenarioSidecar.model_validate_json(encoded)
    assert canonical_json(decoded.model_dump(mode="json")) == encoded


@pytest.mark.parametrize("change,reason", [
    ("patch", "outside writable scope"),
    ("protected", "protected assets overlap"),
    ("hidden", "hidden assertion is unlinked"),
    ("citation", "dangling citation"),
])
def test_sidecar_refuses_invalid_contracts(change: str, reason: str) -> None:
    value = deepcopy(_record())
    if change == "patch":
        value["patch_inventory"][0]["touched_paths"] = ["config/settings.ts"]  # type: ignore[index]
    elif change == "protected":
        value["protected_assets"]["test_files"] = ["src/feature.test.ts"]  # type: ignore[index]
    elif change == "hidden":
        value["requirements_to_tests"] = value["requirements_to_tests"][:1]  # type: ignore[index]
    else:
        value["requirements_to_tests"][0]["citation"] = "Undeclared"  # type: ignore[index]
    with pytest.raises(ValidationError, match=reason):
        ExtensionScenarioSidecar.model_validate(value)


@pytest.mark.parametrize("field,path,reason", [
    ("patch", "src/../tests/hidden/feature.test.ts", "patch touched paths"),
    ("patch", "/src/feature.ts", "patch touched paths"),
    ("patch", "src//feature.ts", "patch touched paths"),
    ("protected", "tests/hidden/../src/feature.ts", "protected assets"),
    ("protected", "/tests/hidden/feature.test.ts", "protected assets"),
    ("protected", "tests//hidden/feature.test.ts", "protected assets"),
])
def test_sidecar_refuses_noncanonical_paths(field: str, path: str, reason: str) -> None:
    value = deepcopy(_record())
    if field == "patch":
        value["patch_inventory"][0]["touched_paths"] = [path]  # type: ignore[index]
    else:
        value["protected_assets"]["test_files"] = [path]  # type: ignore[index]
    with pytest.raises(ValidationError, match=reason):
        ExtensionScenarioSidecar.model_validate(value)
