"""Directory snapshot and command-line contract."""

import json
import sys
from pathlib import Path

import pytest
from code_metrics_fixtures import stub_jscpd
from jsonschema import Draft202012Validator

from assay import cli
from assay.canonical import canonical_json
from assay.code_metrics import analyze, cli_snapshot
from assay.code_metrics.cli_snapshot import DEFAULT_EXCLUDED_DIRECTORIES, snapshot_directory


def test_snapshot_prunes_default_directories_and_extends_globs(tmp_path: Path) -> None:
    for directory in (".venv", "__pycache__", ".assay", "src", "skip"):
        target = tmp_path / directory / "sample.py"
        target.parent.mkdir()
        target.write_text("value = 1\n")
    files, excluded = snapshot_directory(tmp_path, exclude=("skip",))
    assert files == {"src/sample.py": "value = 1\n"}
    assert excluded == tuple(sorted(DEFAULT_EXCLUDED_DIRECTORIES | {"skip"}))


def test_snapshot_decodes_sources_as_python_does(tmp_path: Path) -> None:
    (tmp_path / "latin.py").write_bytes(b"# -*- coding: latin-1 -*-\nname = 'caf\xe9'\n")
    (tmp_path / "bom.py").write_bytes(b"\xef\xbb\xbfvalue = 1\n")
    files, _ = snapshot_directory(tmp_path)
    assert files == {
        "bom.py": "value = 1\n",
        "latin.py": "# -*- coding: latin-1 -*-\nname = 'café'\n",
    }


def test_snapshot_rejects_an_unknown_coding_as_value_error(tmp_path: Path) -> None:
    (tmp_path / "odd.py").write_bytes(b"# -*- coding: no-such-codec -*-\n")
    with pytest.raises(ValueError, match="decode odd.py"):
        snapshot_directory(tmp_path)


def test_snapshot_skips_symlinked_files(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (tmp_path / "outside.py").write_text("secret = 1\n")
    (root / "inside.py").write_text("value = 1\n")
    (root / "leak.py").symlink_to(tmp_path / "outside.py")
    files, _ = snapshot_directory(root)
    assert files == {"inside.py": "value = 1\n"}


def _run(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], *args: str) -> dict:
    monkeypatch.setattr(sys, "argv", ["assay", "code-metrics", *args])
    assert cli.main() == 0
    out = capsys.readouterr().out
    result = json.loads(out)
    assert out == canonical_json(result).decode("utf-8")
    return result


def test_unparsable_file_fails_without_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    stub_jscpd(monkeypatch)
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg/__init__.py").write_text("")
    (tmp_path / "pkg/bad.py").write_text("def f(:\n")
    monkeypatch.setattr(sys, "argv", ["assay", "code-metrics", "snapshot", str(tmp_path)])
    assert cli.main() == 1
    assert capsys.readouterr().out == (
        "code_metrics_snapshot_failed: parse snapshot pkg/bad.py, line 1: invalid syntax\n"
    )


def test_snapshot_and_compare_cli_reports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    stub_jscpd(monkeypatch)
    before = tmp_path / "before"
    after = tmp_path / "after"
    for root in (before, after):
        for directory in (".venv", "__pycache__", ".assay", "src/pkg", "skip"):
            target = root / directory / "a.py"
            target.parent.mkdir(parents=True)
            target.write_text("value = 1\n")
        (root / "src/pkg/__init__.py").write_text("")
    (after / "src/pkg/a.py").write_text("value = 2\n")
    snapshot, excluded = snapshot_directory(before, exclude=("skip",))
    result = _run(monkeypatch, capsys, "snapshot", str(before), "--exclude", "skip", "--json")
    assert result["coverage"]["python_files_seen"] == 2
    assert result["configuration"]["excluded_directories"] == list(excluded)
    assert (
        result["existing_metrics"] == analyze(snapshot).model_dump(mode="json")["existing_metrics"]
    )
    schema_path = Path(__file__).parents[1] / "schemas/assay-code-metrics-report-v0.3.schema.json"
    schema = json.loads(schema_path.read_text())
    Draft202012Validator(schema).validate(result)
    compared = _run(monkeypatch, capsys, "compare", str(before), str(after), "--exclude", "skip")
    assert compared["before"]["configuration"]["excluded_directories"] == list(excluded)
    assert compared["after"]["configuration"]["excluded_directories"] == list(excluded)
    schema = json.loads(
        (
            Path(__file__).parents[1] / "schemas/assay-code-metrics-comparison-v0.4.schema.json"
        ).read_text()
    )
    Draft202012Validator(schema).validate(compared)


def test_malformed_config_is_clean_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "bad.yaml"
    config.write_text("components: [broken\n")
    monkeypatch.setattr(
        sys, "argv", ["assay", "code-metrics", "snapshot", str(tmp_path), "--config", str(config)]
    )
    assert cli.main() == 1
    captured = capsys.readouterr()
    assert captured.out.startswith("code_metrics_snapshot_failed: configure components:")
    assert captured.err == ""


def test_mixed_type_config_keys_fail_cleanly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "bad.yaml"
    config.write_text("1: value\ncomponents: []\n")
    monkeypatch.setattr(
        sys, "argv", ["assay", "code-metrics", "snapshot", str(tmp_path), "--config", str(config)]
    )
    assert cli.main() == 1
    captured = capsys.readouterr()
    assert captured.out == (
        "code_metrics_snapshot_failed: configure components: config keys must be strings\n"
    )
    assert captured.err == ""


@pytest.mark.parametrize("dependency", ["ruff", "mypy"])
def test_missing_pinned_tool_prints_install_hint(
    dependency: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    original_import = cli.import_module

    def missing_tool(name: str) -> object:
        if name == dependency:
            raise ModuleNotFoundError(f"No module named '{name}'", name=name)
        return original_import(name)

    monkeypatch.setattr(cli, "import_module", missing_tool)
    monkeypatch.setattr(sys, "argv", ["assay", "code-metrics", "snapshot", str(tmp_path)])
    assert cli.main() == 1
    captured = capsys.readouterr()
    assert "install assay[code-metrics]" in captured.out
    assert f"missing {dependency}" in captured.out
    assert captured.err == ""


@pytest.mark.parametrize("pattern", ["", "/absolute", r"bad\glob"])
@pytest.mark.parametrize("command", ["snapshot", "compare"])
def test_invalid_exclude_fails_before_analysis(
    command: str,
    pattern: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    paths = [str(tmp_path)] if command == "snapshot" else [str(tmp_path), str(tmp_path)]
    monkeypatch.setattr(
        sys, "argv", ["assay", "code-metrics", command, *paths, "--exclude", pattern]
    )
    assert cli.main() == 1
    captured = capsys.readouterr()
    assert f"code_metrics_{command}_failed: invalid exclude glob" in captured.out
    assert captured.err == ""


def test_snapshot_walk_errors_are_not_silently_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failed_walk(*args: object, onerror: object = None, **kwargs: object) -> object:
        assert callable(onerror)
        onerror(OSError("cannot scan subtree"))
        yield ()

    monkeypatch.setattr(cli_snapshot.os, "walk", failed_walk)
    with pytest.raises(OSError, match="cannot scan subtree"):
        snapshot_directory(tmp_path)
