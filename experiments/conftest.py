"""Shared pytest setup for experiment suites that reuse core test fixtures."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT_TESTS = Path(__file__).resolve().parent.parent / "tests"
sys.path.insert(0, str(ROOT_TESTS))
