from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft7Validator, Draft202012Validator
from test_execution import execution_fixture
from test_reports import report_config

from assay.canonical import canonical_json, digest_bytes
from assay.cli import main
from assay.execution import RunFailed, RunSucceeded, execute_plan
from assay.models import Arm, StatisticalProfile, StudySnapshot
from assay.planning import compile_plan
from assay.references import object_edges, reference_closure
from assay.report_engine import ReportError, build_report
from assay.reporting import bootstrap_paired, compare_scalar
from assay.schema_export import schema_documents
from assay.schema_validation import schema_validators
from assay.statistical_limits import MAX_BOOTSTRAP_SAMPLES
from assay.store import ObjectStore, verification_session
from assay.verify import export_bundle, verify_bundle, verify_manifest, verify_snapshot


async def _run(store: ObjectStore) -> RunSucceeded:
    fixture = execution_fixture(
        store, subject_ids=("ok",), worker_repeats=1, evaluator_repeats=1, concurrency=1
    )
    result = await execute_plan(**fixture.arguments)
    assert isinstance(result, RunSucceeded), result
    assert verify_manifest(store, str(result.manifest_ref)) == ()
    return result


def _replace(value: Any, replacements: dict[str, str]) -> Any:
    if isinstance(value, str):
        return replacements.get(value, value)
    if isinstance(value, list):
        return [_replace(item, replacements) for item in value]
    if isinstance(value, dict):
        return {key: _replace(item, replacements) for key, item in value.items()}
    return value


def _rewrite(
    store: ObjectStore, result: RunSucceeded, group: str, key: str, record: dict[str, Any]
) -> str:
    """Rehash dependent records, so regressions test semantics, not stale hashes."""
    manifest = result.manifest.model_dump(mode="json")
    original = manifest[group][key]
    replacements = {original: str(store.publish_json(record))}
    for collection in ("execution_records", "evaluation_records", "operating_records"):
        for coordinate, old in manifest[collection].items():
            if old in replacements:
                new = replacements[old]
            else:
                value = _replace(json.loads(store.read_bytes(old)), replacements)
                new = str(store.publish_json(value))
                replacements[old] = new
            manifest[collection][coordinate] = new
    return str(store.publish_json(manifest))


@pytest.mark.parametrize("omitted", ["task", "configuration", "basis", "detail", "mutable"])
async def test_evidence_requires_authoritative_sources(tmp_path: Path, omitted: str) -> None:
    store = ObjectStore(tmp_path)
    result = await _run(store)
    key, ref = next(iter(result.manifest.evaluation_records.items()))
    record = json.loads(store.read_bytes(ref))
    index = {"task": 1, "configuration": 2, "basis": 3, "detail": 4}
    if omitted == "mutable":
        record["source_references"].append("https://mutable.example/latest")
    else:
        record["source_references"].pop(index[omitted])
    root = _rewrite(store, result, "evaluation_records", key, record)
    assert verify_manifest(store, root)
    with pytest.raises(ValueError, match="invalid root"):
        export_bundle(store, root, tmp_path / "export")


@pytest.mark.parametrize("field", ["output_ref", "trace_ref"])
@pytest.mark.parametrize("data", [b"not JSON", b'{ "noncanonical": true }'])
async def test_execution_artifacts_require_canonical_json(
    tmp_path: Path, field: str, data: bytes
) -> None:
    store = ObjectStore(tmp_path)
    result = await _run(store)
    key, ref = next(iter(result.manifest.execution_records.items()))
    record = json.loads(store.read_bytes(ref))
    previous = record[field]
    record[field] = str(store.publish_bytes(data))
    root = _rewrite(store, result, "execution_records", key, record)
    # Align evidence output boundaries too; verification must reject the actual
    # artifact, not merely a boundary mismatch.
    if field == "output_ref":
        manifest = json.loads(store.read_bytes(root))
        replacements = {previous: record[field]}
        for group in ("evaluation_records", "operating_records"):
            for coordinate, old in manifest[group].items():
                new = str(
                    store.publish_json(_replace(json.loads(store.read_bytes(old)), replacements))
                )
                replacements[old] = new
                manifest[group][coordinate] = new
        root = str(store.publish_json(manifest))
    failures = verify_manifest(store, root)
    if data == b"not JSON":
        assert any(f.code == "execution_record" for f in failures)
    else:
        # Parseable noncanonical artifacts now fail at the closure boundary,
        # before per-outcome validation. The error must identify those bytes.
        assert any(
            f.code == "manifest_context" and f"noncanonical JSON at {record[field]}" in f.message
            for f in failures
        )


@pytest.mark.parametrize("attempt", [1, 2, 4])
async def test_partial_accounting_failure_has_consistent_missingness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, attempt: int
) -> None:
    store = ObjectStore(tmp_path)
    fixture = execution_fixture(
        store, subject_ids=("ok",), worker_repeats=1, evaluator_repeats=1, concurrency=1
    )
    original = store.publish_json
    calls = 0

    def fail_once(value: Any) -> Any:
        nonlocal calls
        if (
            isinstance(value, dict)
            and value.get("record_schema") == "paa-operating-record/0.1.0-draft"
        ):
            calls += 1
            if calls == attempt:
                raise OSError("accounting disk fault")
        return original(value)

    monkeypatch.setattr(store, "publish_json", fail_once)
    result = await execute_plan(**fixture.arguments)
    assert isinstance(result, RunFailed), result
    assert result.manifest is not None and result.manifest_ref is not None
    assert result.manifest.status == "incomplete"
    assert any(
        key.startswith(("worker:", "evaluator:")) for key in result.manifest.missing_coordinates
    )
    assert {f.code for f in verify_manifest(store, str(result.manifest_ref))} == {"incomplete_run"}
    if attempt == 4:
        assert (
            len(result.manifest.execution_records) == len(result.manifest.evaluation_records) == 2
        )
        assert len(result.manifest.missing_coordinates) == 1


async def test_export_corruption_is_a_cli_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    store = ObjectStore(tmp_path / "source")
    result = await _run(store)
    store._path(result.manifest_ref).write_bytes(b"tampered")
    monkeypatch.setattr(
        "sys.argv",
        [
            "assay",
            "export",
            str(store.root),
            str(result.manifest_ref),
            str(tmp_path / "export"),
        ],
    )
    assert main() == 1
    captured = capsys.readouterr()
    assert captured.out.startswith("export_failed:")
    assert captured.err == ""


@pytest.mark.parametrize("samples", [MAX_BOOTSTRAP_SAMPLES + 1, 10**20, True, 100.5])
def test_sampling_limits_reject_before_drawing(
    samples: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unexpected(*args: Any, **kwargs: Any) -> None:
        pytest.fail("invalid sample count reached sampler")

    monkeypatch.setattr("assay.reporting._IndexStream", unexpected)
    with pytest.raises(ValueError):
        StatisticalProfile(seed=0, bootstrap_samples=samples)
    with pytest.raises(ValueError):
        bootstrap_paired([1.0], seed=0, samples=samples)
    with pytest.raises(ValueError):
        compare_scalar([], reference="r", candidates=["c"], bootstrap_samples=samples)


def test_sampling_bound_is_in_generated_schema() -> None:
    profile = StatisticalProfile(seed=0, bootstrap_samples=MAX_BOOTSTRAP_SAMPLES)
    schema = json.loads(schema_documents()["assay-report-config.schema.json"])["$defs"][
        "StatisticalProfile"
    ]
    validator = Draft202012Validator(schema)
    validator.validate(profile.model_dump(mode="json"))
    assert not validator.is_valid(
        profile.model_dump(mode="json") | {"bootstrap_samples": MAX_BOOTSTRAP_SAMPLES + 1}
    )


@pytest.mark.parametrize("dialect", [None, "https://json-schema.org/draft/2020-12/schema"])
async def test_schema_default_dialect_matches_resolution(
    tmp_path: Path, dialect: str | None
) -> None:
    store = ObjectStore(tmp_path)
    fixture = execution_fixture(store, subject_ids=("ok",), worker_repeats=1, evaluator_repeats=1)
    document = fixture.snapshot.model_dump(mode="json")
    evaluator = document["evaluators"][0]
    schema: dict[str, Any] = {
        "$id": evaluator["payload_schema"],
        "$ref": "https://paa.dev/paa-evidence-record.schema.json",
        "type": "null",  # draft-07 ignores $ref siblings; 2020-12 applies them.
    }
    if dialect is not None:
        schema["$schema"] = dialect
    evaluator["payload_schema_ref"] = str(store.publish_json(schema))
    snapshot = StudySnapshot.model_validate(document)
    plan = compile_plan(
        snapshot,
        snapshot_ref=str(store.publish_json(document)),
        worker_repeats=1,
        jig_revision="test",
    )
    plan_bytes = canonical_json(plan.model_dump(mode="json"))
    result = await execute_plan(
        **(
            fixture.arguments
            | {
                "snapshot": snapshot,
                "plan_bytes": plan_bytes,
                "authorization": digest_bytes(plan_bytes),
            }
        )
    )
    assert isinstance(result, RunSucceeded), result
    validator = schema_validators(store, snapshot)[evaluator["payload_schema_ref"]]
    assert isinstance(validator, Draft7Validator if dialect is None else Draft202012Validator)
    for ref in result.manifest.evaluation_records.values():
        record = json.loads(store.read_bytes(ref))
        if dialect is None:
            assert "verdict" in record
        else:
            assert record["error_type"] == "InvalidVerdict"
    assert verify_manifest(store, str(result.manifest_ref)) == ()


@pytest.mark.parametrize(
    "drift", [None, "task", "jig_revision", "worker_repeats", "concurrency", "pricing"]
)
async def test_cross_run_compatibility(tmp_path: Path, drift: str | None) -> None:
    store = ObjectStore(tmp_path)
    results = []
    for index in range(2):
        fixture = execution_fixture(
            store, subject_ids=(f"s{index}",), worker_repeats=1, evaluator_repeats=1
        )
        document = fixture.snapshot.model_dump(mode="json")
        if index and drift == "task":
            task = json.loads(store.read_bytes(document["paa_task_ref"]))
            task["version"] += 1
            document["paa_task_ref"] = str(store.publish_json(task))
        if index and drift == "pricing":
            document["pricing_assumptions"] = {"basis": "changed"}
        snapshot = StudySnapshot.model_validate(document)
        plan = compile_plan(
            snapshot,
            snapshot_ref=str(store.publish_json(document)),
            worker_repeats=2 if index and drift == "worker_repeats" else 1,
            jig_revision="changed" if index and drift == "jig_revision" else "test",
            concurrency=2 if index and drift == "concurrency" else 1,
        )
        data = canonical_json(plan.model_dump(mode="json"))
        result = await execute_plan(
            **(
                fixture.arguments
                | {
                    "snapshot": snapshot,
                    "plan_bytes": data,
                    "authorization": digest_bytes(data),
                }
            )
        )
        assert isinstance(result, RunSucceeded), result
        assert verify_manifest(store, str(result.manifest_ref)) == ()
        results.append(result)
    config = report_config(results[0]).model_copy(
        update={
            "manifest_refs": tuple(str(r.manifest_ref) for r in results),
            "record_refs": tuple(
                ref for r in results for ref in r.manifest.evaluation_records.values()
            ),
        }
    )
    if drift is None:
        assert build_report(store, config)["comparisons"][0]["n"] == 2
    else:
        with pytest.raises(ReportError, match="compatibility drift"):
            build_report(store, config)


def test_nested_values_are_owned_frozen_and_serialize_normally(tmp_path: Path) -> None:
    nested = {"list": [{"value": 1}]}
    arm = Arm(id="a", worker={"id": "w", "version": "1"}, intervention=nested)
    original = canonical_json(arm.model_dump(mode="json"))
    nested["list"][0]["value"] = 2
    assert canonical_json(arm.model_dump(mode="json")) == original
    with pytest.raises(TypeError):
        arm.intervention["list"][0]["value"] = 3
    with pytest.raises(TypeError):
        arm.intervention["list"].append(4)
    with pytest.raises(TypeError):
        arm.worker.update(version="changed")
    copied = arm.model_copy(deep=True, update={"conditions": nested})
    nested["list"].append({"value": 9})
    assert len(copied.conditions["list"]) == 1
    with pytest.raises(TypeError):
        copied.conditions.clear()
    fixture = execution_fixture(ObjectStore(tmp_path))
    for mapping in (
        fixture.snapshot.evaluators[0].configuration,
        fixture.snapshot.evaluators[0].identity,
        fixture.snapshot.pricing_assumptions,
    ):
        with pytest.raises(TypeError):
            mapping["unexpected"] = True
    dumped = arm.model_dump(mode="json")
    dumped["intervention"]["list"][0]["value"] = 99
    assert canonical_json(arm.model_dump(mode="json")) == original


async def test_hash_looking_free_text_and_explicit_extension_edges(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path / "source")
    fixture = execution_fixture(store, subject_ids=("ok",), worker_repeats=1)
    document = fixture.snapshot.model_dump(mode="json")
    document["subjects"][0]["label"] = "sha256:" + "0" * 64
    task = json.loads(store.read_bytes(document["paa_task_ref"]))
    task["description"] = "sha256:not-an-address"
    document["paa_task_ref"] = str(store.publish_json(task))
    leaf = str(store.publish_bytes(b"binary extension"))
    extension = str(store.publish_json({"assay_object_refs": [leaf]}))
    document["arms"][0]["intervention"]["assay_object_refs"] = [extension]
    snapshot = StudySnapshot.model_validate(document)
    plan = compile_plan(
        snapshot,
        snapshot_ref=str(store.publish_json(document)),
        worker_repeats=1,
        jig_revision="test",
    )
    data = canonical_json(plan.model_dump(mode="json"))
    result = await execute_plan(
        **(
            fixture.arguments
            | {
                "snapshot": snapshot,
                "plan_bytes": data,
                "authorization": digest_bytes(data),
            }
        )
    )
    assert isinstance(result, RunSucceeded), result
    report = report_config(result)
    from assay.report_engine import persist_report

    root = str(persist_report(store, report))
    closure = reference_closure(store, (root,))
    assert {leaf, extension} <= closure
    assert document["subjects"][0]["label"] not in closure
    bundle = export_bundle(store, root, tmp_path / "export")
    assert verify_bundle(bundle, root) == ()
    bundle._path(leaf).unlink()
    assert verify_bundle(bundle, root)


def test_arbitrary_payload_is_not_reinterpreted_as_governed_document(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    fake = str(
        store.publish_json(
            {
                "schema_version": "assay-execution-plan/0.1.0",
                "snapshot_ref": "sha256:" + "0" * 64,
                "$ref": "sha256:" + "1" * 64,
            }
        )
    )
    root = str(store.publish_json({"assay_object_refs": [fake]}))
    assert reference_closure(store, (root,)) == {root, fake}


def test_schema_edges_ignore_literals_but_follow_hash_refs(tmp_path: Path) -> None:
    schema = {
        "$id": "urn:test",
        "default": {"assay_object_refs": ["not-a-ref"]},
        "examples": [{"$ref": "sha256:" + "0" * 64}],
        "properties": {"value": {"$ref": "sha256:" + "1" * 64 + "#/$defs/value"}},
    }
    assert object_edges(schema, "schema") == {("sha256:" + "1" * 64, "schema")}


@pytest.mark.parametrize("modern", [False, True])
def test_schema_reference_keywords_follow_the_declared_dialect(modern: bool) -> None:
    ref = "sha256:" + "1" * 64
    schema = {"$id": "urn:test", "$dynamicRef": ref}
    if modern:
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    assert object_edges(schema, "schema") == ({(ref, "schema")} if modern else set())


@pytest.mark.parametrize("value", ["sha256:" + "0" * 64, ["https://mutable.example"], [1]])
def test_extension_reference_convention_is_validated(value: Any) -> None:
    with pytest.raises((TypeError, ValueError)):
        object_edges({"assay_object_refs": value}, "data")


@pytest.mark.parametrize("data", [b"not JSON", b'{ "subject": "ok" }'])
async def test_invalid_input_artifact_fails_before_execution(tmp_path: Path, data: bytes) -> None:
    store = ObjectStore(tmp_path)
    fixture = execution_fixture(store, subject_ids=("ok",), worker_repeats=1)
    document = fixture.snapshot.model_dump(mode="json")
    ref = str(store.publish_bytes(data))
    document["realizations"][0].update(digest=ref, artifact_ref=ref)
    snapshot = StudySnapshot.model_validate(document)
    with pytest.raises(ValueError):
        verify_snapshot(store, snapshot)
    plan = compile_plan(
        snapshot,
        snapshot_ref=str(store.publish_json(document)),
        worker_repeats=1,
        jig_revision="test",
    )
    plan_bytes = canonical_json(plan.model_dump(mode="json"))
    result = await execute_plan(
        **(
            fixture.arguments
            | {
                "snapshot": snapshot,
                "plan_bytes": plan_bytes,
                "authorization": digest_bytes(plan_bytes),
            }
        )
    )
    assert isinstance(result, RunFailed)
    assert result.manifest is None


async def test_evaluation_failure_trace_must_be_json(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    fixture = execution_fixture(store, subject_ids=("fails",), worker_repeats=1)
    result = await execute_plan(**fixture.arguments)
    assert isinstance(result, RunSucceeded)
    key, ref = next(iter(result.manifest.evaluation_records.items()))
    record = json.loads(store.read_bytes(ref))
    record["trace_ref"] = str(store.publish_bytes(b"invalid trace"))
    root = _rewrite(store, result, "evaluation_records", key, record)
    assert any(f.code == "evaluation_record" for f in verify_manifest(store, root))


def test_shared_content_is_traversed_in_each_referring_role(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path)
    child = str(
        store.publish_json(
            {
                "schema_version": "assay-execution-plan/0.1.0",
                "snapshot_ref": "sha256:" + "0" * 64,
            }
        )
    )
    root = str(store.publish_json({"assay_object_refs": [child]}))
    session = verification_session(store)
    assert reference_closure(session, (root,)) == {root, child}
    with pytest.raises(FileNotFoundError):
        reference_closure(session, (child,))


@pytest.mark.parametrize(
    "mutation",
    [
        lambda d: d.__setitem__("new", 1),
        lambda d: d.__delitem__("x"),
        lambda d: d.__ior__({"new": 1}),
        lambda d: d.clear(),
        lambda d: d.pop("x"),
        lambda d: d.popitem(),
        lambda d: d.setdefault("new", 1),
        lambda d: d.update(new=1),
        lambda d: d.__init__({"new": 1}),
    ],
)
def test_frozen_mapping_mutators(mutation: Any) -> None:
    arm = Arm(id="a", worker={"id": "w", "version": "1"}, intervention={"x": 1})
    with pytest.raises(TypeError):
        mutation(arm.intervention)
    assert arm.intervention == {"x": 1}


@pytest.mark.parametrize(
    "mutation",
    [
        lambda s: s.__setitem__(slice(None), [2]),
        lambda s: s.__delitem__(0),
        lambda s: s.__iadd__([2]),
        lambda s: s.__imul__(2),
        lambda s: s.append(2),
        lambda s: s.clear(),
        lambda s: s.extend([2]),
        lambda s: s.insert(0, 2),
        lambda s: s.pop(),
        lambda s: s.remove(1),
        lambda s: s.reverse(),
        lambda s: s.sort(),
        lambda s: s.__init__([2]),
    ],
)
def test_frozen_sequence_mutators(mutation: Any) -> None:
    arm = Arm(id="a", worker={"id": "w", "version": "1"}, intervention={"x": [1]})
    with pytest.raises(TypeError):
        mutation(arm.intervention["x"])
    assert arm.intervention["x"] == [1]
