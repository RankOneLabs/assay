from __future__ import annotations

import hashlib
import json
from pathlib import Path

from assay.investigations.relevance.fitted_rerun import build_fitted_report, canonical_bytes

ROOT = Path(__file__).parents[1]
SOURCE = ROOT / "evidence/typesafe-relevance-primary-2026-09/exported-answers.json"
REPORT = ROOT / "evidence/typesafe-relevance-fitted-rerun-2026-09/fitted-oof-results.json"
CHECKSUMS = ROOT / "evidence/typesafe-relevance-fitted-rerun-2026-09/checksums.json"


def test_fitted_report_recomputes_from_retained_answers() -> None:
    source_bytes = SOURCE.read_bytes()
    actual = build_fitted_report(json.loads(source_bytes))
    actual["source_sha256"] = hashlib.sha256(source_bytes).hexdigest()
    assert canonical_bytes(actual) == REPORT.read_bytes()


def test_fitted_rerun_is_exploratory_and_does_not_win() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    assert report["status"] == "exploratory_retrospective"
    assert report["adoption_gate"] is False
    assert report["source_case_count"] == 79
    assert report["source_repeat_count"] == 237
    assert report["selection_rule"]["typesafe_won"] is False
    assert report["metrics"]["typesafe_fitted_oof"]["accuracy"] > report["metrics"][
        "typesafe_argmax"
    ]["accuracy"]
    assert report["metrics"]["typesafe_fitted_oof"]["accuracy"] < report["metrics"][
        "production"
    ]["accuracy"]


def test_fitted_report_checksums() -> None:
    checksums = json.loads(CHECKSUMS.read_text(encoding="utf-8"))
    for name, digest in checksums.items():
        assert hashlib.sha256((CHECKSUMS.parent / name).read_bytes()).hexdigest() == digest
