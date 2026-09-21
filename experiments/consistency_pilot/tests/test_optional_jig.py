"""The consistency-pilot paths fail actionably without their optional stack."""

from __future__ import annotations

import sys
from collections.abc import Callable
from unittest.mock import patch

import pytest
from consistency_pilot import dry_experiment, openrouter_smoke, pilot, realistic_pilot


@pytest.mark.parametrize(
    "action",
    [
        pilot._import_legacy_worker_stack,
        dry_experiment.haiku_dry_settings,
        realistic_pilot.realistic_haiku_settings,
        openrouter_smoke.qwen_smoke_settings,
    ],
)
def test_legacy_paths_fail_actionably(action: Callable[[], object]) -> None:
    with (
        patch.dict(sys.modules, {"assay.adapters.consistency": None}),
        pytest.raises(ModuleNotFoundError, match=r"assay\[legacy\]"),
    ):
        action()
