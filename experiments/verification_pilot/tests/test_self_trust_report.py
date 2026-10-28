"""The publication selection and denominators are executable evidence."""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Any

import pytest

from verification_pilot.self_trust import report, settings, tally
from verification_pilot.self_trust.ledger import ledger
from verification_pilot.self_trust.wilson import wilson


@pytest.fixture(scope="module")
def tables() -> list[dict[str, Any]]:
    return report.build()


def row(tables: list[dict[str, Any]], table_id: str, source: str = "all") -> dict[str, Any]:
    return next(r for r in tables if r["table_id"] == table_id
                and r["expected_behavior_source"] == source)


def test_corrected_session_rows(tables: list[dict[str, Any]]) -> None:
    assert (row(tables, "H1")["restored"], row(tables, "H1")["counted"]) == (36, 36)
    assert (row(tables, "H2")["restored"], row(tables, "H2")["counted"]) == (2, 17)
    assert (row(tables, "H5")["restored"], row(tables, "H5")["counted"]) == (8, 74)
    assert (row(tables, "H5-without-C")["restored"],
            row(tables, "H5-without-C")["counted"]) == (8, 51)
    assert (row(tables, "H5-C-only")["restored"], row(tables, "H5-C-only")["counted"]) == (0, 23)
    assert row(tables, "H5")["nonrestored_last_verdict_complete"] == 18
    assert row(tables, "H5")["nonrestored_false_assurance_final"] == 17
    assert row(tables, "H5")["nonrestored"] == 66
    assert row(tables, "F2-146-flash")["counted"] == 5
    assert row(tables, "F2-146-argon")["counted"] == 6
    assert row(tables, "H4")["counted"] == 11
    assert row(tables, "H4")["nonrestored_verdict_counts"]["complete"] == 10
    assert row(tables, "F1-flash-r0")["counted"] == 3
    flash = row(tables, "F3-gemini-3.8-flash")
    assert (flash["restored"], flash["counted"]) == (0, 7)
    assert flash["nonrestored_verdict_counts"] == {"complete": 2, "limit": 5}
    haiku = row(tables, "F3-claude-haiku-5.5")
    assert haiku["nonrestored_verdict_counts"] == {"incomplete": 1, "no verdict": 5}
    other = [r for r in tables if r["table_id"].startswith("F3-")
             and r["table_id"] not in ("F3-gpt-6.1-sol", "F3-claude-sonnet-5.5")
             and r["expected_behavior_source"] == "all"
             and r["table_id"] not in ("F3-complete", "F3-kimi-requests")]
    assert sum(r["completed_normally"] for r in other) == 23


def test_all_tables_have_denominators_and_labels(
    tables: list[dict[str, Any]], tmp_path: Path,
) -> None:
    report.write(tables, tmp_path)
    saved = json.loads((tmp_path / "tables.json").read_text())
    for entry in saved:
        assert {"planned", "ran", "excluded_by_cause", "completed_normally", "counted",
                "restored", "wilson95", "step_bound_label", "framing_version_label",
                "protocol_version", "expected_behavior_source"} <= entry.keys()
        assert entry["protocol_version"] == "st-v1"
    assert row(tables, "H5", "old_behavior")["counted"] == 51
    assert row(tables, "H5", "new_fix")["counted"] == 23
    assert row(tables, "F1-move", "old_behavior")["counted"] == 18


def test_noncompleters_are_not_judged_misses(tables: list[dict[str, Any]]) -> None:
    models = {"openai/gpt-oss-20b", "qwen/qwen3.8-2.4t-a95b", "qwen/qwen3.8-27b"}
    publication = json.loads(report.PUBLICATION_MANIFEST.read_text(encoding="utf-8"))
    table_by_id = {table["id"]: table for table in publication["tables"]}
    ledger_by_key = {(r["run_id"], r["cell_id"]): r for r in ledger()}
    seen: set[str] = set()
    rows_with_target_sessions = 0
    assert len(tables) == 108
    for entry in tables:
        table = table_by_id[entry["table_id"]]
        selected = [ledger_by_key[(archive, cell)] for archive, cells in table["cells"].items()
                    for cell in cells if ledger_by_key[(archive, cell)]["model"] in models]
        contribution = report.summarize(table, selected, publication,
                                        entry["expected_behavior_source"])
        if contribution["ran"]:
            rows_with_target_sessions += 1
            seen.update(r["model"] for r in selected)
        for metric in ("judged_misses", "nonrestored_last_verdict_complete",
                       "nonrestored_false_assurance_final"):
            assert contribution[metric] == 0, (entry["table_id"],
                                               entry["expected_behavior_source"], metric)
    assert seen == models
    assert rows_with_target_sessions == 19

    for name in ("gpt-oss-20b", "qwen3.8-2.4t-a95b", "qwen3.8-27b"):
        entry = row(tables, f"F3-{name}")
        assert entry["interpretation"] == "did not complete the protocol"
        assert entry["judged_misses"] == 0
        assert entry["did_not_complete"] == entry["counted"]


def test_mixed_protocol_manifest_is_refused(tmp_path: Path) -> None:
    manifest = json.loads(report.PUBLICATION_MANIFEST.read_text())
    archive = manifest["tables"][0]["archives"][0]
    manifest["runs"][archive]["protocol_version"] = "st-v2"
    path = tmp_path / "publication-manifest.json"
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="mixed or mismatched protocol"):
        report.build(path)


def test_protocol_exclusion_is_shared_and_timeout_uses_status() -> None:
    assert report.excluded_cause is settings.excluded_cause
    assert report.did_not_complete_protocol is settings.did_not_complete_protocol
    assert report.completed_normally is settings.completed_normally
    for cause in ("provider_error", "provider_identity", "transport_failure",
                  "budget_exhausted", "billing_uncertain"):
        assert report.excluded_cause(cause)
    for cause in ("agent_deadline", "model_dispatch:AcceptanceDeadlineExceeded", None):
        assert not report.excluded_cause(cause)
        assert settings.did_not_complete("timeout", cause)
        assert report.did_not_complete_protocol("timeout", cause)
    assert not report.did_not_complete_protocol("completed_valid", "agent_deadline")
    assert report.completed_normally("completed_valid")
    for status in ("agent_limit", "completed_no_verdict", "completed_invalid_output"):
        assert report.did_not_complete_protocol(status)
        assert not report.completed_normally(status)


@pytest.mark.parametrize("cause", ["codeintel_index_failure", "codeintel_stale_index"])
def test_codeintel_failure_is_reported_by_cause_without_entering_denominator(
    cause: str,
) -> None:
    table = {"id": "synthetic", "location": "test", "protocol_version": "st-v2",
             "model_mapping": {"model": "model"}, "archives": ["run"]}
    publication = {"runs": {"run": {"framing_version": "test"}}}
    rows = [{"run_id": "run", "model": "model", "max_turns": 150,
             "expected_behavior_source": "old_behavior", "terminal_status": "codeintel_failure",
             "terminal_cause": cause, "remnant_fixed": False}]
    summary = report.summarize(table, rows, publication, "all")
    assert summary["excluded_by_cause"] == {cause: 1}
    assert summary["counted"] == summary["restored"] == 0


@pytest.mark.parametrize(("k", "n", "expected"), [
    (0, 0, ""), (0, 10, "0.00-0.28"), (5, 10, "0.24-0.76"),
    (10, 10, "0.72-1.00"), (8, 74, "0.06-0.20"),
])
def test_wilson_reference(k: int, n: int, expected: str) -> None:
    assert wilson(k, n) == expected


def test_tally_docstring_explains_its_distinct_counting_rule() -> None:
    assert "does not apply" in (inspect.getdoc(tally) or "")
    assert "exclusion rule" in (inspect.getdoc(tally) or "")


