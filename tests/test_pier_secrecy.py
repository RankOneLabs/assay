"""No hidden, other-arm, evaluator, or object-store byte ever reaches a package."""

from __future__ import annotations

from pathlib import Path

import pytest

from assay.pier_packaging import build_package

FIXTURES = Path(__file__).parent / "fixtures" / "pier_packages"

VISIBLE_SENTINEL = "SENTINEL_ARM_A_VISIBLE_1a2b"
FORBIDDEN_SENTINELS = (
    "SENTINEL_OTHER_ARM_HIDDEN_3c4d",
    "SENTINEL_HIDDEN_TEST_5e6f",
    "SENTINEL_EVALUATOR_7g8h",
    "SENTINEL_OBJECT_METADATA_9i0j",
)


@pytest.fixture
def package_text() -> str:
    package = build_package(
        cell_id="s1:arm-a:w0",
        task="Implement solve() so it returns the correct value.",
        repository_root=FIXTURES / "arm_a",
    )
    return "\n".join(content for _path, content in package.files)


def test_selected_arm_content_is_visible(package_text: str) -> None:
    assert VISIBLE_SENTINEL in package_text


@pytest.mark.parametrize("sentinel", FORBIDDEN_SENTINELS)
def test_forbidden_sentinel_never_reaches_the_package(package_text: str, sentinel: str) -> None:
    assert sentinel not in package_text


def test_arm_identifier_never_reaches_the_package(package_text: str) -> None:
    assert "arm-a" not in package_text
    assert "s1:arm-a:w0" not in package_text
