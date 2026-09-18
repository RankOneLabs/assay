"""A fixed, checked-in 0.1.0 report stays byte-exact under the dual-version core.

Complements ``tests/test_legacy_bundle.py`` (manifest-rooted) by pinning a *report*
document: offline recomputation from the fixture's own pinned config must reproduce the
identical report bytes and digest, not merely pass verification.
"""

from __future__ import annotations

import json
from pathlib import Path

from assay.canonical import canonical_json, digest_bytes
from assay.models import ReportConfig
from assay.report_engine import build_report
from assay.store import ObjectStore
from assay.verify import verify_bundle, verify_report

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "legacy-0.1.0-report-bundle" / "bundle"
REPORT_REF = "sha256:c89c984a842bd43d60f6b504b1465e76fda06554981f7fe20e97e9a1b329b91c"


def test_fixture_report_verifies_and_is_exactly_its_own_closure() -> None:
    store = ObjectStore(FIXTURE_ROOT)
    assert verify_report(store, REPORT_REF) == ()
    assert verify_bundle(store, REPORT_REF) == ()


def test_offline_recomputation_reproduces_the_identical_report_digest_and_root() -> None:
    store = ObjectStore(FIXTURE_ROOT)
    report = json.loads(store.read_bytes(REPORT_REF))
    config = ReportConfig.model_validate(json.loads(store.read_bytes(report["config_ref"])))

    recomputed = build_report(store, config)

    assert recomputed == report
    assert digest_bytes(canonical_json(recomputed)) == REPORT_REF
