"""Report drift, denominator, cost, and offline measurement contracts."""

from __future__ import annotations

import base64
import csv
import json
import shutil
import socket
from pathlib import Path

import pytest
from code_extension.classification import HarnessOrProviderFailure
from code_extension.fixture import PILOT, load_fixture, materialize
from code_extension.ledger import AttemptLedger, AttemptRow, EvidenceReference
from code_extension.metrics import measure_attempt, measure_patch, trace_measures
from code_extension.publish import REPORT_MD, render, render_archive, render_from_ledgers
from code_extension.study import load_pilot_study_fixture
from code_extension.tests.test_code_extension_ledger import _manifest, _outcome, _plan
from code_extension.tests.test_code_extension_regrade import _forbid_model_constructors
from code_extension.tests.test_code_extension_study import _two_arm_fixture
from workflow_edit.metrics import install_toolchain

from assay.canonical import digest_bytes
from assay.code_metrics import pins
from assay.execution import Accounting
from assay.store import ObjectStore


def _row(
    cell_id: str,
    subject: str,
    arm: str,
    *,
    completed: bool,
    accounting: Accounting,
) -> AttemptRow:
    return AttemptRow(
        cell_id,
        subject,
        arm,
        True,
        completed,
        False,
        HarnessOrProviderFailure(),
        None,
        None,
        EvidenceReference("sha256:" + "a" * 64, None, None, None),
        1.0,
        accounting,
    )


def test_committed_report_is_exactly_recomputed_evidence() -> None:
    assert REPORT_MD.read_text(encoding="utf-8") == render()
    assert "Descriptive only" in render()
    assert "p-value" not in render() and "adjusted interval" not in render()


def test_empty_archive_reproduces_committed_report_and_fixed_ledger(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "empty"
    archive.mkdir()
    paths = render_archive(archive, tmp_path / "out")
    first = [path.read_bytes() for path in paths]
    assert paths[0].read_bytes() == REPORT_MD.read_bytes()
    assert paths[1].read_text().startswith("attempt,retry_of,scenario,arm,")
    assert paths[2].read_text() == "[]\n"
    assert [path.read_bytes() for path in render_archive(archive, tmp_path / "out")] == first


def test_committed_qualification_and_scripted_archive_reproduce_and_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A model-free bridge submission can be reported and exported offline."""
    from code_extension.fixtures import load_scenario
    from code_extension.probe import _run_script, _scripted_client
    from code_extension.study import load_qualified_study_fixture, plan_study
    from code_extension.tests.test_code_extension_study import PlanWorker
    from workflow_edit.tests.test_workflow_edit_bridge import FakeSandbox

    from assay.canonical import canonical_json
    from assay.fixture_manifest import FixtureManifestV3
    from assay.investigations.workflow_correctness import (
        DockerWorkflowRunner,
        WorkflowRunnerSettings,
    )
    from assay.models import (
        ExecutionCeiling,
        ExecutionOutcome,
        RunManifest,
        RuntimeProfile,
        parse_execution_plan,
    )
    from assay.verify import export_bundle, verify_bundle

    fixture = load_scenario("dispatch-handler")
    manifest_path = (
        Path(__file__).resolve().parents[1]
        / "fixtures" / "dispatch-handler" / "qualification" / "manifest.json"
    )
    manifest_bytes = manifest_path.read_bytes()
    manifest = FixtureManifestV3.model_validate_json(manifest_bytes)
    image = manifest.observed_runtime_image_digest
    source = ObjectStore(tmp_path / "source")
    qualified = load_qualified_study_fixture(
        source, {"dispatch-handler": digest_bytes(manifest_bytes)}, image=image
    )
    prepared = plan_study(
        source, qualified, workers={"baseline": PlanWorker()},
        runner=DockerWorkflowRunner(WorkflowRunnerSettings(image=image, toolchain="bun")),
        runtime=RuntimeProfile(
            id="pier", version="scripted", configuration_ref=str(source.publish_json({"v": 1}))
        ),
        image=image, routing_digest=manifest.routing_config_digest, repeats=1,
        ceiling=ExecutionCeiling(max_cells=1, max_wall_time_seconds=600, max_fleet_occupancy=1),
    )
    plan = parse_execution_plan(json.loads(prepared.plan_bytes))
    assert len(plan.cells) == 1

    monkeypatch.setattr("code_extension.bridge.observed_image_digest", lambda _image: image)
    monkeypatch.setattr("code_extension.probe.observed_image_digest", lambda _image: image)
    path = "src/domain/run-event.ts"
    client = _scripted_client(
        fixture, manifest, "scripted-image", tmp_path / "trial",
        [("write_file", {"path": path,
                         "content": fixture.repository[path] + "\n// offline rehearsal\n"})],
    )
    client.sandbox_factory = FakeSandbox
    result, trajectory, _, _ = _run_script(client, fixture, "scripted-image")
    assert [call["name"] for turn in trajectory["turns"] for call in turn["tool_calls"]] == [
        "write_file", "submit_output"
    ]
    def retain_artifact(name: str) -> str:
        data = result.artifacts[name]
        return str(source.publish_json({
            "schema_version": "assay-pier-raw-artifact/0.1.0",
            "path": name, "checksum": digest_bytes(data), "byte_length": len(data),
            "content_base64": base64.b64encode(data).decode(),
        }))

    output_ref = str(source.publish_json({
        "patch_ref": retain_artifact("candidate.patch"),
        "result_ref": retain_artifact("result.json"),
        "raw_trajectory_ref": retain_artifact("trajectory.json"),
    }))
    cell = plan.cells[0]
    execution = ExecutionOutcome(
        run_id="scripted-rehearsal", plan_ref=prepared.authorization,
        started_at="2026-10-31T00:00:00Z", completed_at="2026-10-31T00:00:01Z",
        coordinate=cell, status="succeeded", input_ref=cell.realization_ref,
        output_ref=output_ref,
        trace_ref=str(source.publish_bytes(canonical_json({"scripted": True}))),
    )
    execution_ref = str(source.publish_json(execution.model_dump(mode="json")))
    run_manifest = RunManifest(
        run_id="scripted-rehearsal", plan_ref=prepared.authorization, status="incomplete",
        execution_records={cell.id: execution_ref}, evaluation_records={},
        missing_coordinates=tuple(sorted((
            f"worker:{cell.id}", *(item.id for item in plan.evaluations)
        ))),
    )
    manifest_ref = str(source.publish_json(run_manifest.model_dump(mode="json")))
    archive = tmp_path / "archive"
    run_dir = archive / "runs" / "scripted-rehearsal"
    shutil.copytree(source.root, run_dir)
    (run_dir / "run.json").write_text(json.dumps({
        "plan_ref": prepared.authorization, "manifest_ref": manifest_ref,
        "judgments": {}, "expected_change_paths": {fixture.subject_id: [path]},
    }), encoding="utf-8")

    dependencies = install_toolchain(tmp_path / "dependencies", offline=True)
    monkeypatch.setattr("workflow_edit.metrics.dependencies_directory", lambda _lock: dependencies)
    _forbid_model_constructors(monkeypatch)
    paths = render_archive(archive, tmp_path / "rendered")
    first = tuple(item.read_bytes() for item in paths)
    assert first == tuple(
        item.read_bytes() for item in render_archive(archive, tmp_path / "rendered")
    )
    rows = json.loads(paths[2].read_text(encoding="utf-8"))
    assert len(rows) == 1 and rows[0]["scenario"] == fixture.subject_id
    assert "| All attempts | 1 |" in paths[0].read_text(encoding="utf-8")

    bundle = export_bundle(ObjectStore(run_dir), manifest_ref, tmp_path / "bundle")
    assert {failure.code for failure in verify_bundle(bundle, manifest_ref)} <= {"incomplete_run"}
    object_path = bundle._path(manifest_ref)
    object_path.write_bytes(b"tampered")
    assert any(failure.code != "incomplete_run" for failure in verify_bundle(bundle, manifest_ref))


def test_archive_ledger_keeps_undispatched_coordinate_as_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, plan, authorization = _plan(tmp_path / "source")
    fixture = _two_arm_fixture(store, load_pilot_study_fixture(store))
    archive = tmp_path / "archive"
    fixture_dir = archive / "fixtures" / "two-arm"
    qualification_dir = fixture_dir / "qualification"
    qualification_dir.mkdir(parents=True)
    (qualification_dir / "manifest.json").write_text(
        fixture.manifest.model_dump_json(), encoding="utf-8"
    )
    for arm_id, repository in fixture.scenarios[0].realizations.items():
        materialize(fixture_dir / "repository" / arm_id, repository)

    execution_ref, _ = _outcome(store, plan, authorization, success=False, trace={})
    manifest_ref = _manifest(store, plan, authorization, execution_ref, passed=False)
    run_dir = archive / "runs" / "sample"
    shutil.copytree(store.root, run_dir)
    (run_dir / "run.json").write_text(
        json.dumps(
            {
                "plan_ref": authorization,
                "manifest_ref": manifest_ref,
                "judgments": {},
                "expected_change_paths": {},
                "retry_of": {plan.cells[1].id: f"run:{plan.cells[0].id}"},
            }
        ),
        encoding="utf-8",
    )

    _forbid_model_constructors(monkeypatch)
    markdown_path, csv_path, json_path = render_archive(archive, tmp_path / "out")
    entries = json.loads(json_path.read_text(encoding="utf-8"))
    with csv_path.open(newline="", encoding="utf-8") as stream:
        csv_entries = list(csv.DictReader(stream))
    assert csv_entries == entries
    assert len(entries) == len(plan.cells) == 2
    missing = [entry for entry in entries if entry["dispatched"] == "no"]
    assert len(missing) == 1
    assert missing[0]["planned"] == "yes"
    assert missing[0]["missing"] == "yes"
    assert missing[0]["retry_of"] == f"run:{plan.cells[0].id}"
    assert next(entry for entry in entries if entry["dispatched"] == "yes")["retry_of"] == "none"
    for name in ("external_verdict", "duration_seconds", "cost", "tool_calls"):
        assert missing[0][name] == "unavailable"
    report = markdown_path.read_text(encoding="utf-8")
    assert "| All attempts | 2 | 0 | 0 |" in report
    outcomes = report.split("## Scenario outcomes", 1)[1].split(
        "## Terminal causes", 1
    )[0]
    scenario = next(
        line for line in outcomes.splitlines()
        if line.startswith("| oakridge-dbos-context-defaults |")
    )
    cells = [cell.strip() for cell in scenario.strip("|").split("|")]
    assert cells[:4] == ["oakridge-dbos-context-defaults", "1", "0", "1"]
    assert cells[4].startswith("0/1 ")
    assert cells[-2:] == ["0", "1"]


def test_run_index_recomputes_attempt_counts_from_retained_objects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import code_extension.publish as publish

    store, plan, authorization = _plan(tmp_path)
    execution_ref, _ = _outcome(store, plan, authorization, success=False, trace={})
    manifest_ref = _manifest(store, plan, authorization, execution_ref, passed=False)
    run_dir = tmp_path / "runs" / "sample"
    shutil.copytree(store.root, run_dir)
    (run_dir / "run.json").write_text(
        json.dumps(
            {
                "plan_ref": authorization,
                "manifest_ref": manifest_ref,
                "judgments": {},
                "expected_change_paths": {},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(publish, "RUNS", run_dir.parent)
    monkeypatch.setattr(
        publish,
        "_fixture_trees",
        lambda: {
            publish.ScenarioArm(cell.subject_id, cell.arm_id): PILOT / "repository"
            for cell in plan.cells
        },
    )
    report = publish.render()
    assert "| All attempts | 2 | 0 | 0 |" in report
    assert "| oakridge-dbos-context-defaults | 2 | 0 | 0 |" in report


def test_report_counts_incomplete_and_keeps_unpriced_cost_separate() -> None:
    ledger = AttemptLedger(
        (
            _row(
                "cell-a",
                "oakridge-dbos-context-defaults",
                "baseline",
                completed=False,
                accounting=Accounting(coverage="unavailable"),
            ),
            _row(
                "cell-b",
                "oakridge-dbos-context-defaults",
                "baseline",
                completed=True,
                accounting=Accounting(coverage="uncertain"),
            ),
            _row(
                "cell-c",
                "oakridge-dbos-stage-pass-through",
                "central",
                completed=True,
                accounting=Accounting(
                    amount=1.25, currency="USD", coverage="measured", basis="retained pricing"
                ),
            ),
        )
    )
    report = render_from_ledgers((ledger,))
    assert "| All attempts | 3 | 2 | 0 |" in report
    assert "| oakridge-dbos-context-defaults | 2 | 1 | 0 |" in report
    assert "| baseline | 0 | 1 | 1 | unpriced |" in report
    assert "| central | 1 | 0 | 0 | 1.2500 USD |" in report
    assert "| oakridge-dbos-pointer-root | 0 | 0 | 0 |" in report
    assert "Descriptive only" in report
    assert "p-value" not in report and "adjusted interval" not in report
    assert "0.0000" not in report


def test_one_common_subject_is_descriptive_only() -> None:
    subject = "oakridge-dbos-stage-pass-through"
    ledger = AttemptLedger(
        (
            _row("cell-a", subject, "modular", completed=True, accounting=Accounting()),
            _row("cell-b", subject, "central", completed=True, accounting=Accounting()),
        )
    )
    report = render_from_ledgers((ledger,))
    assert "Common subjects with an attempt in every arm of a multi-arm run: 1." in report
    assert "Descriptive only" in report
    assert "p-value" not in report and "adjusted interval" not in report


def test_single_arm_run_is_not_pair_eligible_with_ten_subjects() -> None:
    ledger = AttemptLedger(
        tuple(
            _row(
                f"cell-{index}",
                f"subject-{index}",
                "baseline",
                completed=True,
                accounting=Accounting(),
            )
            for index in range(10)
        )
    )
    report = render_from_ledgers((ledger,))
    assert "| All attempts | 10 | 10 | 0 |" in report
    assert "Common subjects with an attempt in every arm of a multi-arm run: 0." in report
    assert "Descriptive only" in report
    assert "Paired inference is eligible" not in report


def test_self_report_is_compared_with_external_result_only() -> None:
    trace = b"""{"turns":[{"tool_calls":[{"name":"read_file","arguments":{"path":"src/a.ts"}}],
        "submission":{"self_assessed_verdict":"complete","checks_performed":"tsc"}}],
        "events":[{"kind":"model_request","turn":1},{"kind":"model_request","turn":1}]}"""
    ungraded = trace_measures(trace, passed=None)
    assert ungraded.self_assessed_verdict == "complete"
    assert ungraded.self_report_agrees is None
    graded = trace_measures(trace, passed=False)
    assert graded.self_report_agrees is False
    assert graded.files_inspected == ("src/a.ts",)
    assert graded.retries == 1


def test_invalid_partial_patch_keeps_attempt_and_unpriced_coverage(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path / "store")
    patch = b"not a patch"
    patch_ref = str(
        store.publish_json(
            {
                "schema_version": "assay-pier-raw-artifact/0.1.0",
                "checksum": digest_bytes(patch),
                "byte_length": len(patch),
                "content_base64": base64.b64encode(patch).decode("ascii"),
            }
        )
    )
    row = _row(
        "partial",
        "oakridge-dbos-context-defaults",
        "baseline",
        completed=False,
        accounting=Accounting(coverage="uncertain"),
    )
    row = AttemptRow(
        row.cell_id,
        row.subject_id,
        row.arm_id,
        row.attempted,
        row.completed,
        row.passed,
        row.category,
        row.distinction,
        row.verdict,
        EvidenceReference(row.reference.manifest_ref, None, patch_ref, None),
        row.duration_seconds,
        row.accounting,
    )
    measured = measure_attempt(row, store, fixture_tree=PILOT / "repository")
    assert measured.diff is None
    assert measured.cost_amount is None and measured.cost_coverage == "uncertain"


def test_measurement_of_committed_fixture_patch_has_no_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Dependency installation is a separate, locked, offline preparation step.
    dependencies = install_toolchain(tmp_path / "dependencies", offline=True)
    monkeypatch.setattr(pins, "NODE_TOOLS", tmp_path / "node-tools")
    pins.install_node_tools(offline=True)
    blocker = tmp_path / "deny-network.cjs"
    blocker.write_text(
        'const net = require("node:net");\n'
        'net.Socket.prototype.connect = function () { throw new Error("network disabled"); };\n'
    )
    monkeypatch.setenv("NODE_OPTIONS", f"--require={blocker}")

    def deny(*args: object, **kwargs: object) -> None:
        raise AssertionError("network disabled")

    monkeypatch.setattr(socket.socket, "connect", deny)
    patch = load_fixture().arms[0].reference_patch.encode("utf-8")
    result = measure_patch(
        PILOT / "repository",
        patch,
        dependencies=dependencies,
        expected_change_paths=frozenset({"src/domain/json-pointer.ts"}),
    )
    assert result.added_lines > 0
    assert "src/domain/json-pointer.ts" in result.changed_paths
    assert set(result.unnecessary_paths) == set(result.changed_paths) - {
        "src/domain/json-pointer.ts"
    }
