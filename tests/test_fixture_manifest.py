"""Fixture identity and secrecy at the schema/package boundary."""

from __future__ import annotations

import json
import shutil
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
        excluded_paths=("src/private/", "tests/hidden/"),
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

    fixture_root = tmp_path / "fixture"
    visible = {
        "src/workflow.ts": "export const workflow = 1;\n",
        "package.json": '{"name":"workflow-fixture"}\n',
    }
    private = {
        "tests/hidden/hidden_tests.txt": hidden["hidden_tests"],
        "src/private/reference_patch.txt": hidden["reference_patch"],
        "src/private/negative_patches.txt": hidden["negative_patches"],
        "src/private/rubric.txt": hidden["rubric"],
    }
    for path, content in {**visible, **private}.items():
        target = fixture_root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def under(path: str, selected: tuple[str, ...]) -> bool:
        return any(
            path == entry.rstrip("/") or path.startswith(entry.rstrip("/") + "/")
            for entry in selected
        )

    def package_from_paths(paths: tuple[str, ...], excluded: tuple[str, ...]) -> dict[str, str]:
        root = tmp_path / "arm"
        if root.exists():
            shutil.rmtree(root)
        root.mkdir()
        for source in fixture_root.rglob("*"):
            if not source.is_file():
                continue
            relative = source.relative_to(fixture_root).as_posix()
            if under(relative, paths) and not under(relative, excluded):
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
        package = build_package(
            cell_id="s1:mess-00:w0", task=manifest.task_prompt, repository_root=root
        )
        gate_package(package, expected_digest=package.manifest_digest)
        return package.as_mapping()

    assert under("src/private/reference_patch.txt", manifest.included_paths)
    assert under("src/private/reference_patch.txt", manifest.excluded_paths)
    packaged_files = package_from_paths(manifest.included_paths, manifest.excluded_paths)
    assert {path for path in packaged_files if path.startswith("workspace/")} == {
        f"workspace/{path}" for path in visible
    }
    package_text = "\n".join(packaged_files.values())
    assert all(content not in package_text for content in hidden.values())
    assert all(_digest(content) not in package_text for content in hidden.values())

    # This control shows the same fixture would leak when the overlapping
    # exclusion is lost; the absence check above must remain sensitive to it.
    leaky_files = package_from_paths(manifest.included_paths, ())
    assert hidden["reference_patch"] in "\n".join(leaky_files.values())


@pytest.mark.parametrize("section", ["observed_runtime_image_digest", "routing_config_digest"])
def test_image_and_routing_changes_change_fixture_identity(section: str) -> None:
    manifest = _manifest()
    changed = manifest.model_copy(update={section: _digest("changed " + section)})
    assert fixture_identity(changed) != fixture_identity(manifest)
