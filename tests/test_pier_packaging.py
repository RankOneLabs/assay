from __future__ import annotations

import os
from pathlib import Path

import pytest

from assay.pier_packaging import (
    INSTRUCTION_PATH,
    SUBMISSION_CONTRACT_PATH,
    WORKSPACE_PREFIX,
    build_package,
    non_repository_entries,
    render_instruction,
    repository_only_entries,
)
from assay.repository import validate_source_tree


def _write_tree(root: Path, files: dict[str, str]) -> Path:
    for path, content in files.items():
        full = root / path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content, encoding="utf-8")
    return root


def test_render_instruction_rejects_blank_task() -> None:
    with pytest.raises(ValueError, match="nonblank"):
        render_instruction("   ")


def test_build_package_is_deterministic(tmp_path: Path) -> None:
    root = _write_tree(tmp_path / "arm", {"solution.py": "print('hi')\n"})
    first = build_package(cell_id="s1:a1:w0", task="Do the thing.", repository_root=root)
    second = build_package(cell_id="s1:a1:w0", task="Do the thing.", repository_root=root)
    assert first.files == second.files
    assert first.manifest_digest == second.manifest_digest


def test_build_package_only_contains_allowlisted_entries(tmp_path: Path) -> None:
    root = _write_tree(
        tmp_path / "arm", {"solution.py": "print('hi')\n", "nested/util.py": "x = 1\n"}
    )
    package = build_package(cell_id="s1:a1:w0", task="Do the thing.", repository_root=root)
    paths = {path for path, _ in package.files}
    assert INSTRUCTION_PATH in paths
    assert SUBMISSION_CONTRACT_PATH in paths
    assert f"{WORKSPACE_PREFIX}/solution.py" in paths
    assert f"{WORKSPACE_PREFIX}/nested/util.py" in paths
    assert paths == {
        INSTRUCTION_PATH,
        SUBMISSION_CONTRACT_PATH,
        f"{WORKSPACE_PREFIX}/solution.py",
        f"{WORKSPACE_PREFIX}/nested/util.py",
    }


def test_non_repository_entries_match_byte_for_byte_across_arms(tmp_path: Path) -> None:
    arm_a = _write_tree(tmp_path / "arm_a", {"solution.py": "print('a')\n"})
    arm_b = _write_tree(tmp_path / "arm_b", {"solution.py": "print('b')\n", "extra.py": "y = 2\n"})
    package_a = build_package(cell_id="s1:a1:w0", task="Do the thing.", repository_root=arm_a)
    package_b = build_package(cell_id="s1:a2:w0", task="Do the thing.", repository_root=arm_b)

    assert non_repository_entries(package_a) == non_repository_entries(package_b)
    assert repository_only_entries(package_a) != repository_only_entries(package_b)


def test_cell_id_is_never_written_into_a_file(tmp_path: Path) -> None:
    root = _write_tree(tmp_path / "arm", {"solution.py": "print('hi')\n"})
    package = build_package(cell_id="s1:a1:w0", task="Do the thing.", repository_root=root)
    for _path, content in package.files:
        assert "s1:a1:w0" not in content


def test_validate_source_tree_rejects_symlink(tmp_path: Path) -> None:
    root = tmp_path / "arm"
    root.mkdir()
    target = tmp_path / "outside.py"
    target.write_text("secret = 1\n", encoding="utf-8")
    (root / "link.py").symlink_to(target)
    with pytest.raises(ValueError, match="symlink"):
        validate_source_tree(root)


def test_validate_source_tree_rejects_special_file(tmp_path: Path) -> None:
    root = tmp_path / "arm"
    root.mkdir()
    fifo = root / "pipe"
    os.mkfifo(fifo)
    with pytest.raises(ValueError, match="special file"):
        validate_source_tree(root)


def test_validate_source_tree_rejects_non_utf8(tmp_path: Path) -> None:
    root = tmp_path / "arm"
    root.mkdir()
    (root / "bad.py").write_bytes(b"\xff\xfe\x00\x01")
    with pytest.raises(ValueError, match="UTF-8"):
        validate_source_tree(root)


def test_validate_source_tree_enforces_byte_limit(tmp_path: Path) -> None:
    root = tmp_path / "arm"
    root.mkdir()
    (root / "big.py").write_text("x" * 100, encoding="utf-8")
    with pytest.raises(ValueError, match="byte limit"):
        validate_source_tree(root, max_total_bytes=10)


def test_validate_source_tree_enforces_file_count_limit(tmp_path: Path) -> None:
    root = tmp_path / "arm"
    root.mkdir()
    for index in range(3):
        (root / f"f{index}.py").write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="too many files"):
        validate_source_tree(root, max_files=2)


def test_build_package_rejects_traversal_from_repository_dict(tmp_path: Path) -> None:
    from assay.repository import validate_repository

    with pytest.raises(ValueError, match="unsafe repository path"):
        validate_repository({"../escape.py": "x = 1\n"})
