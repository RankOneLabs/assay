from __future__ import annotations

import os
from pathlib import Path

import pytest

from assay.pier_packaging import (
    INSTRUCTION_PATH,
    SUBMISSION_CONTRACT_PATH,
    WORKSPACE_PREFIX,
    _manifest_digest,
    build_package,
    gate_package,
    non_repository_entries,
    render_instruction,
    repository_only_entries,
)
from assay.repository import validate_repository, validate_source_tree


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
    with pytest.raises(ValueError, match="unsafe repository path"):
        validate_repository({"../escape.py": "x = 1\n"})


def test_validate_repository_rejects_case_folded_duplicate_paths() -> None:
    with pytest.raises(ValueError, match="duplicate repository path"):
        validate_repository({"Solution.py": "a = 1\n", "solution.py": "b = 2\n"})


def test_gate_package_accepts_the_expected_digest(tmp_path: Path) -> None:
    root = _write_tree(tmp_path / "arm", {"solution.py": "print('hi')\n"})
    package = build_package(cell_id="s1:a1:w0", task="Do the thing.", repository_root=root)
    gate_package(package, expected_digest=package.manifest_digest)


def test_gate_package_rejects_a_mismatched_digest(tmp_path: Path) -> None:
    root = _write_tree(tmp_path / "arm", {"solution.py": "print('hi')\n"})
    package = build_package(cell_id="s1:a1:w0", task="Do the thing.", repository_root=root)
    with pytest.raises(ValueError, match="digest does not match"):
        gate_package(package, expected_digest="sha256:" + "0" * 64)


def test_gate_package_rejects_forged_content_with_an_unchanged_digest_field(
    tmp_path: Path,
) -> None:
    from dataclasses import replace

    root = _write_tree(tmp_path / "arm", {"solution.py": "print('hi')\n"})
    package = build_package(cell_id="s1:a1:w0", task="Do the thing.", repository_root=root)
    forged_files = tuple(
        (path, content if path != f"{WORKSPACE_PREFIX}/solution.py" else "print('forged')\n")
        for path, content in package.files
    )
    forged = replace(package, files=forged_files)  # manifest_digest left unchanged
    with pytest.raises(ValueError, match="digest does not match"):
        gate_package(forged, expected_digest=forged.manifest_digest)


def test_gate_package_rejects_a_forbidden_sentinel(tmp_path: Path) -> None:
    root = _write_tree(tmp_path / "arm", {"solution.py": "SENTINEL_LEAK = 1\n"})
    package = build_package(cell_id="s1:a1:w0", task="Do the thing.", repository_root=root)
    with pytest.raises(ValueError, match="forbidden sentinel"):
        gate_package(
            package,
            expected_digest=package.manifest_digest,
            forbidden_substrings=("SENTINEL_LEAK",),
        )


def test_gate_package_rejects_a_non_allowlisted_entry(tmp_path: Path) -> None:
    from dataclasses import replace

    root = _write_tree(tmp_path / "arm", {"solution.py": "print('hi')\n"})
    package = build_package(cell_id="s1:a1:w0", task="Do the thing.", repository_root=root)
    tampered_files = (*package.files, ("evaluator/rubric.json", "{}"))
    digest = _manifest_digest(dict(sorted(tampered_files)))
    tampered = replace(package, files=tampered_files, manifest_digest=digest)
    with pytest.raises(ValueError, match="outside the allowlist"):
        gate_package(tampered, expected_digest=tampered.manifest_digest)


def test_gate_package_rejects_a_traversal_segment_inside_the_workspace_prefix(
    tmp_path: Path,
) -> None:
    from dataclasses import replace

    root = _write_tree(tmp_path / "arm", {"solution.py": "print('hi')\n"})
    package = build_package(cell_id="s1:a1:w0", task="Do the thing.", repository_root=root)
    tampered_files = (*package.files, (f"{WORKSPACE_PREFIX}/../evaluator/rubric.json", "{}"))
    digest = _manifest_digest(dict(sorted(tampered_files)))
    tampered = replace(package, files=tampered_files, manifest_digest=digest)
    with pytest.raises(ValueError, match="unsafe path"):
        gate_package(tampered, expected_digest=tampered.manifest_digest)


def test_gate_package_rejects_a_duplicate_path(tmp_path: Path) -> None:
    from dataclasses import replace

    root = _write_tree(tmp_path / "arm", {"solution.py": "print('hi')\n"})
    package = build_package(cell_id="s1:a1:w0", task="Do the thing.", repository_root=root)
    duplicated_files = (*package.files, package.files[0])
    tampered = replace(package, files=duplicated_files)
    with pytest.raises(ValueError, match="duplicate path"):
        gate_package(tampered, expected_digest=tampered.manifest_digest)


def test_dockerfile_context_is_confined_to_the_named_allowlist() -> None:
    dockerfile = Path(__file__).parents[1] / "integrations" / "pier" / "Dockerfile"
    text = dockerfile.read_text(encoding="utf-8")
    allowed_copy_sources = {"pyproject.toml", "uv.lock", "README.md", "src", "config"}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("COPY "):
            continue
        parts = stripped.split()
        if any(part.startswith("--from=") for part in parts):
            continue  # copies from another build stage/image, not the build context
        sources = parts[1:-1]
        assert sources, f"COPY with no explicit source is not allowed: {line}"
        for source in sources:
            assert source in allowed_copy_sources, f"unlisted COPY source: {source}"
