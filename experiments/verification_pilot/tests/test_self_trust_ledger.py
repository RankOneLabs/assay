"""Historical archive ledger can be rebuilt without the object store."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from verification_pilot.self_trust.ledger import ledger


def test_committed_archive_ledger_is_store_free(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
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
