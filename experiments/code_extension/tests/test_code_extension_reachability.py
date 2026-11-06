"""The reachability split follows the failed test titles in retained output."""

from __future__ import annotations

import pytest
from code_extension.reachability import feature_failure


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        ("(pass) reachability: found\n(pass) semantics: ok [1.20ms]\n", None),
        ("(pass) reachability: found\n(fail) semantics: rejects [0.50ms]\n", "semantic"),
        ("(fail) reachability: found [1.00ms]\n(fail) semantics: rejects\n", "reachability"),
        ("(fail) something else [1.00ms]\n", "unattributed"),
        ("", None),
    ],
)
def test_failed_titles_decide_the_split(output: str, expected: str | None) -> None:
    assert feature_failure(output) == expected
