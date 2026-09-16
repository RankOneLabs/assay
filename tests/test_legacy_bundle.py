"""A fixed, checked-in 0.1.0 bundle stays byte-exact under the dual-version core.

This exercises verification, export, discovery and offline rendering against
a pre-built ``tests/fixtures/legacy-0.1.0-bundle`` fixture instead of a freshly
executed run, so a regression in historical compatibility shows up even if
nothing about *today's* compilation changed.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from assay.models import ExecutionPlan, RunManifest
from assay.review.export import build_export_data
from assay.review.index import IndexedPlan, build_index, classify_object
from assay.store import ObjectStore
from assay.verify import export_bundle, verify_bundle, verify_manifest

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "legacy-0.1.0-bundle" / "bundle"
MANIFEST_REF = "sha256:7f60b6946084c4ef35c81fea380daa2c669a1f634e8edc85b11cf79cf97a3803"


def _read_only_copy(tmp_path: Path) -> ObjectStore:
    """Discovery writes a dispensable cache sibling; never let it dirty the fixture."""
    copy = tmp_path / "bundle"
    shutil.copytree(FIXTURE_ROOT, copy)
    return ObjectStore(copy)


def test_fixture_manifest_verifies_offline() -> None:
    store = ObjectStore(FIXTURE_ROOT)
    assert verify_manifest(store, MANIFEST_REF) == ()


def test_fixture_bundle_is_exactly_its_own_closure() -> None:
    store = ObjectStore(FIXTURE_ROOT)
    assert verify_bundle(store, MANIFEST_REF) == ()


def test_fixture_re_exports_byte_identically(tmp_path: Path) -> None:
    store = ObjectStore(FIXTURE_ROOT)
    exported = export_bundle(store, MANIFEST_REF, tmp_path / "export")
    assert verify_bundle(exported, MANIFEST_REF) == ()
    original = {p.name: p.read_bytes() for p in store.objects.iterdir()}
    copied = {p.name: p.read_bytes() for p in exported.objects.iterdir()}
    assert original == copied


def test_fixture_manifest_and_plan_are_the_legacy_0_1_0_shape() -> None:
    store = ObjectStore(FIXTURE_ROOT)
    manifest = RunManifest.model_validate_json(store.read_bytes(MANIFEST_REF))
    assert manifest.schema_version == "assay-run-manifest/0.1.0"
    plan = ExecutionPlan.model_validate_json(store.read_bytes(manifest.plan_ref))
    assert plan.schema_version == "assay-execution-plan/0.1.0"
    assert isinstance(plan.jig_revision, str) and plan.jig_revision


def test_fixture_discovers_and_projects_legacy_runtime_identity(tmp_path: Path) -> None:
    store = _read_only_copy(tmp_path)
    index = build_index(store)
    run = next(run for run in index.runs if run.manifest_ref == MANIFEST_REF)
    assert run.summary.status == "complete"
    assert run.summary.runtime_id == "jig"
    assert run.summary.runtime_version == run.summary.jig_revision
    assert run.summary.jig_revision is not None

    plan_item = classify_object(run.plan_ref, store.read_bytes(run.plan_ref))
    assert isinstance(plan_item, IndexedPlan)
    assert isinstance(plan_item.value, ExecutionPlan)


def test_fixture_renders_for_offline_export(tmp_path: Path) -> None:
    store = _read_only_copy(tmp_path)
    export_data = build_export_data(store, MANIFEST_REF)
    assert export_data.root_ref == MANIFEST_REF
    run_summary = next(
        run for run in export_data.store.runs if run.manifest_ref == MANIFEST_REF
    )
    assert run_summary.runtime_id == "jig"
    assert run_summary.jig_revision == run_summary.runtime_version
