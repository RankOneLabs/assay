"""Shared pytest setup for experiment suites that reuse core test fixtures."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT_TESTS = Path(__file__).resolve().parent.parent / "tests"
sys.path.insert(0, str(ROOT_TESTS))

RUN_RECEIPTS_ENV_VAR = "ASSAY_RUN_RECEIPTS"
_RUN_RECEIPTS_VALUE = os.environ.get(RUN_RECEIPTS_ENV_VAR)
RUN_RECEIPTS_CHECKOUT = (
    Path(_RUN_RECEIPTS_VALUE).expanduser().resolve() if _RUN_RECEIPTS_VALUE else None
)


@pytest.fixture
def optional_run_receipts_checkout() -> Path | None:
    return RUN_RECEIPTS_CHECKOUT


@pytest.fixture
def run_receipts_checkout() -> Path:
    if RUN_RECEIPTS_CHECKOUT is None:
        pytest.skip(f"{RUN_RECEIPTS_ENV_VAR} is not set")
    return RUN_RECEIPTS_CHECKOUT


@pytest.fixture
def relevance_catalogues(run_receipts_checkout: Path) -> Path:
    """The Scout relevance catalogues are private; they live in run-receipts."""
    return run_receipts_checkout / "scout-relevance-2026-09/catalogues"
