"""Historical archive ledger can be rebuilt without the object store."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from verification_pilot.run import _terminal_fields
from verification_pilot.self_trust.ledger import FIELDS, cell_row, ledger, terminal
from verification_pilot.self_trust.tally import cell_rows


@pytest.mark.parametrize("cause", ["codeintel_index_failure", "codeintel_stale_index"])
def test_codeintel_failure_has_its_own_terminal_status(cause: str) -> None:
    assert terminal("failed", cause, None, None) == "codeintel_failure"
    assert _terminal_fields({}, {"events": [{"kind": "stopped", "cause": cause}]},
                            "failed") == ("codeintel_failure", cause)


def test_ledger_and_tally_publish_broad_read_and_query_errors(tmp_path: Path) -> None:
    traces = tmp_path / "traces"
    traces.mkdir()
    cell = "refactor-own_a-remnant_a:st-native:w0"
    entry = {"status": "succeeded", "trajectory": "trajectory.json",
             "worker_trace": "worker.json", "measures": "measures.json"}
    query = {"name": "codeintel_query", "exit_code": 0, "returned_text": "exit=0\n{}"}
    error = {"name": "codeintel_query", "exit_code": None,
             "returned_text": "error: codeintel_query_timeout"}
    trajectory = {"events": [], "turns": [{"turn": "T1", "tool_calls": [query, error]}]}
    measures = [
        {"turn": "T1", "name": "module_read", "result": {"value": False}},
        {"turn": "T1", "name": "module_read_any", "result": {"value": True}},
    ]
    for filename, value in (("trajectory.json", trajectory), ("worker.json", {}),
                            ("measures.json", measures)):
        (traces / filename).write_text(json.dumps(value), encoding="utf-8")
    (tmp_path / "index.json").write_text(json.dumps({cell: entry}), encoding="utf-8")
    row = cell_row(tmp_path, cell, entry, {})
    assert [row[f"module_read_any_t{turn}"] for turn in (1, 2, 3)] == [True, None, None]
    assert row["module_read_t1"] is False
    assert row["codeintel_query_count"] == 2
    assert row["codeintel_query_error_count"] == 1
    assert json.loads(row["codeintel_query_error_causes"]) == ["codeintel_query_timeout"]
    assert {"module_read_any_t1", "module_read_any_t2", "module_read_any_t3",
            "codeintel_query_count", "codeintel_query_error_count",
            "codeintel_query_error_causes"} <= set(FIELDS)
    tally_row = cell_rows(tmp_path)[0]
    assert tally_row["read_omission_file"] == [False, None, None]
    assert tally_row["module_read_any"] == [True, None, None]


def test_committed_archive_ledger_is_store_free(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    assert FIELDS[FIELDS.index("tools_sha256"):FIELDS.index("tools_sha256") + 3] == [
        "tools_sha256", "tools_t1_sha256", "tools_t2_t3_sha256",
    ]
    monkeypatch.setenv("HOME", str(tmp_path))
    rows = ledger()
    assert len(rows) == 362
    assert Counter(row["terminal_status"] for row in rows) == {
        "completed_valid": 144,
        "completed_no_verdict": 23,
        "completed_invalid_output": 6,
        "provider_error": 17,
        "budget_cut": 17,
        "agent_limit": 28,
        "timeout": 9,
        "not_run": 118,
    }
    assert sum(row["terminal_status"] != "not_run" for row in rows) == 244
    assert all(row["model"] and row["protocol_version"] == "st-v1" for row in rows)
    assert all(row["plan_resolved"] for row in rows)
