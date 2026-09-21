from __future__ import annotations

import os
from pathlib import Path

import pytest

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
