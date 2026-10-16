"""Fixture identity and secrecy at the schema/package boundary."""

from __future__ import annotations

import copy
import json
import math
import shutil
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError

from assay.canonical import digest_bytes
from assay.fixture_manifest import (
    DOSE_ARMS,
    DOSED_ARMS,
    FixtureManifest,
    FixtureManifestV2,
    TreatmentSite,
    dose_count,
    fixture_identity,
    parse_fixture_manifest,
    task_record_digest,
)
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


def test_exported_schema_rejects_invalid_arm_id_like_model() -> None:
    wire = _manifest().model_dump(mode="json")
    wire["per_arm_tree_digests"]["invalid/arm"] = _digest("another arm")
    schema = json.loads(schema_documents()["assay-fixture-manifest.schema.json"])
    with pytest.raises(JsonSchemaValidationError, match="invalid/arm"):
        Draft202012Validator(schema).validate(wire)
    with pytest.raises(ValidationError, match="invalid/arm"):
        FixtureManifest.model_validate(wire)


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


# --- assay-fixture-manifest/0.2.0 -------------------------------------------

SCHEMAS = Path(__file__).resolve().parents[1] / "schemas"


def _members(rank: int, n: int) -> list[str]:
    return [arm for arm in DOSED_ARMS if rank <= dose_count(arm, n)]


def _qualification(arm: str, *, feature: str = "failed") -> dict[str, Any]:
    return {
        check: {"outcome": outcome, "evidence": _digest(f"{arm} {check} record")}
        for check, outcome in (
            ("baseline_passes", "passed"),
            ("feature_fails", feature),
            ("reference_passes", "passed"),
            ("equivalence_passes", "passed"),
        )
    }


def _task_wire(subject_id: str = "subject-a", n: int = 5) -> dict[str, Any]:
    sites = [
        {
            "rank": rank,
            "path": f"src/module_{rank}.ts",
            "symbol": f"caller{rank}",
            "span": {"start_line": 10, "end_line": 20},
            "arms": _members(rank, n),
            "removed_imports": (
                [{"module": "./owner", "name": "readOwner", "arms": _members(rank, n)}]
                if rank == 1
                else []
            ),
            "comment_corrections": (
                [{"span": {"start_line": 9, "end_line": 9}, "reason": "names the owner"}]
                if rank == 2
                else []
            ),
        }
        for rank in range(1, n + 1)
    ]
    return {
        "subject_id": subject_id,
        "task_prompt": "Make pointer resolution strict.",
        "normalization_patch": _digest(f"{subject_id} normalization"),
        "transformation_version": "inline-owner/1",
        "treatment_site_count": n,
        "treatment_sites": sites,
        "arms": {
            arm: {
                "tree_digest": _digest(f"{subject_id} {arm} tree"),
                "reference_patch": _digest(f"{subject_id} {arm} reference"),
                "negative_patches": [_digest(f"{subject_id} {arm} negative")],
                "qualification": _qualification(arm),
            }
            for arm in DOSE_ARMS
        },
        "visible_tests": [{"name": "visible_regression", "digest": _digest("visible")}],
        "hidden_tests": [
            {"name": "hidden_regression", "digest": _digest(f"{subject_id} hidden regression")},
            {"name": "new_behavior", "digest": _digest(f"{subject_id} new behavior")},
        ],
        "equivalence_suite": _digest(f"{subject_id} equivalence suite"),
        "rubric": _digest(f"{subject_id} rubric"),
    }


def _manifest_v2_wire(**changes: Any) -> dict[str, Any]:
    wire: dict[str, Any] = {
        "schema_version": "assay-fixture-manifest/0.2.0",
        "checkpoint_sha": "b" * 40,
        "included_paths": ["src/", "tests/visible/", "package.json"],
        "excluded_paths": ["tests/hidden/"],
        "normalization_diff": "slice adaptations only\n",
        "dependency_lock_digests": {"package-lock.json": _digest("locked npm tree")},
        "observed_runtime_image_digest": _digest("inspected image"),
        "routing_config_digest": _digest("routing_config.yaml bytes"),
        "tasks": [_task_wire("subject-a"), _task_wire("subject-b", n=4)],
    }
    wire.update(changes)
    return wire


def _with_task(**changes: Any) -> dict[str, Any]:
    return _manifest_v2_wire(tasks=[{**_task_wire(), **changes}])


def _with_sites(changes: dict[int, dict[str, Any]]) -> dict[str, Any]:
    task = _task_wire()
    for rank, change in changes.items():
        task["treatment_sites"][rank - 1].update(change)
    return _manifest_v2_wire(tasks=[task])


def _with_site(rank: int, /, **changes: Any) -> dict[str, Any]:
    return _with_sites({rank: changes})


def _v2_schema() -> dict[str, Any]:
    schema: dict[str, Any] = json.loads(
        schema_documents()["assay-fixture-manifest-v0.2.schema.json"]
    )
    return schema


def _reject(wire: dict[str, Any], match: str) -> None:
    with pytest.raises(ValidationError, match=match):
        FixtureManifestV2.model_validate(wire)


@pytest.mark.parametrize(
    "name", ["assay-fixture-manifest.schema.json", "assay-fixture-manifest-v0.2.schema.json"]
)
def test_committed_fixture_manifest_schemas_match_models(name: str) -> None:
    assert (SCHEMAS / name).read_bytes() == schema_documents()[name]


def test_manifest_v2_round_trips_through_exported_schema() -> None:
    wire = _manifest_v2_wire()
    schema = _v2_schema()
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(wire)
    manifest = FixtureManifestV2.model_validate(wire)
    assert manifest.model_dump(mode="json") == wire
    assert parse_fixture_manifest(wire) == manifest
    task = manifest.task("subject-a")
    assert task is not None and task.qualified
    assert manifest.task("subject-z") is None
    assert task.group("new_behavior", hidden=True) == task.hidden_tests[1]
    assert task.group("new_behavior", hidden=False) is None


def test_parse_fixture_manifest_keeps_0_1_0_readable_and_rejects_unknown_versions() -> None:
    old = _manifest()
    assert parse_fixture_manifest(old.model_dump(mode="json")) == old
    with pytest.raises(ValidationError):
        parse_fixture_manifest(_manifest_v2_wire(schema_version="assay-fixture-manifest/9.9.9"))


@pytest.mark.parametrize("n", [4, 5, 6, 7, 12])
def test_dose_counts_are_one_half_and_all(n: int) -> None:
    task = FixtureManifestV2.model_validate(_manifest_v2_wire(tasks=[_task_wire(n=n)])).tasks[0]
    low, mid, high = (
        {site.rank for site in task.treatment_sites if arm in site.arms} for arm in DOSED_ARMS
    )
    assert (len(low), len(mid), len(high)) == (1, math.ceil(n / 2), n)
    assert low < mid < high


@pytest.mark.parametrize(
    ("wire", "match"),
    [
        (_with_task(treatment_site_count=6), "treatment_site_count is 6"),
        (_with_task(treatment_site_count=3), "greater than or equal to 4"),
        # mid doses ranks 1..3 of N=5; taking rank 3 out of mid leaves two.
        (_with_site(3, arms=["mess-high"]), "mess-mid must dose 3"),
        # A site in mid but not in high breaks the nesting.
        (_with_site(2, arms=["mess-mid"]), "must nest"),
        (_with_site(2, arms=["mess-high", "mess-mid"]), "dose order"),
        (_with_site(1, arms=["mess-00", "mess-low", "mess-mid", "mess-high"]), "mess-low"),
        (_with_site(2, rank=7), "ranks must be 1..N"),
        # Right count, wrong sites: mid must be the lowest-ranked prefix.
        (_with_sites({3: {"arms": ["mess-high"]}, 4: {"arms": ["mess-mid", "mess-high"]}}),
         "mess-mid must dose the 3 lowest-ranked"),
        (_with_site(2, path="src/module_1.ts", span={"start_line": 15, "end_line": 30}),
         "sites overlap"),
        (_with_site(2, path="src/module_1.ts", symbol="caller1",
                    span={"start_line": 40, "end_line": 50}), "sites overlap"),
        (_with_site(2, path="../escape.ts"), "normalized relative"),
        (_with_site(5, removed_imports=[
            {"module": "./o", "name": "o", "arms": ["mess-low", "mess-mid", "mess-high"]}]),
         "only in arms where its site is inline"),
        (_with_site(1, removed_imports=[{"module": "./o", "name": "o", "arms": ["mess-low"]}]),
         "removed-import arms must nest"),
        (_with_site(2, span={"start_line": 9, "end_line": 3}), "end_line"),
    ],
)
def test_manifest_v2_rejects_invalid_dose_inventory(wire: dict[str, Any], match: str) -> None:
    _reject(wire, match)


def test_manifest_v2_rejects_invalid_arms_groups_and_tasks() -> None:
    arms = copy.deepcopy(_task_wire()["arms"])
    del arms["mess-mid"]
    _reject(_with_task(arms=arms), "at least 4 items")
    same = copy.deepcopy(_task_wire()["arms"])
    same["mess-high"] = same["mess-00"]
    _reject(_with_task(arms=same), "own repository tree")
    _reject(
        _with_task(visible_tests=[{"name": "hidden_regression", "digest": _digest("v")}]),
        "names must be unique",
    )
    reused = {"name": "visible", "digest": _digest("subject-a new behavior")}
    _reject(_with_task(visible_tests=[reused]), "digests must be distinct")
    _reject(_manifest_v2_wire(tasks=[_task_wire("b"), _task_wire("a")]), "sorted order")
    _reject(_manifest_v2_wire(tasks=[_task_wire("a"), _task_wire("a")]), "unique subject ids")
    _reject(_manifest_v2_wire(tasks=[]), "at least 1 item")


def test_exported_v2_schema_refuses_unknown_or_missing_arms_and_mess_00_sites() -> None:
    validator = Draft202012Validator(_v2_schema())
    extra = _manifest_v2_wire()
    extra["tasks"][0]["arms"]["mess-extra"] = extra["tasks"][0]["arms"]["mess-00"]
    with pytest.raises(JsonSchemaValidationError, match="mess-extra"):
        validator.validate(extra)
    missing = _manifest_v2_wire()
    del missing["tasks"][0]["arms"]["mess-low"]
    with pytest.raises(JsonSchemaValidationError, match="does not have enough properties"):
        validator.validate(missing)
    with pytest.raises(JsonSchemaValidationError, match="mess-00"):
        validator.validate(_with_site(1, arms=["mess-00", "mess-low", "mess-mid", "mess-high"]))


@pytest.mark.parametrize("section", list(_manifest_v2_wire()))
def test_manifest_v2_requires_every_section(section: str) -> None:
    wire = _manifest_v2_wire()
    del wire[section]
    with pytest.raises(JsonSchemaValidationError, match=section):
        Draft202012Validator(_v2_schema()).validate(wire)
    with pytest.raises(ValidationError, match=section):
        FixtureManifestV2.model_validate(wire)


def test_hosted_manifest_states_no_routing_and_identity_binds_image_and_routing() -> None:
    hosted = FixtureManifestV2.model_validate(_manifest_v2_wire(routing_config_digest=None))
    Draft202012Validator(_v2_schema()).validate(hosted.model_dump(mode="json"))
    local = FixtureManifestV2.model_validate(_manifest_v2_wire())
    rerouted = local.model_copy(update={"routing_config_digest": _digest("other routing")})
    rebuilt = local.model_copy(update={"observed_runtime_image_digest": _digest("rebuilt")})
    assert len({fixture_identity(item) for item in (local, rerouted, rebuilt, hosted)}) == 4


def test_failed_arm_qualification_is_recorded_but_not_qualified() -> None:
    task = _task_wire()
    task["arms"]["mess-mid"]["qualification"] = _qualification("mess-mid", feature="passed")
    record = FixtureManifestV2.model_validate(_manifest_v2_wire(tasks=[task])).tasks[0]
    assert not record.arms["mess-mid"].qualification.qualified
    assert not record.qualified
    clean = FixtureManifestV2.model_validate(_manifest_v2_wire(tasks=[_task_wire()])).tasks[0]
    assert task_record_digest(record) != task_record_digest(clean)


def test_manifest_v2_hidden_assets_are_digest_only() -> None:
    wire = json.dumps(_manifest_v2_wire())
    for content in ("subject-a mess-low reference", "subject-a new behavior", "subject-a rubric"):
        assert content not in wire
        assert _digest(content) in wire
