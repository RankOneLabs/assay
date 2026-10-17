"""SMOKE.md numbers are recomputed from evidence, failures included."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest

from assay.canonical import digest_bytes
from workflow_edit.publish import (
    SMOKE_MD,
    cell_metrics,
    correctness_metrics,
    failure_diagnosis,
    hosted_worst_case,
    probe_rows,
    quantile,
    render,
    render_original,
    render_regraded,
    stop_cause,
)
from workflow_edit.qualify import EVIDENCE, read_evidence
from workflow_edit.settings import Part1AgentSettings


def _turn(turn: int, prompt: int, completion: int, *, finish: str = "tool_calls") -> dict[str, Any]:
    return {
        "kind": "model_request", "turn": turn, "prompt_tokens": prompt,
        "completion_tokens": completion, "finish_reason": finish,
        "request_bytes": prompt * 4, "queue_latency_seconds": 0.1,
        "time_from_acceptance_seconds": completion / 50, "worker_model": "/m",
        "billing": "uncertain",
    }


def _cell(outcome: dict[str, Any], events: list[dict[str, Any]], seconds: float) -> dict[str, Any]:
    return {"outcome": outcome, "seconds": seconds, "trajectory": {"events": events}}


CELLS = {
    "s:mess-00:w0": _cell({"kind": "candidate"}, [
        _turn(1, 1000, 300), _turn(2, 3000, 8192, finish="length"),
        {"kind": "cgroup_peaks", "memory_peak_bytes": 50, "pids_peak": 9, "oom_kills": 0,
         "workspace_free_kb": 9000, "cache_free_kb": 9000},
        {"kind": "tool_timeout"},
    ], 120.0),
    "s:mess-00:w1": _cell(
        {"kind": "candidate_failure", "cause": "no_submission", "error_type": "CandidateFailure"},
        [_turn(t, 2000 * t, 400) for t in range(1, 21)] + [
            {"kind": "stopped", "cause": "turn_limit"},
            {"kind": "cgroup_peaks", "memory_peak_bytes": 70, "pids_peak": 12, "oom_kills": 0,
             "workspace_free_kb": 8000, "cache_free_kb": 9000},
        ],
        880.0,
    ),
    "s:mess-00:w2": _cell(
        {"kind": "infrastructure_failure", "cause": "harness_deadline",
         "error_type": "InfrastructureFailure"},
        [_turn(1, 900, 100), {"kind": "stopped", "cause": "agent_deadline"}], 900.0,
    ),
}


def test_quantile_is_an_observed_value() -> None:
    assert quantile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 0.95) == 10
    assert quantile([3, 1, 2], 0.5) == 2


def test_stop_cause_keeps_the_loop_reason() -> None:
    assert stop_cause(CELLS["s:mess-00:w0"]) == "candidate"
    assert stop_cause(CELLS["s:mess-00:w1"]) == "no_submission:turn_limit"
    assert stop_cause(CELLS["s:mess-00:w2"]) == "harness_deadline:agent_deadline"


def test_cell_metrics_count_every_cell_and_turn() -> None:
    m = cell_metrics(CELLS)
    assert m["cells"] == 3 and m["turns"] == 23
    assert m["outcomes"] == {
        "candidate": 1, "harness_deadline:agent_deadline": 1, "no_submission:turn_limit": 1
    }
    assert m["prompt_tokens"]["max"] == 40_000
    assert m["completion_tokens"]["max"] == 8192
    assert m["turns_at_output_cap"] == 1
    assert m["turns_per_cell"] == {"min": 1, "median": 2, "max": 20}
    assert m["cells_at_deadline"] == 1
    assert m["memory_peak_bytes_max"] == 70 and m["workspace_free_kb_min"] == 8000
    assert m["tool_events"] == {"tool_timeout": 1}
    assert m["cell_coverage"] == {"missing": 3}
    assert 4 < m["bytes_per_prompt_token"]["min"] < 5


def test_paid_cells_are_derived_from_accounting() -> None:
    cells = {name: dict(cell) for name, cell in CELLS.items()}
    cells["s:mess-00:w0"]["accounting"] = {"coverage": "measured", "amount": 1.25}
    cells["s:mess-00:w1"]["accounting"] = {"coverage": "uncertain", "amount": None}
    assert cell_metrics(cells)["paid_cells"] == 1


def test_report_reads_nonzero_paid_cells_from_bundle(monkeypatch: pytest.MonkeyPatch) -> None:
    import workflow_edit.publish as publish

    smoke = read_evidence("smoke")
    cell = next(iter(smoke["cells"].values()))
    cell["accounting"] = {"coverage": "measured", "amount": 1.25}
    monkeypatch.setattr(
        publish, "read_evidence",
        lambda name: smoke if name == "smoke" else read_evidence(name),
    )
    assert "Paid cells: 1." in publish.render_original()
    assert "Cost correction: Paid cells: 1," in publish.render()


def test_regraded_report_names_each_changed_grade_and_cause(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    import workflow_edit.publish as publish

    smoke_bundle = b"synthetic compressed smoke bundle"
    (tmp_path / "smoke.json.gz").write_bytes(smoke_bundle)
    regrade = {
        "smoke_sha256": digest_bytes(smoke_bundle),
        "regraded_at": "2026-10-17",
        "image": "sha256:fixed-image",
        "original_harness_sha256": "sha256:original",
        "harness_sha256": "sha256:fixed",
        "evaluations": {"cell-a": {}, "cell-b": {}},
        "changed_grades": {
            "cell-a": {
                "before": {
                    "verdict": "incorrect", "cause": "test_failure",
                    "groups": {"new_behavior": {"status": "failed", "cause": "test_failure"}},
                },
                "after": {
                    "verdict": "correct", "cause": None,
                    "groups": {"new_behavior": {"status": "passed", "cause": None}},
                },
            },
            "cell-b": {
                "before": {
                    "verdict": "incorrect", "cause": "typecheck_failure",
                    "groups": {"typecheck": {"status": "failed", "cause": "typecheck_failure"}},
                },
                "after": {
                    "verdict": "incorrect", "cause": "test_failure",
                    "groups": {"typecheck": {"status": "failed", "cause": "test_failure"}},
                },
            },
        },
    }
    pricing = {
        "fetched_at": "2026-10-17", "model": {"id": "m"},
        "endpoints": [{
            "provider_name": "p", "pricing": {"prompt": "0.000001", "completion": "0.000002"},
            "context_length": 262144, "max_completion_tokens": 65536,
        }],
    }
    evidence = {"regrade": regrade, "smoke": {"cells": CELLS}, "pricing": pricing}
    monkeypatch.setattr(publish, "EVIDENCE", tmp_path)
    monkeypatch.setattr(publish, "read_evidence", evidence.__getitem__)

    report = render_regraded()
    assert "2 previously graded candidates were regraded; 2 grades changed." in report
    assert "| Cell | Original | Regraded | Changed groups and cause |" in report
    assert (
        "| cell-a | incorrect | correct | new_behavior: failed (test_failure) to passed |"
        in report
    )
    assert (
        "| cell-b | incorrect | incorrect | "
        "typecheck: failed (typecheck_failure) to failed (test_failure) |"
        in report
    )


def test_regraded_report_rejects_stale_smoke_bundle(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    import workflow_edit.publish as publish

    (tmp_path / "smoke.json.gz").write_bytes(b"new smoke bundle")
    monkeypatch.setattr(publish, "EVIDENCE", tmp_path)
    evidence = {"regrade": {"smoke_sha256": digest_bytes(b"old smoke bundle")}}
    monkeypatch.setattr(
        publish, "read_evidence", evidence.__getitem__,
    )

    with pytest.raises(ValueError, match="regrade smoke_sha256 does not match"):
        render_regraded()


def test_correctness_counts_against_dispatched_cells() -> None:
    evaluations = {
        "s:mess-00:w0": {"verdict": "correct", "empty_patch": False, "seconds": 9.0,
                         "groups": {"new_behavior": {"status": "passed", "cause": None}}},
    }
    c = correctness_metrics(CELLS, evaluations)
    assert c["dispatched"] == 3 and c["evaluated"] == 1 and c["correct_of_dispatched"] == 1
    assert c["groups"] == {"new_behavior": {"passed": 1}}


def test_failure_diagnosis_counts_candidates_per_test_and_error() -> None:
    diagnosis = {"cells": {
        "a": {"failing_tests": {"hidden_regression": ["pinned rule"], "new_behavior": ["x"]}},
        "b": {"failing_tests": {"hidden_regression": ["pinned rule"]}},
        "c": {"typecheck_errors": [
            {"code": "TS2322", "file": "src/r.ts", "message": "m"},
            {"code": "TS2322", "file": "src/r.ts", "message": "n"},
        ]},
    }}
    d = failure_diagnosis(diagnosis)
    assert d["diagnosed"] == 3 and d["typecheck_failures"] == 1
    assert d["tests"] == [(("hidden_regression", "pinned rule"), 2), (("new_behavior", "x"), 1)]
    assert d["typecheck_errors"] == [("TS2322 src/r.ts", 1)]


def test_hosted_worst_case_charges_every_byte_and_the_full_output_cap() -> None:
    pricing = {
        "fetched_at": "t", "model": {"id": "m"},
        "endpoints": [{"provider_name": "p", "pricing": {"prompt": "0.000001",
                                                          "completion": "0.000002"},
                       "context_length": 262144, "max_completion_tokens": 65536}],
    }
    settings = Part1AgentSettings()
    hosted = hosted_worst_case(pricing, bytes_per_token_floor=4.0, settings=settings)
    row = hosted["endpoints"][0]
    strict = 20 * (settings.max_request_bytes * 1e-6 + settings.max_output_tokens * 2e-6)
    assert row["strict_usd"] == pytest.approx(strict)
    assert row["measured_usd"] < row["strict_usd"]
    assert row["fits_context"]


def test_probe_rows_compare_observed_to_expected() -> None:
    probes = {"rejections": {
        "tampering": {"expected": "tampering", "retained_artifacts": ["x"],
                      "outcome": {"kind": "candidate_failure", "cause": "tampering"}},
        "empty_patch": {"expected": "candidate", "retained_artifacts": [],
                        "outcome": {"kind": "candidate"}, "evaluation": {"verdict": "incorrect"}},
    }}
    rows = {row["probe"]: row for row in probe_rows(probes)}
    assert rows["tampering"]["matches"] and rows["empty_patch"]["matches"]
    assert rows["empty_patch"]["evaluation"] == "incorrect"


@pytest.mark.skipif(
    not all(
        (EVIDENCE / f"{name}.json.gz").exists()
        for name in ("smoke", "probes", "wake", "pricing", "diagnosis", "regrade")
    ),
    reason="wf-13 evidence not yet published",
)
def test_committed_smoke_report_is_exactly_the_evidence() -> None:
    assert SMOKE_MD.read_text(encoding="utf-8") == render()
    original = SMOKE_MD.read_bytes().split(b"\n## Regraded (", maxsplit=1)[0]
    assert original == render_original().encode("utf-8")
    assert hashlib.sha256(original).hexdigest() == (
        "6d972e85db40038b6fac594bf9f507636a2984b66ae8640878dfb7d68f8344cc"
    )
