"""Fixture identity and secrecy at the schema/package boundary."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError

from assay.canonical import digest_bytes
from assay.fixture_manifest import FixtureManifest, TreatmentSite, fixture_identity
from assay.pier_packaging import build_package, gate_package
from assay.schema_export import schema_documents


def _digest(value: str) -> str:
    return digest_bytes(value.encode())


def _manifest() -> FixtureManifest:
    return FixtureManifest(
        schema_version="assay-fixture-manifest/0.1.0",
        checkpoint_sha="a" * 40,
        included_paths=("src/", "package.json"),
        excluded_paths=("private/", "tests/hidden/"),
        dependency_lock_digests={"package-lock.json": _digest("locked npm tree")},
        observed_runtime_image_digest=_digest("inspected image"),
        normalization_diff="removed generated cache\n",
        treatment_site_inventory=(
            TreatmentSite(path="src/workflow.ts", description="duplicate branch"),
        ),
        per_arm_tree_digests={"mess-00": _digest("arm tree")},
        transformation_version="transform-1",
        equivalence_test_version="equivalence-1",
        task_prompt="Repair the workflow edit.",
        hidden_tests=(_digest("hidden test bytes"),),
        reference_patch=_digest("reference patch bytes"),
        negative_patches=(_digest("negative patch bytes"),),
        rubric=_digest("rubric bytes"),
        routing_config_digest=_digest("routing_config.yaml bytes"),
    )


def test_manifest_round_trips_through_exported_schema() -> None:
    manifest = _manifest()
    wire = manifest.model_dump(mode="json")
    schema = json.loads(schema_documents()["assay-fixture-manifest.schema.json"])
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(wire)
    assert FixtureManifest.model_validate_json(json.dumps(wire)) == manifest


@pytest.mark.parametrize("section", list(_manifest().model_dump(mode="json")))
def test_manifest_requires_every_section(section: str) -> None:
    wire = _manifest().model_dump(mode="json")
    del wire[section]
    schema = json.loads(schema_documents()["assay-fixture-manifest.schema.json"])
    with pytest.raises(JsonSchemaValidationError, match=section):
        Draft202012Validator(schema).validate(wire)
    with pytest.raises(ValidationError, match=section):
        FixtureManifest.model_validate(wire)


def test_hidden_assets_are_digest_only_and_absent_from_same_fixture_package(tmp_path: Path) -> None:
    hidden = {
        "hidden_tests": "hidden test bytes",
        "reference_patch": "reference patch bytes",
        "negative_patches": "negative patch bytes",
        "rubric": "rubric bytes",
    }
    manifest = _manifest()
    wire = manifest.model_dump(mode="json")
    assert wire["hidden_tests"] == [_digest(hidden["hidden_tests"])]
    assert wire["reference_patch"] == _digest(hidden["reference_patch"])
    assert wire["negative_patches"] == [_digest(hidden["negative_patches"])]
    assert wire["rubric"] == _digest(hidden["rubric"])
    assert all(content not in json.dumps(wire) for content in hidden.values())

    root = tmp_path / "arm"
    root.mkdir()
    (root / "workflow.ts").write_text("export const workflow = 1;\n", encoding="utf-8")
    package = build_package(
        cell_id="s1:mess-00:w0", task=manifest.task_prompt, repository_root=root
    )
    gate_package(package, expected_digest=package.manifest_digest)
    package_text = "\n".join(package.as_mapping().values())
    assert all(content not in package_text for content in hidden.values())
    assert all(_digest(content) not in package_text for content in hidden.values())


@pytest.mark.parametrize("section", ["observed_runtime_image_digest", "routing_config_digest"])
def test_image_and_routing_changes_change_fixture_identity(section: str) -> None:
    manifest = _manifest()
    changed = manifest.model_copy(update={section: _digest("changed " + section)})
    assert fixture_identity(changed) != fixture_identity(manifest)
