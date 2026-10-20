"""No hidden, other-arm, evaluator, or object-store byte ever reaches a package."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from assay.adapters.pier import PierAdapter, PierBridgeClient
from assay.execution import WorkerFailure
from assay.models import CellCoordinate
from assay.pier_packaging import FORBIDDEN_SENTINELS, build_package, gate_package
from assay.pier_protocol import RuntimeBinding
from assay.store import ObjectStore

FIXTURES = Path(__file__).parent / "fixtures" / "pier_packages"

VISIBLE_SENTINEL = "SENTINEL_ARM_A_VISIBLE_1a2b"
HELD_OUT_SENTINELS = (
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


@pytest.mark.parametrize("sentinel", HELD_OUT_SENTINELS)
def test_forbidden_sentinel_never_reaches_the_package(package_text: str, sentinel: str) -> None:
    assert sentinel not in package_text


def test_arm_identifier_never_reaches_the_package(package_text: str) -> None:
    assert "arm-a" not in package_text
    assert "s1:arm-a:w0" not in package_text


@pytest.mark.parametrize(("category", "sentinel"), FORBIDDEN_SENTINELS)
def test_each_forbidden_category_fails_closed(tmp_path: Path, category: str, sentinel: str) -> None:
    root = tmp_path / "selected_arm"
    root.mkdir()
    (root / "solution.py").write_text(f"marker = {sentinel!r}\n", encoding="utf-8")
    package = build_package(cell_id="s1:arm-a:w0", task="Implement solve()", repository_root=root)
    with pytest.raises(ValueError, match=rf"forbidden sentinel \({category}\)"):
        gate_package(
            package,
            expected_digest=package.manifest_digest,
            forbidden_substrings=dict(FORBIDDEN_SENTINELS),
        )


@pytest.mark.parametrize(("category", "sentinel"), FORBIDDEN_SENTINELS)
async def test_dispatch_uses_authorized_sentinel_set(
    tmp_path: Path, category: str, sentinel: str
) -> None:
    adapter = PierAdapter(
        store=ObjectStore(tmp_path / "objects"),
        bridge=cast(PierBridgeClient, object()),
        binding=RuntimeBinding(
            runtime_version="lock-v1",
            image_digest="sha256:" + "1" * 64,
            configuration_ref="sha256:" + "2" * 64,
            package_digest="sha256:" + "0" * 64,
        ),
        model_route={"model": "test"},
        trial_limits={"timeout_s": 10},
    )
    assert adapter.configuration("arm-a")["forbidden_substrings"][category] == sentinel
    result = await adapter.run_cell(
        input_value={"task": "Implement solve()", "repository": {"solve.py": sentinel}},
        coordinate=CellCoordinate(
            subject_id="s1",
            arm_id="arm-a",
            worker_repeat=0,
            realization_ref="sha256:" + "3" * 64,
        ),
    )
    assert isinstance(result, WorkerFailure)
    assert category in result.message
