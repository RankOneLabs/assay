"""Report drift, denominator, cost, and offline measurement contracts."""

from __future__ import annotations

import base64
import json
import shutil
import socket
from pathlib import Path

import pytest
from code_extension.classification import HarnessOrProviderFailure
from code_extension.fixture import PILOT, load_fixture
from code_extension.ledger import AttemptLedger, AttemptRow, EvidenceReference
from code_extension.metrics import measure_attempt, measure_patch, trace_measures
from code_extension.publish import REPORT_MD, render, render_from_ledgers
from code_extension.tests.test_code_extension_ledger import _manifest, _outcome, _plan
from workflow_edit.metrics import install_toolchain

from assay.canonical import digest_bytes
from assay.code_metrics import pins
from assay.execution import Accounting
from assay.store import ObjectStore


def _row(
    cell_id: str, subject: str, arm: str, *, completed: bool,
    accounting: Accounting,
) -> AttemptRow:
    return AttemptRow(
        cell_id, subject, arm, True, completed, False,
        HarnessOrProviderFailure(), None, None,
        EvidenceReference("sha256:" + "a" * 64, None, None, None),
        1.0, accounting,
    )


def test_committed_report_is_exactly_recomputed_evidence() -> None:
    assert REPORT_MD.read_text(encoding="utf-8") == render()
    assert "Descriptive only" in render()
    assert "p-value" not in render() and "adjusted interval" not in render()


def test_run_index_recomputes_attempt_counts_from_retained_objects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import code_extension.publish as publish

    store, plan, authorization = _plan(tmp_path)
    execution_ref, _ = _outcome(store, plan, authorization, success=False, trace={})
    manifest_ref = _manifest(store, plan, authorization, execution_ref, passed=False)
    run_dir = tmp_path / "runs" / "sample"
    shutil.copytree(store.root, run_dir)
    (run_dir / "run.json").write_text(json.dumps({
        "plan_ref": authorization, "manifest_ref": manifest_ref,
        "judgments": {}, "expected_change_paths": {},
    }), encoding="utf-8")
    monkeypatch.setattr(publish, "RUNS", run_dir.parent)
    monkeypatch.setattr(publish, "_fixture_trees", lambda: {
        publish.ScenarioArm(cell.subject_id, cell.arm_id): PILOT / "repository"
        for cell in plan.cells
    })
    report = publish.render()
    assert "| All attempts | 2 | 0 | 0 |" in report
    assert "| oakridge-dbos-context-defaults | 2 | 0 | 0 |" in report


def test_report_counts_incomplete_and_keeps_unpriced_cost_separate() -> None:
    ledger = AttemptLedger((
        _row("cell-a", "oakridge-dbos-context-defaults", "baseline", completed=False,
             accounting=Accounting(coverage="unavailable")),
        _row("cell-b", "oakridge-dbos-context-defaults", "baseline", completed=True,
             accounting=Accounting(coverage="uncertain")),
        _row("cell-c", "oakridge-dbos-stage-pass-through", "central", completed=True,
             accounting=Accounting(amount=1.25, currency="USD", coverage="measured",
                                   basis="retained pricing")),
    ))
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
    ledger = AttemptLedger((
        _row("cell-a", subject, "modular", completed=True, accounting=Accounting()),
        _row("cell-b", subject, "central", completed=True, accounting=Accounting()),
    ))
    report = render_from_ledgers((ledger,))
    assert "Common subjects with an attempt in every arm of their run: 1." in report
    assert "Descriptive only" in report
    assert "p-value" not in report and "adjusted interval" not in report


def test_self_report_is_compared_with_external_result_only() -> None:
    trace = b'''{"turns":[{"tool_calls":[{"name":"read_file","arguments":{"path":"src/a.ts"}}],
        "submission":{"self_assessed_verdict":"complete","checks_performed":"tsc"}}],
        "events":[{"kind":"model_request","turn":1},{"kind":"model_request","turn":1}]}'''
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
    patch_ref = str(store.publish_json({
        "schema_version": "assay-pier-raw-artifact/0.1.0",
        "checksum": digest_bytes(patch), "byte_length": len(patch),
        "content_base64": base64.b64encode(patch).decode("ascii"),
    }))
    row = _row(
        "partial", "oakridge-dbos-context-defaults", "baseline", completed=False,
        accounting=Accounting(coverage="uncertain"),
    )
    row = AttemptRow(
        row.cell_id, row.subject_id, row.arm_id, row.attempted, row.completed, row.passed,
        row.category, row.distinction, row.verdict,
        EvidenceReference(row.reference.manifest_ref, None, patch_ref, None),
        row.duration_seconds, row.accounting,
    )
    measured = measure_attempt(row, store, fixture_tree=PILOT / "repository")
    assert measured.diff is None
    assert measured.cost_amount is None and measured.cost_coverage == "uncertain"


def test_measurement_of_committed_fixture_patch_has_no_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
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
        PILOT / "repository", patch, dependencies=dependencies,
        expected_change_paths=frozenset({"src/domain/json-pointer.ts"}),
    )
    assert result.added_lines > 0
    assert "src/domain/json-pointer.ts" in result.changed_paths
    assert set(result.unnecessary_paths) == set(result.changed_paths) - {
        "src/domain/json-pointer.ts"
    }
